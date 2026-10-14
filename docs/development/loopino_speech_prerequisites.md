# Local Speech installation prerequisites

The clean Loopino installation uses real local engines; source fixture engines
are never production readiness evidence. Install `.[speech]` into the protected
installation `.venv`. `faster-whisper` 1.2.1 still calls PyAV with
`metadata_errors`, which PyAV 19 removed. The Speech extra therefore declares
`av>=11,<19`. The prepared Python 3.12 environment resolves PyAV 18.1.0 and
CTranslate2 4.8.3. Do not patch installed third-party code.

The destination uses installation-owned extracted Ubuntu espeak-ng 1.51 and
FFmpeg 6.1.1 libraries and launchers under `.toolchains/media` and
`.toolchains/bin`. Its pinned public faster-whisper-small model is under
`.toolchains/models/faster-whisper-small`; `.loopino/speech.env` selects that
local path with CPU/int8 inference. Keep downloads, model caches and temporary
files under the installation and keep executable/model material root-controlled.
Exact upstream revision, package versions and file hashes are operational
receipts under `operations/phase1/deployment`.

Deployment verification generated a fixed local espeak WAV and transcribed it
as the actual service UID using the real local model without credentials. The
first inference with PyAV 19 failed with `TypeError: open() got an unexpected
keyword argument 'metadata_errors'`; the bounded retry with PyAV 18.1.0 succeeded.
This verifies local inference, not transcription quality or microphone/device
acceptance.

For local-only mounted backend requests use the documented generic secret
selector `_app_secret_request: {"logical_names": [], "required": true}`.
Omitting it requests the app's declared default credentials. An explicit missing
remote credential must still fail with `app_secret_unavailable`; local readiness
must not imply a configured cloud provider.
