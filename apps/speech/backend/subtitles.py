"""Editor-independent subtitle preparation from measured word intervals."""

import math

from errors import SpeechValidationError


def _number(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise SpeechValidationError(f"{field} must be a finite number in {minimum}...{maximum}.", operation="prepare_subtitles")
    return float(value)


def _integer(body, key, default, minimum, maximum):
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SpeechValidationError(f"{key} must be an integer in {minimum}...{maximum}.", operation="prepare_subtitles")
    return value


def normalized_words(value):
    """Validate word timing without inventing boundaries from sentence durations."""
    if not isinstance(value, list) or len(value) > 100_000:
        raise SpeechValidationError("words must be an array of at most 100000 timed words.", operation="prepare_subtitles")
    result = []
    previous_start = -1.0
    for index, word in enumerate(value):
        if not isinstance(word, dict):
            raise SpeechValidationError(f"words[{index}] must be an object.", operation="prepare_subtitles")
        start = _number(word.get("start"), f"words[{index}].start", 0, 86_400)
        end = _number(word.get("end"), f"words[{index}].end", 0, 86_400)
        text = word.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 1000 or any(c in text for c in ("\0", "\r", "\n")):
            raise SpeechValidationError(f"words[{index}].text must be bounded single-line text.", operation="prepare_subtitles")
        if end <= start or start < previous_start:
            raise SpeechValidationError(f"words[{index}] requires a positive interval and chronological order.", operation="prepare_subtitles")
        item = {"start": start, "end": end, "text": text.strip()}
        if word.get("confidence") is not None:
            item["confidence"] = _number(word["confidence"], f"words[{index}].confidence", 0, 1)
        result.append(item)
        previous_start = start
    return result


def prepare_subtitles(body):
    words = normalized_words(body.get("words"))
    max_words = _integer(body, "max_words", 3, 1, 20)
    max_chars = _integer(body, "max_chars", 42, 1, 200)
    max_duration = _number(body.get("max_duration_seconds", 3.0), "max_duration_seconds", 0.05, 30)
    pause = _number(body.get("pause_threshold_seconds", 0.35), "pause_threshold_seconds", 0, 10)
    offset = _number(body.get("time_offset_seconds", 0), "time_offset_seconds", -86_400, 86_400)
    groups, group = [], []
    for word in words:
        count = len(word["text"].split())
        if count > max_words:
            raise SpeechValidationError("A timing unit exceeds max_words; provide individual word timestamps instead of dividing its duration.", operation="prepare_subtitles")
        text = " ".join(item["text"] for item in [*group, word])
        if group and (sum(len(item["text"].split()) for item in group) + count > max_words or
                      len(text) > max_chars or word["end"] - group[0]["start"] > max_duration or
                      word["start"] - group[-1]["end"] >= pause or group[-1]["text"].endswith((".", "!", "?", ";"))):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)
    captions, records = [], []
    for index, group in enumerate(groups):
        start = round((group[0]["start"] + offset) * 1000)
        boundary = groups[index + 1][0]["start"] if index + 1 < len(groups) else group[-1]["end"]
        end = round((min(group[-1]["end"], boundary) + offset) * 1000)
        if start < 0 or end <= start:
            raise SpeechValidationError("Caption intervals must remain positive at millisecond precision after offset and overlap resolution.", operation="prepare_subtitles")
        text = " ".join(word["text"] for word in group)
        captions.append({"start": start / 1000, "end": end / 1000, "text": text})
        records.append(f"{index + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return {"captions": captions, "srt": "\n".join(records), "caption_count": len(captions),
            "word_count": len(words), "timing_source": "provided_word_intervals",
            "overlong_word_count": sum(len(word["text"]) > max_chars for word in words)}


def _srt_time(milliseconds):
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
