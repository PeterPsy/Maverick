"""Apply the authorized compiled OpenDesign API boundary patch."""

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
_STATIC_DIR_DECLARATION = b"const STATIC_DIR = path.join(PROJECT_ROOT, 'apps', 'web', 'out');\n"
_PATCHED_STATIC_DIR_DECLARATION = b"""function resolveRequiredStaticDir() {
    const configuredStaticDir = process.env.OD_STATIC_DIR;
    const configuredRegistryRoot = process.env.OD_STATIC_REGISTRY_ROOT;
    if (!configuredStaticDir || configuredStaticDir.trim() !== configuredStaticDir ||
        !configuredRegistryRoot || configuredRegistryRoot.trim() !== configuredRegistryRoot) {
        throw new Error('OD_STATIC_DIR and OD_STATIC_REGISTRY_ROOT are required.');
    }
    if (!path.isAbsolute(configuredStaticDir) || !path.isAbsolute(configuredRegistryRoot)) {
        throw new Error('OpenDesign static overlay paths must be absolute.');
    }
    const staticMetadata = fs.lstatSync(configuredStaticDir);
    const registryMetadata = fs.lstatSync(configuredRegistryRoot);
    if (staticMetadata.isSymbolicLink() || !staticMetadata.isDirectory() ||
        registryMetadata.isSymbolicLink() || !registryMetadata.isDirectory()) {
        throw new Error('OpenDesign static overlay paths must be real directories.');
    }
    const staticDir = fs.realpathSync(configuredStaticDir);
    const registryRoot = fs.realpathSync(configuredRegistryRoot);
    const relative = path.relative(registryRoot, staticDir);
    if (!relative || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
        throw new Error('OD_STATIC_DIR must stay inside OD_STATIC_REGISTRY_ROOT.');
    }
    return staticDir;
}
function readMaverickReadyMarker() {
    const markerPath = process.env.OD_MAVERICK_READY_MARKER;
    if (!markerPath || !path.isAbsolute(markerPath))
        return null;
    try {
        const metadata = fs.lstatSync(markerPath);
        if (metadata.isSymbolicLink() || !metadata.isFile())
            return null;
        const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
        const expected = {
            schema_version: '1',
            startup_nonce: process.env.OD_MAVERICK_STARTUP_NONCE,
            runtime_artifact_sha256: process.env.OD_RUNTIME_ARTIFACT_SHA256,
            web_overlay_sha256: process.env.OD_WEB_OVERLAY_SHA256,
            data_generation: process.env.OD_DATA_GENERATION,
            activation_id: process.env.OD_ACTIVATION_ID ?? '',
        };
        const keys = Object.keys(expected);
        if (Object.keys(marker).length !== keys.length || keys.some((key) => marker[key] !== expected[key]))
            return null;
        return marker;
    }
    catch {
        return null;
    }
}
"""
_START_SERVER_HOST = b"    host = normalizeDaemonBindHost(host);\n"
_PATCHED_START_SERVER_HOST = _START_SERVER_HOST + b"    const STATIC_DIR = resolveRequiredStaticDir();\n"
_STATIC_MOUNT = (
    b"    if (fs.existsSync(STATIC_DIR)) {\n"
    b"        app.use(express.static(STATIC_DIR));\n"
    b"    }\n"
)
_PATCHED_STATIC_MOUNT = b"    app.use(express.static(STATIC_DIR));\n"
_READY_ROUTE = b"""    app.get('/api/ready', async (_req, res) => {
        const versionInfo = await readCurrentAppVersionInfo();
        const ready = !daemonShuttingDown;
        res.status(ready ? 200 : 503).json({
            ok: ready,
            ready,
            version: versionInfo.version,
        });
    });
"""
_PATCHED_READY_ROUTE = _READY_ROUTE + b"""    app.get('/api/maverick-ready', (_req, res) => {
        const ready = !daemonShuttingDown && readMaverickReadyMarker() !== null;
        res.setHeader('Cache-Control', 'no-store');
        res.status(ready ? 200 : 503).json({ ok: ready, ready });
    });
"""

_BUNDLED_CATALOG_DECLARATION = b"    let bundledMarketplaceEntries = [];\n"
_PATCHED_BUNDLED_CATALOG_DECLARATION = _BUNDLED_CATALOG_DECLARATION + b"""    let bundledCatalogTimer = null;
    let bundledCatalogPromise = null;
"""
_BUNDLED_CATALOG_START = b"""    try {
        const result = await registerBundledPlugins({
"""
_PATCHED_BUNDLED_CATALOG_START = b"""    const initializeBundledCatalog = async () => {
        try {
        const result = await registerBundledPlugins({
"""
_BUNDLED_CATALOG_ASSIGNMENT_START = (
    b"        bundledMarketplaceEntries = result.registered.map((plugin) => ({\n"
)
_PATCHED_BUNDLED_CATALOG_ASSIGNMENT_START = (
    b"        bundledMarketplaceEntries.splice(0, bundledMarketplaceEntries.length, "
    b"...result.registered.map((plugin) => ({\n"
)
_BUNDLED_CATALOG_ASSIGNMENT_END = b"""            capabilitiesSummary: Array.isArray(plugin.manifest.od?.capabilities)
                ? plugin.manifest.od.capabilities
                : undefined,
        }));
        if (result.registered.length > 0) {
"""
_PATCHED_BUNDLED_CATALOG_ASSIGNMENT_END = b"""            capabilitiesSummary: Array.isArray(plugin.manifest.od?.capabilities)
                ? plugin.manifest.od.capabilities
                : undefined,
        })));
        if (result.registered.length > 0) {
"""
_BUNDLED_CATALOG_END = """    catch (err) {
        console.warn(`[plugins] registry seed failed: ${(err)?.message ?? err}`);
    }
    // Plan §3.A5 / spec §16 Phase 5 / PB2: periodic snapshot GC. Disabled
""".encode("utf-8")
_PATCHED_BUNDLED_CATALOG_END = """    catch (err) {
        console.warn(`[plugins] registry seed failed: ${(err)?.message ?? err}`);
    }
    };
    const deferBundledCatalog = ['1', 'true', 'yes', 'on'].includes(String(process.env.OD_MAVERICK_DEFER_PLUGIN_CATALOG ?? '').trim().toLowerCase());
    if (!deferBundledCatalog) {
        await initializeBundledCatalog();
    }
    // Plan §3.A5 / spec §16 Phase 5 / PB2: periodic snapshot GC. Disabled
""".encode("utf-8")
_DAEMON_BACKGROUND_CLEANUP = b"""        const cleanupDaemonBackgroundWork = () => {
            composioConnectorProvider.stopCatalogRefreshLoop();
"""
_PATCHED_DAEMON_BACKGROUND_CLEANUP = b"""        const cleanupDaemonBackgroundWork = () => {
            if (bundledCatalogTimer) {
                clearTimeout(bundledCatalogTimer);
                bundledCatalogTimer = null;
            }
            composioConnectorProvider.stopCatalogRefreshLoop();
"""
_DAEMON_SHUTDOWN_START = b"""            daemonShutdownStarted = true;
            daemonShuttingDown = true;
            await design.runs.shutdownActive({ graceMs: resolveChatRunShutdownGraceMs() });
"""
_PATCHED_DAEMON_SHUTDOWN_START = b"""            daemonShutdownStarted = true;
            daemonShuttingDown = true;
            if (bundledCatalogTimer) {
                clearTimeout(bundledCatalogTimer);
                bundledCatalogTimer = null;
            }
            if (bundledCatalogPromise)
                await bundledCatalogPromise;
            await design.runs.shutdownActive({ graceMs: resolveChatRunShutdownGraceMs() });
"""
_DAEMON_LISTEN_COMMIT = b"""                daemonUrl = url;
                resolve(returnServer ? {
"""
_PATCHED_DAEMON_LISTEN_COMMIT = b"""                daemonUrl = url;
                if (deferBundledCatalog && !daemonShuttingDown && !bundledCatalogTimer && !bundledCatalogPromise) {
                    bundledCatalogTimer = setTimeout(() => {
                        bundledCatalogTimer = null;
                        if (!daemonShuttingDown)
                            bundledCatalogPromise = initializeBundledCatalog();
                    }, 5_000);
                    bundledCatalogTimer.unref?.();
                }
                resolve(returnServer ? {
"""

_BUNDLED_WARNINGS_DECLARATION = b"    const warnings = [];\n"
_PATCHED_BUNDLED_WARNINGS_DECLARATION = (
    _BUNDLED_WARNINGS_DECLARATION + b"    const candidates = [];\n"
)
_DIRECT_BUNDLED_REGISTRATION = (
    b"            await registerOne({ folder: tierAbs, folderId: tier.name, out, warnings, "
    b"seenFolderIds, input });\n"
)
_PATCHED_DIRECT_BUNDLED_REGISTRATION = (
    b"            candidates.push({ folder: tierAbs, folderId: tier.name });\n"
)
_NESTED_BUNDLED_REGISTRATION = (
    b"            await registerOne({ folder, folderId: entry.name, out, warnings, "
    b"seenFolderIds, input });\n"
)
_PATCHED_NESTED_BUNDLED_REGISTRATION = (
    b"            candidates.push({ folder, folderId: entry.name });\n"
)
_BUNDLED_REGISTRATION_COMMIT = b"""    const pruned = pruneRemovedBundledPlugins(input.db, seenFolderIds);
    return { registered: out, pruned, warnings };
}
// Bundled rows"""
_PATCHED_BUNDLED_REGISTRATION_COMMIT = b"""    candidates.sort((left, right) => left.folderId.localeCompare(right.folderId));
    await forEachConcurrent(candidates, 8, async ({ folder, folderId }) => {
        await registerOne({ folder, folderId, out, warnings, seenFolderIds, input });
    });
    out.sort((left, right) => left.id.localeCompare(right.id));
    warnings.sort();
    const pruned = pruneRemovedBundledPlugins(input.db, seenFolderIds);
    return { registered: out, pruned, warnings };
}
async function forEachConcurrent(values, concurrency, worker) {
    let cursor = 0;
    const workers = Array.from({ length: Math.min(concurrency, values.length) }, async () => {
        while (cursor < values.length) {
            const index = cursor;
            cursor += 1;
            await worker(values[index]);
        }
    });
    await Promise.all(workers);
}
// Bundled rows"""

_BUNDLED_REGISTRY_IMPORT = (
    b"import { deleteInstalledPlugin, getInstalledPlugin, resolvePluginFolder, "
    b"upsertInstalledPlugin, } from './registry.js';\n"
)
_PATCHED_BUNDLED_REGISTRY_IMPORT = (
    b"import { deleteInstalledPlugin, getInstalledPlugin, listInstalledPlugins, "
    b"resolvePluginFolder, upsertInstalledPlugin, } from './registry.js';\n"
)
_BUNDLED_REUSE_SITE = b"""    candidates.sort((left, right) => left.folderId.localeCompare(right.folderId));
    await forEachConcurrent(candidates, 8, async ({ folder, folderId }) => {"""
_PATCHED_BUNDLED_REUSE_SITE = b"""    candidates.sort((left, right) => left.folderId.localeCompare(right.folderId));
    const reused = reuseProtectedRuntimeRecords(input, candidates);
    if (reused !== null) {
        for (const record of reused) {
            seenFolderIds.add(record.id);
            out.push(record);
        }
        const pruned = pruneRemovedBundledPlugins(input.db, seenFolderIds);
        return { registered: out, pruned, warnings };
    }
    await forEachConcurrent(candidates, 8, async ({ folder, folderId }) => {"""
_BUNDLED_CONCURRENCY_HELPER = b"""}
async function forEachConcurrent(values, concurrency, worker) {"""
_PATCHED_BUNDLED_CONCURRENCY_HELPER = b"""}
function reuseProtectedRuntimeRecords(input, candidates) {
    const runtimeDigest = protectedRuntimeIdentity();
    if (runtimeDigest === null)
        return null;
    const records = [];
    const seen = new Set();
    const installed = new Map(listInstalledPlugins(input.db)
        .filter((record) => record.sourceKind === 'bundled')
        .map((record) => [record.fsPath, record]));
    const digests = new Map(input.db
        .prepare(`SELECT id, bundled_content_digest FROM installed_plugins WHERE source_kind = 'bundled'`)
        .all()
        .map((row) => [row.id, row.bundled_content_digest]));
    for (const { folder, folderId: rawFolderId } of candidates) {
        const folderId = rawFolderId.toLowerCase();
        if (!SAFE_BASENAME.test(folderId))
            return null;
        const record = installed.get(folder) ?? null;
        const expectedDigest = protectedRuntimeBundledDigest(folderId, runtimeDigest);
        if (record === null
            || seen.has(record.id)
            || record.sourceKind !== 'bundled'
            || record.source !== folder
            || record.fsPath !== folder
            || digests.get(record.id) !== expectedDigest
            || !marketplaceProvenanceMatches(record, input.marketplaceProvenance)) {
            return null;
        }
        seen.add(record.id);
        records.push(record);
    }
    return records;
}
function marketplaceProvenanceMatches(record, provenance) {
    if (!provenance) {
        return record.sourceMarketplaceId === undefined
            && record.sourceMarketplaceEntryName === undefined
            && record.sourceMarketplaceEntryVersion === undefined
            && record.marketplaceTrust === undefined
            && record.resolvedSource === undefined;
    }
    return record.sourceMarketplaceId === provenance.sourceMarketplaceId
        && record.sourceMarketplaceEntryName === `${provenance.entryNamePrefix}/${record.id}`
        && record.sourceMarketplaceEntryVersion === record.version
        && record.marketplaceTrust === provenance.marketplaceTrust
        && record.resolvedSource === record.source;
}
async function forEachConcurrent(values, concurrency, worker) {"""
_BUNDLED_DIGEST_HELPER_SITE = b"""    return hash.digest('hex');
}
function getBundledContentDigest(db, id) {"""
_PATCHED_BUNDLED_DIGEST_HELPER_SITE = b"""    return hash.digest('hex');
}
function protectedRuntimeIdentity() {
    const runtimeDigest = process.env.OD_RUNTIME_ARTIFACT_SHA256;
    return runtimeDigest && /^[0-9a-f]{64}$/.test(runtimeDigest) ? runtimeDigest : null;
}
function protectedRuntimeBundledDigest(folderId, runtimeDigest = protectedRuntimeIdentity()) {
    if (runtimeDigest === null)
        return null;
    return createHash('sha256')
        .update('maverick-protected-runtime-v1\\0')
        .update(runtimeDigest)
        .update('\\0')
        .update(folderId)
        .digest('hex');
}
function getBundledContentDigest(db, id) {"""
_BUNDLED_CONTENT_DIGEST = b"    const contentDigest = await computeBundledContentDigest(args.folder);\n"
_PATCHED_BUNDLED_CONTENT_DIGEST = b"""    const contentDigest = protectedRuntimeBundledDigest(folderId)
        ?? await computeBundledContentDigest(args.folder);
"""

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
    if any(
        source.count(fragment) != 1
        for fragment in (
            _TOKEN_DECLARATIONS,
            _LOOPBACK_BYPASS,
            _STATIC_DIR_DECLARATION,
            _START_SERVER_HOST,
            _STATIC_MOUNT,
            _READY_ROUTE,
            _BUNDLED_CATALOG_DECLARATION,
            _BUNDLED_CATALOG_START,
            _BUNDLED_CATALOG_ASSIGNMENT_START,
            _BUNDLED_CATALOG_ASSIGNMENT_END,
            _BUNDLED_CATALOG_END,
            _DAEMON_BACKGROUND_CLEANUP,
            _DAEMON_SHUTDOWN_START,
            _DAEMON_LISTEN_COMMIT,
        )
    ):
        raise BoundaryPatchError("OpenDesign boundary patch semantic preimage is missing or ambiguous")
    patched = source.replace(_TOKEN_DECLARATIONS, _PATCHED_TOKEN_DECLARATIONS, 1)
    patched = patched.replace(_LOOPBACK_BYPASS, _PATCHED_LOOPBACK_BYPASS, 1)
    patched = patched.replace(_STATIC_DIR_DECLARATION, _PATCHED_STATIC_DIR_DECLARATION, 1)
    patched = patched.replace(_START_SERVER_HOST, _PATCHED_START_SERVER_HOST, 1)
    patched = patched.replace(_STATIC_MOUNT, _PATCHED_STATIC_MOUNT, 1)
    patched = patched.replace(_READY_ROUTE, _PATCHED_READY_ROUTE, 1)
    patched = patched.replace(
        _BUNDLED_CATALOG_DECLARATION,
        _PATCHED_BUNDLED_CATALOG_DECLARATION,
        1,
    )
    patched = patched.replace(_BUNDLED_CATALOG_START, _PATCHED_BUNDLED_CATALOG_START, 1)
    patched = patched.replace(
        _BUNDLED_CATALOG_ASSIGNMENT_START,
        _PATCHED_BUNDLED_CATALOG_ASSIGNMENT_START,
        1,
    )
    patched = patched.replace(
        _BUNDLED_CATALOG_ASSIGNMENT_END,
        _PATCHED_BUNDLED_CATALOG_ASSIGNMENT_END,
        1,
    )
    patched = patched.replace(_BUNDLED_CATALOG_END, _PATCHED_BUNDLED_CATALOG_END, 1)
    patched = patched.replace(
        _DAEMON_BACKGROUND_CLEANUP,
        _PATCHED_DAEMON_BACKGROUND_CLEANUP,
        1,
    )
    patched = patched.replace(_DAEMON_SHUTDOWN_START, _PATCHED_DAEMON_SHUTDOWN_START, 1)
    patched = patched.replace(_DAEMON_LISTEN_COMMIT, _PATCHED_DAEMON_LISTEN_COMMIT, 1)
    if (
        patched == source
        or patched.count(_PATCHED_LOOPBACK_BYPASS) != 1
        or patched.count(b"/api/maverick-ready") != 1
        or patched.count(b"OD_MAVERICK_DEFER_PLUGIN_CATALOG") != 1
        or patched.count(b"initializeBundledCatalog") != 3
    ):
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
    return evidence


def apply_startup_patch(stage: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Apply the exact bounded-concurrency transformation to the compiled daemon."""

    policy = manifest["startup_patch"]
    target = stage.joinpath(*policy["path"].split("/"))
    try:
        target.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise BoundaryPatchError("OpenDesign startup patch target escapes the derived stage") from exc
    if target.is_symlink() or not target.is_file():
        raise BoundaryPatchError("OpenDesign startup patch target must be a real file")
    source = target.read_bytes()
    pre_sha256 = hashlib.sha256(source).hexdigest()
    if pre_sha256 != policy["pre_sha256"]:
        raise BoundaryPatchError("OpenDesign startup patch preimage does not match the authorized release")
    structural_replacements = (
        (_BUNDLED_WARNINGS_DECLARATION, _PATCHED_BUNDLED_WARNINGS_DECLARATION),
        (_DIRECT_BUNDLED_REGISTRATION, _PATCHED_DIRECT_BUNDLED_REGISTRATION),
        (_NESTED_BUNDLED_REGISTRATION, _PATCHED_NESTED_BUNDLED_REGISTRATION),
        (_BUNDLED_REGISTRATION_COMMIT, _PATCHED_BUNDLED_REGISTRATION_COMMIT),
    )
    if any(source.count(fragment) != 1 for fragment, _replacement in structural_replacements):
        raise BoundaryPatchError("OpenDesign startup patch semantic preimage is missing or ambiguous")
    patched = source
    for fragment, replacement in structural_replacements:
        patched = patched.replace(fragment, replacement, 1)
    protected_replacements = (
        (_BUNDLED_REGISTRY_IMPORT, _PATCHED_BUNDLED_REGISTRY_IMPORT),
        (_BUNDLED_REUSE_SITE, _PATCHED_BUNDLED_REUSE_SITE),
        (_BUNDLED_CONCURRENCY_HELPER, _PATCHED_BUNDLED_CONCURRENCY_HELPER),
        (_BUNDLED_DIGEST_HELPER_SITE, _PATCHED_BUNDLED_DIGEST_HELPER_SITE),
        (_BUNDLED_CONTENT_DIGEST, _PATCHED_BUNDLED_CONTENT_DIGEST),
    )
    if any(patched.count(fragment) != 1 for fragment, _replacement in protected_replacements):
        raise BoundaryPatchError("OpenDesign startup patch semantic preimage is missing or ambiguous")
    for fragment, replacement in protected_replacements:
        patched = patched.replace(fragment, replacement, 1)
    if (
        patched == source
        or patched.count(b"forEachConcurrent(candidates, 8") != 1
        or patched.count(b"maverick-protected-runtime-v1") != 1
    ):
        raise BoundaryPatchError("OpenDesign startup patch did not produce the authorized transformation")
    post_sha256 = hashlib.sha256(patched).hexdigest()
    expected_post = policy.get("post_sha256")
    if expected_post is not None and post_sha256 != expected_post:
        raise BoundaryPatchError("OpenDesign startup patch postimage does not match the pin")
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
    return {
        "path": policy["path"],
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "max_concurrency": policy["max_concurrency"],
    }


__all__ = ["BoundaryPatchError", "apply_boundary_patch", "apply_startup_patch"]
