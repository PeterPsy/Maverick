"""Managed YouTube metadata/captions and bounded local audio preparation."""

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from content import item, result
from http_client import FetchError, fetch


YT_DLP_VERSION = "2026.8.19"


def youtube_metadata(root: Path, operation: str, parameters: dict) -> dict:
    vendor = root / "vendor"
    if not (vendor / "yt_dlp").is_dir():
        raise FetchError("media_runtime_missing", "The YouTube reader is not installed. Reinstall Connectors to repair its managed runtime.", 503)
    import os
    environment = {key:os.environ[key] for key in ("PATH","LANG","SSL_CERT_FILE","SSL_CERT_DIR") if key in os.environ}
    environment.update(PYTHONPATH=str(vendor),PYTHONNOUSERSITE="1")
    target = "ytsearch"+str(min(parameters["max_items"],30))+":"+parameters["query"] if operation == "search" else parameters["url"]
    command = [sys.executable,"-m","yt_dlp","--ignore-config","--no-cache-dir","--no-playlist","--skip-download",
               "--dump-single-json","--socket-timeout","10","--retries","0","--extractor-retries","0",
               "--js-runtimes","node","--use-extractors","youtube.*","--flat-playlist" if operation == "search" else "--no-flat-playlist","--",target]
    try:
        completed = subprocess.run(command,env=environment,capture_output=True,timeout=50,check=False)
    except subprocess.TimeoutExpired as error:
        raise FetchError("media_timeout","YouTube did not respond within the reading time limit.",504) from error
    if completed.returncode or len(completed.stdout)>8*1024*1024:
        raise FetchError("youtube_unavailable","YouTube could not be read. The video may require login, be restricted, or present a verification challenge.")
    try:
        return json.loads(completed.stdout)
    except ValueError as error:
        raise FetchError("invalid_media_response","The YouTube reader returned invalid metadata.") from error


def captions(data: dict, language: str) -> tuple[list, str, bool]:
    for automatic, tracks in ((False,data.get("subtitles",{})),(True,data.get("automatic_captions",{}))):
        keys = [language] + [key for key in tracks if key.split("-")[0] == language.split("-")[0]] + list(tracks)
        for key in dict.fromkeys(keys):
            track = next((t for t in tracks.get(key,[]) if t.get("ext") == "json3"),None)
            if not track:
                continue
            host = urlsplit(track["url"]).hostname or ""
            if host not in {"www.youtube.com","youtube.com"}:
                continue
            response = fetch(track["url"],allowed_hosts={host},max_bytes=4*1024*1024).json()
            segments = [{"start":e.get("tStartMs",0)/1000,"end":(e.get("tStartMs",0)+e.get("dDurationMs",0))/1000,
                         "text":"".join(s.get("utf8","") for s in e.get("segs",[])).strip()}
                        for e in response.get("events",[]) if e.get("segs")][:10000]
            if segments:
                return segments,key,automatic
    return [],language,False


def audio_clip(root: Path, audio_url: str, seconds: int, *, youtube: bool = False) -> bytes:
    host = urlsplit(audio_url).hostname or ""
    if youtube and not (host.endswith(".googlevideo.com") and re.fullmatch(r"[\w.-]+",host)):
        raise FetchError("invalid_audio_host","YouTube audio must come from its media CDN.",403)
    response = fetch(audio_url,allowed_hosts={host} if youtube else None,max_bytes=32*1024*1024,timeout=20)
    temporary_root = root / "tmp"
    temporary_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temporary_root) as temporary:
        input_path, output_path = Path(temporary)/"input.media", Path(temporary)/"clip.wav"
        input_path.write_bytes(response.content)
        try:
            process = subprocess.run(["ffmpeg","-nostdin","-v","error","-protocol_whitelist","file,pipe","-i",str(input_path),
                                      "-t",str(seconds),"-vn","-ac","1","-ar","16000","-y",str(output_path)],
                                     capture_output=True,timeout=30,check=False)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise FetchError("audio_conversion_failed","The bounded audio clip could not be prepared.") from error
        if process.returncode or not output_path.exists() or output_path.stat().st_size>6*1024*1024:
            raise FetchError("audio_conversion_failed","The source audio could not be decoded within its limits.")
        return output_path.read_bytes()


def read_youtube(root: Path, operation: str, parameters: dict) -> tuple[dict, bytes | None]:
    data = youtube_metadata(root,operation,parameters)
    if operation == "search":
        items = [item("youtube","https://www.youtube.com/watch?v="+r["id"],r.get("title"),r.get("description"),
                      content_observed=False,duration_seconds=r.get("duration"),author=r.get("channel")) for r in data.get("entries",[]) if r and r.get("id")]
        return result(items,coverage="YouTube search metadata; open a video to read its description or transcript."),None
    observed = item("youtube",data.get("webpage_url") or parameters["url"],data.get("title"),data.get("description"),
                    duration_seconds=data.get("duration"),author=data.get("channel"),published_at=data.get("upload_date"),
                    view_count=data.get("view_count"))
    if operation != "transcript":
        return result([observed]),None
    segments, language, automatic = captions(data,parameters.get("language") or "en")
    if segments:
        observed["transcript"] = {"text":"\n".join(s["text"] for s in segments),"segments":segments,"language":language,
                                  "engine":"youtube_captions","automatic":automatic,"status":"completed","truncated":len(segments)>=10000}
        return result([observed]),None
    formats = [f for f in data.get("formats",[]) if f.get("vcodec") == "none" and f.get("acodec") != "none" and f.get("url")]
    formats.sort(key=lambda f:f.get("abr") or 1000)
    if not formats:
        raise FetchError("transcript_unavailable","This video has no accessible captions or public audio stream.")
    audio = audio_clip(root,formats[0]["url"],parameters["max_seconds"],youtube=True)
    return result([observed],coverage=f"Audio transcription covers the first {parameters['max_seconds']} seconds when captions are unavailable."),audio
