"""Apply the authorized compiled OpenDesign boundary and Maverick UI patches."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


class BoundaryPatchError(RuntimeError):
    """Fail-closed compiled boundary patch error."""


_TOKEN_DECLARATIONS = (
    b"    const apiToken = apiTokenFromEnv();\n"
    b"    const apiAuthDisabled = isApiAuthDisabled();\n"
)
_PATCHED_TOKEN_DECLARATIONS = _TOKEN_DECLARATIONS + (
    b"    const requireApiTokenOnLoopback = "
    b"['1', 'true', 'yes', 'on'].includes(String(process.env.OD_REQUIRE_API_TOKEN_ON_LOOPBACK ?? '')"
    b".trim().toLowerCase());\n"
)
_LOOPBACK_BYPASS = (
    b"            if (isLoopbackPeerAddress(req.socket?.remoteAddress))\n"
    b"                return next();\n"
)
_PATCHED_LOOPBACK_BYPASS = (
    b"            if (!requireApiTokenOnLoopback && isLoopbackPeerAddress(req.socket?.remoteAddress))\n"
    b"                return next();\n"
)

_UI_INJECTION = br'''<style id="maverick-opendesign-ui">
:root{--mav-bg:#070708;--mav-panel:rgba(12,12,14,.96);--mav-subtle:#111114;--mav-muted:#19191d;--mav-border:rgba(255,255,255,.1);--mav-text:#ececec;--mav-soft:rgba(236,236,236,.62);--mav-accent:#fff;color-scheme:dark}
:root[data-maverick-theme="light"]{--mav-bg:#f5f5f6;--mav-panel:rgba(255,255,255,.96);--mav-subtle:#eeeeef;--mav-muted:#e5e5e7;--mav-border:rgba(7,7,8,.11);--mav-text:#171719;--mav-soft:rgba(23,23,25,.62);--mav-accent:#111113;color-scheme:light}
:root,:root[data-theme="dark"],:root[data-theme="light"]{--bg:var(--mav-bg)!important;--bg-app:var(--mav-bg)!important;--bg-panel:var(--mav-panel)!important;--bg-subtle:var(--mav-subtle)!important;--bg-muted:var(--mav-muted)!important;--bg-elevated:var(--mav-panel)!important;--border:var(--mav-border)!important;--border-subtle:var(--mav-border)!important;--text:var(--mav-text)!important;--text-primary:var(--mav-text)!important;--text-secondary:var(--mav-soft)!important;--text-muted:var(--mav-soft)!important;--accent:var(--mav-accent)!important;--accent-hover:var(--mav-text)!important}
html,body,#__next{background:var(--mav-bg)!important;color:var(--mav-text)!important}
.split{grid-template-columns:minmax(0,1fr)!important}.split-chat-slot,.split-resize-handle,.split-edit-divider,[data-testid="side-chat-tab"]{display:none!important}.split-file-slot,.file-workspace{grid-column:1/-1!important;width:100%!important;max-width:none!important}
.home-view>.home-hero,.home-view>.recent-projects{display:none!important}.home-view{display:grid!important;place-items:center!important;min-height:100%!important}.home-view:before{content:"Select or create a project from the Maverick sidebar";display:block;max-width:28rem;padding:1.2rem 1.4rem;border:1px solid var(--mav-border);border-radius:1rem;background:var(--mav-panel);color:var(--mav-soft);font:600 14px/1.5 Inter,system-ui,sans-serif;text-align:center}
header,nav,[role="dialog"],[role="menu"],[data-radix-popper-content-wrapper]>div{border-color:var(--mav-border)!important;background-color:var(--mav-panel)!important;color:var(--mav-text)!important}input,textarea,button,select{border-color:var(--mav-border)!important}::-webkit-scrollbar-thumb{background:rgba(255,255,255,.18)!important;border-radius:999px}
</style><script id="maverick-opendesign-bridge">(()=>{const root=document.documentElement;let lastProject="";const valid=id=>/^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/.test(id||"");const project=()=>{const match=/^\/projects\/([^/?#]+)/.exec(location.pathname);if(!match)return"";try{return decodeURIComponent(match[1])}catch{return""}};const notify=()=>{const id=project();if(id===lastProject)return;lastProject=id;if(valid(id))parent.postMessage({type:"maverick.opendesign.navigation-changed",version:1,od_project_id:id},"*")};const prune=()=>document.querySelectorAll('.split-chat-slot,.split-resize-handle,.split-edit-divider,[data-testid="side-chat-tab"],.home-view>.home-hero,.home-view>.recent-projects').forEach(element=>element.remove());const sync=()=>{prune();notify()};const applyTheme=theme=>{if(theme!=="dark"&&theme!=="light")return;root.dataset.maverickTheme=theme;root.dataset.theme=theme;root.style.colorScheme=theme};const navigate=id=>{if(!valid(id))return;const next=`/projects/${encodeURIComponent(id)}`;if(location.pathname!==next){location.assign(next);return}sync()};addEventListener("message",event=>{if(event.source!==parent||!event.data||typeof event.data!=="object"||event.data.version!==1)return;if(event.data.type==="maverick.opendesign.navigate"&&event.data.od_project_id)navigate(event.data.od_project_id);if(event.data.type==="maverick.opendesign.theme")applyTheme(event.data.theme)});for(const method of ["pushState","replaceState"]){const original=history[method];history[method]=function(...args){const result=original.apply(this,args);queueMicrotask(sync);return result}}addEventListener("popstate",sync);new MutationObserver(sync).observe(document.documentElement,{childList:true,subtree:true});const ready=()=>{sync();parent.postMessage({type:"maverick.opendesign.ready",version:1},"*")};document.readyState==="loading"?addEventListener("DOMContentLoaded",ready,{once:true}):ready()})();</script>'''


def apply_boundary_patch(stage: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    policy = manifest["boundary_patch"]
    target = stage.joinpath(*policy["path"].split("/"))
    try:
        target.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise BoundaryPatchError("OpenDesign boundary patch target escapes the derived stage") from exc
    if target.is_symlink() or not target.is_file():
        raise BoundaryPatchError("OpenDesign boundary patch target must be a real file")
    source = target.read_bytes()
    pre_sha256 = hashlib.sha256(source).hexdigest()
    if pre_sha256 != policy["pre_sha256"]:
        raise BoundaryPatchError("OpenDesign boundary patch preimage does not match the authorized release")
    if source.count(_TOKEN_DECLARATIONS) != 1 or source.count(_LOOPBACK_BYPASS) != 1:
        raise BoundaryPatchError("OpenDesign boundary patch semantic preimage is missing or ambiguous")
    patched = source.replace(_TOKEN_DECLARATIONS, _PATCHED_TOKEN_DECLARATIONS, 1)
    patched = patched.replace(_LOOPBACK_BYPASS, _PATCHED_LOOPBACK_BYPASS, 1)
    if patched == source or patched.count(_PATCHED_LOOPBACK_BYPASS) != 1:
        raise BoundaryPatchError("OpenDesign boundary patch did not produce the authorized transformation")
    post_sha256 = hashlib.sha256(patched).hexdigest()
    expected_post = policy.get("post_sha256")
    if expected_post is not None and post_sha256 != expected_post:
        raise BoundaryPatchError("OpenDesign boundary patch postimage does not match the pin")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, target.stat().st_mode & 0o777)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(patched)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    evidence: dict[str, Any] = {
        "path": policy["path"],
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "required_environment": policy["required_environment"],
    }
    evidence["ui_patch"] = _apply_ui_patch(stage, manifest)
    return evidence


def _apply_ui_patch(stage: Path, manifest: dict[str, Any]) -> dict[str, str]:
    policy = manifest["ui_patch"]
    target = stage.joinpath(*policy["path"].split("/"))
    try:
        target.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise BoundaryPatchError("OpenDesign UI patch target escapes the derived stage") from exc
    if target.is_symlink() or not target.is_file():
        raise BoundaryPatchError("OpenDesign UI patch target must be a real file")
    source = target.read_bytes()
    pre_sha256 = hashlib.sha256(source).hexdigest()
    if pre_sha256 != policy["pre_sha256"]:
        raise BoundaryPatchError("OpenDesign UI patch preimage does not match the authorized release")
    marker = b"</head>"
    if source.count(marker) != 1 or _UI_INJECTION in source:
        raise BoundaryPatchError("OpenDesign UI patch semantic preimage is missing or ambiguous")
    patched = source.replace(marker, _UI_INJECTION + marker, 1)
    post_sha256 = hashlib.sha256(patched).hexdigest()
    if post_sha256 != policy["post_sha256"]:
        raise BoundaryPatchError("OpenDesign UI patch postimage does not match the pin")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, target.stat().st_mode & 0o777)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(patched)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": policy["path"], "pre_sha256": pre_sha256, "post_sha256": post_sha256}


__all__ = ["BoundaryPatchError", "apply_boundary_patch"]
