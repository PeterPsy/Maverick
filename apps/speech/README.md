# Speech

Backend-only speech provider app for workspace text-to-speech and future transcription surfaces.

## Contract Notes

- The app declares no frontend, widgets, CLI, MCP, skills, references, or persisted view surfaces. It is a provider app selected through generic app links.
- `speech` provides `speech.synthesis` v1 through its app backend. `speech.transcription` v1 is reserved as the future STT boundary in the backend capability payload, but it is intentionally not declared in `provides` until transcription is implemented.
- The app stores synthesis job metadata under `data/speech/jobs.json`. Chat and other consumers never read or write this data directly.
- Synthesis uses an explicit local TTS engine when one is available on the backend host (`espeak` or `espeak-ng`). If no engine is available, `capabilities` reports `provider_available: false` and `synthesize` returns `provider_unavailable`.
- Synthesis responses return bounded inline WAV audio for immediate playback and are retained as ephemeral output. The app does not write generated audio artifacts under workspace storage; only capped job metadata is persisted.
- The app does not request network or secret permissions. Future cloud provider support must declare outbound targets and logical secret names in the contract instead of storing raw values in `data/speech`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id speech --app-root apps/speech --workspace default --json
python3 -m unittest discover -s apps/speech/tests -p 'test_*.py'
```

`speech` is an installation-level sealed app under `apps/speech`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
