# Speech

Backend-only speech provider app for workspace text-to-speech and speech-to-text transcription surfaces.

## Contract Notes

- The app declares no frontend, widgets, skills, reference entities, or persisted view surfaces. It is a provider app selected through generic app links.
- `speech` provides `speech.synthesis` v1 through its app backend and `speech.transcription` v1 through backend, CLI, and MCP surfaces. Both interfaces are optional at runtime: capability payloads report whether a usable local engine is available in the current installation.
- The app stores capped synthesis and transcription job metadata under `data/speech/jobs.json` and workspace engine settings under `data/speech/settings.json`. Chat and other consumers never read or write this data directly.
- Synthesis uses an explicit local TTS engine when one is available on the backend host (`espeak` or `espeak-ng`). If no engine is available, `capabilities` reports `provider_available: false` and `synthesize` returns `provider_unavailable`.
- Transcription supports bounded inline audio blobs with `transcribe_audio` over the backend and workspace Storage audio files with `transcribe_file` over backend, CLI, and MCP. Live microphone streaming is intentionally not exposed through CLI/MCP.
- Workspace settings may select only the preferred synthesis/transcription engine. Host paths, model choices, device choices, and compute settings are operator configuration, not workspace data.
- The local MVP prefers `faster-whisper` when the optional speech dependency and model are installed locally. `faster-whisper` runs with `local_files_only` and uses `MAVERICK_SPEECH_FASTER_WHISPER_MODEL`, `MAVERICK_SPEECH_FASTER_WHISPER_DEVICE`, and `MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE` as operator configuration. `whisper.cpp` can be enabled through `MAVERICK_SPEECH_WHISPER_CPP_BINARY` and `MAVERICK_SPEECH_WHISPER_CPP_MODEL`. Health and settings payloads report only redacted configured/available booleans, not host paths.
- Synthesis responses return bounded inline WAV audio as `audio_base64` plus `content_type` and are retained as ephemeral output. The app does not write generated audio artifacts under workspace storage; only capped job metadata is persisted.
- Transcription responses return text, segments, language metadata, engine metadata, and `retention: metadata_only`. Raw microphone audio is not persisted by the app.
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

`transcribe_audio` accepts small base64 audio payloads such as browser `audio/webm` recordings. `transcribe_file` accepts normalized workspace-relative paths under `storage/uploaded/` or `storage/generated/`; absolute paths and traversal are rejected.

Agents should use:

```bash
maverick app speech cli run speech --action transcribe_file --workspace-relative-path storage/uploaded/example.wav
maverick app speech mcp call speech_transcribe_file --workspace-relative-path storage/uploaded/example.wav
```

The exact wrapper flag spelling is discoverable through `maverick app speech cli inspect speech --json` and `maverick app speech mcp inspect speech_transcribe_file --json`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id speech --app-root apps/speech --workspace default --json
python3 -m unittest discover -s apps/speech/tests -p 'test_*.py'
```

Local faster-whisper support is optional:

```bash
python3 -m pip install '.[speech]'
```

`speech` is an installation-level sealed app under `apps/speech`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
