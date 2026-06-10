# Speech

Backend-only speech provider app for workspace text-to-speech and speech-to-text transcription surfaces.

## Contract Notes

- The app declares no frontend, widgets, skills, reference entities, or persisted view surfaces. It is a provider app selected through generic app links.
- `speech` provides `speech.synthesis` v1 through its app backend and `speech.transcription` v1 through backend, CLI, and MCP surfaces. Both interfaces are optional at runtime: capability payloads report whether a usable local engine is available in the current installation.
- The app stores capped synthesis and transcription job metadata under `data/speech/jobs.json` and workspace engine settings under `data/speech/settings.json`. Those two primary JSON paths are exportable through the platform's primary-path export support; Speech does not define a custom export hook. Reusable local TTS cache bytes live under `data/speech/cache/tts/` as derived, non-exportable cache material capped by file count, total bytes, and age; it may be deleted and regenerated. Chat and other consumers never read or write this data directly.
- Synthesis uses the selected local TTS engine from workspace settings. `auto` prefers Piper when a local model is configured, then falls back to `espeak-ng` or `espeak`. `espeak` remains a diagnostic fallback rather than the preferred user voice.
- Transcription supports small bounded inline audio uploads with `transcribe_audio` over the backend and larger workspace Storage audio files with `transcribe_file` over backend, CLI, and MCP. Chat can send microphone dictation as short HTTP binary body chunks with a temporary `session_id`, `chunk_index`, and `final` marker so text appears while the user is still speaking; JSON `audio_base64` remains accepted for compatibility. One-shot microphone dictation is marked with `dictation: true`; Storage/file transcription ignores dictation mode entirely, so literal phrases such as "nuova riga" stay in the transcript instead of becoming editor commands. Inline audio is capped below the core's default body limit and defaults to the `fast` transcription profile unless the backend consumer passes an explicit `profile`; longer recordings should enter Storage and use `transcribe_file`, which keeps the workspace transcription profile such as `balanced`. Chunked dictation is not true streaming ASR: each chunk is still locally transcribed as a bounded inline request, and raw microphone audio is not persisted.
- Workspace settings may select the preferred synthesis engine, transcription engine, and transcription profile (`fast`, `balanced`, or `accurate`). Host paths, model choices, device choices, and compute settings remain operator configuration, not workspace data.
- Piper support is local-only and requires `piper` on `PATH` plus `MAVERICK_SPEECH_PIPER_MODEL` pointing at a local voice model. Optional redacted voice metadata can be supplied with `MAVERICK_SPEECH_PIPER_VOICE_ID`, `MAVERICK_SPEECH_PIPER_LANGUAGE`, and `MAVERICK_SPEECH_PIPER_VOICES_JSON`. Cache misses use a workspace-scoped persistent Piper worker in `auto` mode when the `piper-tts` Python package is available, so repeated Chat TTS chunks reuse the loaded voice instead of spawning the `piper` binary per chunk. The worker prepares WAV channel, sample width, and sample rate parameters before synthesis so Piper voices that write frames directly do not fail with missing channel metadata. Set `MAVERICK_SPEECH_PIPER_WORKER=persistent` to fail visibly instead of falling back to the subprocess path, or `entrypoint` to force per-request subprocess synthesis.
- Speech keeps the core's JSON entrypoint contract but makes `backend/app_backend.py` a thin dispatcher. In `auto` mode it forwards backend requests to a workspace-scoped persistent backend worker, so repeated Chat speech calls reuse imported Python modules, engine discovery caches, voice lists, and model availability checks instead of rebuilding them for every mounted backend request. Set `MAVERICK_SPEECH_BACKEND_WORKER=persistent` to fail visibly instead of falling back to inline handling, or `entrypoint` to force the older per-request backend process.
- The local STT path prefers `faster-whisper` when the optional speech dependency and profile model are installed locally. `fast` maps to `base` with `beam_size=1`, `cpu`, and `int8` by default; `balanced` maps to `small`; `accurate` maps to `medium`. Profile-specific operator overrides such as `MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL` take precedence over the legacy global `MAVERICK_SPEECH_FASTER_WHISPER_MODEL`. The legacy global model applies to the workspace default `balanced` profile only unless `MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES=1` is set, which prevents one large global model from accidentally making Chat's `fast` dictation slow. `faster-whisper` runs with `local_files_only` and uses a workspace-scoped persistent worker in `auto` mode so backend subprocess requests can reuse a loaded model while still reporting fallback metadata if the worker cannot start. Set `MAVERICK_SPEECH_FASTER_WHISPER_WORKER=persistent` to fail visibly instead of falling back, or `entrypoint` to force the older per-entrypoint worker. Worker sockets, pid files, temporary dictation session metadata, and logs live under `data/speech/run/`; `worker_status` is exposed through backend and CLI to report lifecycle state by effective transcription profile and prune stale PID/socket files without loading a model by default. Chat calls `prewarm_worker` automatically after resolving an available Speech transcription provider whose `inline_default_profile_available` is not false; CLI callers can also use `prewarm_worker` explicitly. Capability payloads report both the workspace profile availability and the inline default `fast` profile availability, so a `balanced` workspace setting does not hide whether Chat dictation can actually run. Device and compute settings use `MAVERICK_SPEECH_FASTER_WHISPER_DEVICE` and `MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE` when an operator wants to override profile defaults. `MAVERICK_SPEECH_TRANSCRIPTION_PROMPT`, `MAVERICK_SPEECH_TRANSCRIPTION_GLOSSARY`, and `MAVERICK_SPEECH_TRANSCRIPTION_GLOSSARY_FILE` provide a local faster-whisper `initial_prompt` for project names, app names, commands, and common vocabulary; public settings report only whether a prompt is configured. `whisper.cpp` can be enabled through `MAVERICK_SPEECH_WHISPER_CPP_BINARY` and `MAVERICK_SPEECH_WHISPER_CPP_MODEL`. Health and settings payloads report only redacted configured/available booleans, not host paths.
- The app contract declares `hook_timeouts.backend_seconds: 300` so HTTP backend transcription requests are not killed by the core's 30-second default before Speech can return a clean response.
- Compressed audio duration validation requires `ffprobe`. WAV duration is read directly; compressed formats fail clearly when `ffprobe` is unavailable instead of bypassing duration limits.
- Synthesis responses return bounded inline WAV audio as `audio_base64` plus `content_type` and `retention: derived_cache`. Repeated identical synthesis requests reuse workspace-scoped cached WAV bytes under `data/speech/cache/tts/`; the cache key includes engine binary/model/config file fingerprints, small file hashes, and optional operator-supplied Piper model/config digests so voice changes do not silently serve stale audio. Age-based cache eviction is opportunistic and bounded by a cleanup marker, while every cache miss still enforces the count and byte caps so chunked playback bursts cannot grow the cache past its configured limits. Oversize generated audio is rejected before cache write. Generated audio artifacts are not written under workspace storage and only capped job metadata is persisted.
- Transcription responses return text, per-chunk text when chunked dictation is used, segments with timestamps, language metadata, engine metadata, profile metadata, worker latency metadata when available, timing metrics (`transcription_seconds`, `audio_duration_seconds`, and realtime factor), normalized dictation commands, and `retention: metadata_only`. Raw microphone audio is not persisted by the app. When callers omit a language hint, local Whisper engines auto-detect the spoken language; Chat uses this path by default so Italian speech is not forced through the browser UI language.
- The app does not request network or secret permissions. Future cloud provider support must declare outbound targets and logical secret names in the contract instead of storing raw values in `data/speech`.

## Backend Operations

- `capabilities`
- `operations.manifest`
- `list_engines`
- `engine_health`
- `get_settings`
- `set_engine`
- `synthesize`
- `transcribe_audio`
- `transcribe_file`
- `worker_status`
- `prewarm_worker`

`transcribe_audio` accepts small HTTP binary uploads such as browser `audio/webm` recordings, with `action`, `language`, `profile`, optional `session_id`, optional `chunk_index`, optional `final`, and optional `dictation` carried in the query string. It also accepts small JSON `audio_base64` payloads for backend consumers that cannot send binary bodies. The core spools non-JSON backend request bodies under the app data root for the duration of the request; Speech validates that spooled path before transcription and raw microphone audio is deleted by the core after the backend call returns. `transcribe_file` accepts normalized workspace-relative paths under `storage/uploaded/` or `storage/generated/`; absolute paths, traversal, and split `storage_role`/`relative_path` payloads are rejected.
Consumers should omit `language` unless the user explicitly selected the spoken language for this recording or the consumer is sending a short-lived adaptive hint from the same dictation flow. When a caller does pass a short BCP-47-style hint such as `en`, `en-us`, or `it`, Speech validates that hint and passes only the primary language subtag, such as `en` or `it`, to local Whisper engines because those engines reject regional tags such as `en-us`. Backend consumers may pass `profile: "fast" | "balanced" | "accurate"` on `transcribe_audio`; omitted inline audio uses `fast`, while `transcribe_file` keeps the workspace setting.

CLI exposes engine inspection, persistent worker status, and Storage-file transcription:

```bash
maverick app speech cli run speech --action engine_health
maverick app speech cli run speech --action list_engines
maverick app speech cli run speech --action get_settings
maverick app speech cli run speech --action worker_status
maverick app speech cli run speech --action prewarm_worker
maverick app speech cli run speech --action transcribe_file --workspace-relative-path storage/uploaded/example.wav
```

`engine_health` and `list_engines` omit full voice arrays by default to keep CLI output compact. Pass `--include-voices true` when full voice metadata is needed.

MCP exposes the operations manifest, the empty reference manifest, and Storage-file transcription:

```bash
maverick app speech mcp call speech_transcribe_file --workspace-relative-path storage/uploaded/example.wav
```

The exact wrapper flag spelling is discoverable through `maverick app speech cli inspect speech --json` and `maverick app speech mcp inspect speech_transcribe_file --json`.

`synthesize` and `transcribe_audio` are backend consumer operations only. They are intentionally not CLI operations because they require generated audio bytes or inline audio payloads.

## Operational Runbook

Use one-shot shell commands to prepare packages and local models. Persist `MAVERICK_SPEECH_*` values in the backend service environment, then restart the Maverick backend. Exporting variables in an interactive shell affects only commands started from that shell; it does not reconfigure an already-running backend process.

For local operator-managed installs where the backend launcher cannot pass service
environment variables, Speech app entrypoints also read an optional
installation-local `.maverick/speech.env` file. That file may define `PATH` and
`MAVERICK_SPEECH_*` values only; it is local runtime configuration, not
workspace app data.

### STT with faster-whisper

From the repository root, install the optional Speech dependencies into the backend Python environment:

```bash
python3 -m pip install -e '.[speech]'
```

Speech runs `faster-whisper` with `local_files_only`. The default `balanced` transcription profile maps to `small`, so `Systran/faster-whisper-small` must already be present in the Hugging Face cache for the backend user or be configured as a local model path. Prefetch the default balanced model with:

```bash
python3 - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download("Systran/faster-whisper-small")
PY
```

Alternatively, place the model in an operator-managed directory and persist this in the backend service environment:

```bash
MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL=/srv/maverick/models/faster-whisper-small
```

Optional backend environment values:

```bash
MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL=/srv/maverick/models/faster-whisper-base
MAVERICK_SPEECH_FASTER_WHISPER_ACCURATE_MODEL=/srv/maverick/models/faster-whisper-medium
MAVERICK_SPEECH_FASTER_WHISPER_DEVICE=auto
MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE=default
MAVERICK_SPEECH_FASTER_WHISPER_BEAM_SIZE=5
MAVERICK_SPEECH_BACKEND_WORKER=auto
MAVERICK_SPEECH_BACKEND_WORKER_IDLE_SECONDS=21600
MAVERICK_SPEECH_FASTER_WHISPER_WORKER=auto
MAVERICK_SPEECH_FASTER_WHISPER_WORKER_IDLE_SECONDS=21600
MAVERICK_SPEECH_TRANSCRIPTION_GLOSSARY="Maverick, Loopino, Storage, nuova riga, cancella ultima frase"
```

Profile names resolve as `fast -> base`, `balanced -> small`, and `accurate -> medium` when no matching profile-specific environment variable is set. `MAVERICK_SPEECH_FASTER_WHISPER_MODEL` is retained for older installs but no longer overrides every profile by default; set `MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES=1` only when one model should intentionally serve fast, balanced, and accurate. Directory model fingerprints include config/tokenizer content hashes plus size/mtime metadata for root-level weight files such as `model.bin`, `*.bin`, and `*.safetensors`, so replacing weights in place changes the worker identity without hashing large model contents.

For true realtime local ASR, Speech should add a dedicated streaming engine rather than stretch file-oriented `faster-whisper`. The planned candidates are `sherpa-onnx` for local streaming ASR/VAD or a `whisper.cpp` streaming/server mode. For a more natural local TTS alternative to Piper, Kokoro ONNX is the candidate to evaluate behind the same local engine boundary; it is not bundled or selected by default.

### TTS with Piper

Install Piper into the backend environment:

```bash
python3 -m pip install piper-tts
command -v piper
```

If `piper` does not appear in `PATH`, install a distro/package binary or add the pip script directory to the backend service `PATH`. Speech checks for the `piper` executable and will report Piper unavailable when the binary is not reachable.

Download a voice model and config from a pinned Hugging Face revision or tag, not from `main`:

```bash
mkdir -p /srv/maverick/models/piper/en_US-lessac-medium
curl -fL -o /srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -fL -o /srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

Persist the model path and optional metadata in the backend service environment:

```bash
MAVERICK_SPEECH_PIPER_MODEL=/srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx
MAVERICK_SPEECH_PIPER_CONFIG=/srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json
MAVERICK_SPEECH_PIPER_VOICE_ID=en_US-lessac-medium
MAVERICK_SPEECH_PIPER_LANGUAGE=en-us
MAVERICK_SPEECH_PIPER_WORKER=auto
MAVERICK_SPEECH_PIPER_WORKER_IDLE_SECONDS=21600
```

Optional digests can make cache invalidation explicit for large model/config files:

```bash
sha256sum /srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx
sha256sum /srv/maverick/models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json

MAVERICK_SPEECH_PIPER_MODEL_SHA256=<sha256 of en_US-lessac-medium.onnx>
MAVERICK_SPEECH_PIPER_CONFIG_SHA256=<sha256 of en_US-lessac-medium.onnx.json>
```

For multiple voices, persist `MAVERICK_SPEECH_PIPER_VOICES_JSON` as a JSON array whose entries include `voice_id`, `language`, `model`, optional `config`, and optional digest fields.

### Backend restart and verification

After changing packages, model files, `PATH`, or any `MAVERICK_SPEECH_*` value, restart the Maverick backend so mounted backend subprocesses inherit the new environment.

Verify the contract and CLI/MCP surfaces:

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id speech --app-root apps/speech --workspace default --json
maverick app speech cli inspect speech --json
maverick app speech cli run speech --action engine_health
maverick app speech cli run speech --action list_engines
maverick app speech cli run speech --action get_settings
maverick app speech cli run speech --action worker_status
maverick app speech cli run speech --action prewarm_worker
maverick app speech mcp inspect speech_transcribe_file --json
```

If the backend HTTP surface is available, verify capabilities through the backend consumer path as well. The payload should report `provider_available: true` for at least one configured synthesis or transcription engine.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id speech --app-root apps/speech --workspace default --json
python3 -m unittest discover -s apps/speech/tests -p 'test_*.py'
```

`speech` is an installation-level sealed app under `apps/speech`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
