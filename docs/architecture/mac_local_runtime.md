# Retired macOS direct-provider runtime

Status (2026-09-14): **removed**.

The former Chat `Su questo Mac` mode ran a separate Codex app-server on the Mac,
kept a local transcript and copied managed OpenAI credentials into a private
native runtime home. It existed only as the A/B control for Device Use through
Maverick.

The final paired v40 test measured 4m44s direct and 4m48s through Maverick
(+4s / +1.4%) with equivalent functionality and no replay. That acceptance gate
passed, so the duplicate provider/runtime path was deleted.

Removed surfaces include:

- Chat's `Sul server` / `Su questo Mac` switch and `LocalMacChat`;
- base-shell's local-runtime broker and WebKit `maverickLocalRuntime` handler;
- native `LocalRuntime`, `CodexProcess`, runtime home and local transcript;
- bundled Codex download/runtime assets and its smoke scripts;
- OpenAI credential provisioning, encrypted delivery and Keychain copy;
- Core `core/local_runtime`, `scripts/provision_mac_codex.py` and their tests;
- direct image comparison/delivery and native setup/diagnostic chrome.

There is no migration adapter or compatibility shim. Historical Keychain items
or Application Support folders are not read by the current app; removing them
is explicit operator cleanup rather than launch behavior.

The only current design is
[`macos_device_use_bridge.md`](macos_device_use_bridge.md): Maverick Chat/Core
own the Codex turn, credentials, transcript and image injection, while the Mac
app is the signed native executor. Implement all future Mac control features
against that architecture. Do not reintroduce a local provider runtime.
