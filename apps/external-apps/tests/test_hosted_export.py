"""Real Core dependency dispatch, real Website build, real consumer callback."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
import zipfile

from support import APP_ROOT, apply_args, context
from external_apps.deployment import load
from external_apps.files import atomic_write, encoded
from external_apps.service import Service
from public_server.serving import PublicRuntime
from core.apps.dependencies import resolve_app_dependencies, save_app_dependency_selection
from core.api.app_events import AppEventBus
from core.apps.installation import install_store_app
from core.apps.registration import register_app_source_from_contract
from core.apps.runtime_requests import apply_app_runtime_requests
from core.apps.surfaces import resolve_workspace_app_surface
from core.shared.entrypoints import run_json_entrypoint
from tests.support.app_hosting import AppHostingTestBase


class HostedExportTests(AppHostingTestBase):
    def test_real_provider_build_and_core_callback_under_alias(self):
        self.run_export_proof(spa=False)

    @unittest.skipUnless(os.environ.get("EXTERNAL_APPS_VITE_TEST") == "1", "opt-in real npm/Vite build")
    def test_real_vite_spa_through_core_callback_and_public_runtime(self):
        self.run_export_proof(spa=True)

    def run_export_proof(self, *, spa):
        with TemporaryDirectory() as directory:
            root = self.make_repo_root(directory)
            store = self.make_store()
            bindings = {}
            for app_id, local_id in (("external-apps", "publisher"), ("website-studio", "website-studio")):
                app_source = APP_ROOT.parent / app_id
                (root / "apps" / app_id).symlink_to(app_source, target_is_directory=True)
                source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_source))
                bindings[local_id] = install_store_app(store, source_id=source.source_id, workspace_id="proof", local_app_id=local_id, start_path=root)
            save_app_dependency_selection(store, workspace_id="proof", consumer_app_id="publisher", alias="static-exporter", provider_app_ids=["website-studio"], start_path=root)
            dependencies = resolve_app_dependencies(store, workspace_id="proof", consumer_app_id="publisher", start_path=root)

            def call(local_id, body):
                source, contract = resolve_workspace_app_surface(store, binding=bindings[local_id], start_path=root)
                response = run_json_entrypoint(source / contract.contract.entrypoints.backend, cwd=source, payload={
                    "surface": "backend", "workspace_id": "proof", "app_id": local_id,
                    "data_root": bindings[local_id].data_root, "workspace_root": str(root / "workspaces/proof"),
                    "user_id": "admin-proof", "workspace_role": "admin", "platform_role": "",
                    "app_dependencies": dependencies if local_id == "publisher" else {}, "body": body,
                })
                self.assertLess(response.get("status_code", 200), 400, response)
                return response

            body = {"action": "import_zip", "display_name": "Synthetic Vite SPA", "archive_base64": vite_archive(root / "vite-fixture")} if spa else {"action": "site_create", "display_name": "Synthetic hosted proof", "slug": "proof"}
            site = call("website-studio", body)["json"]["site"]
            build = call("website-studio", {"action": "build_validate", "site_id": site["id"]})["json"]["build"]
            self.assertEqual(build["status"], "passed", build)
            self.assertEqual(build["runtime_kind"], "node_build" if spa else "static_export")
            call("publisher", {"action": "deployment.configure", "installation_domain": "example.test"})
            result = call("publisher", {"action": "publish.plan", "source_entity_id": site["id"], "build_id": build["id"], "name": "Proof", "format": "spa_bundle" if spa else "static_bundle"})
            source, parsed = resolve_workspace_app_surface(store, binding=bindings["publisher"], start_path=root)
            state = SimpleNamespace(app_store=store, workspace_store=None, secret_store=None, observability_store=None, app_event_bus=AppEventBus())
            apply_app_runtime_requests(state, result=result, workspace_id="proof", app_id="publisher", source_root=source,
                                       backend_entrypoint=parsed.contract.entrypoints.backend, data_root=bindings["publisher"].data_root,
                                       parsed=parsed, start_path=root, actor_user_id="admin-proof")
            self.assertNotIn("content_base64", json.dumps(result))
            request_result = result["json"]["dependency_backend_request_results"][0]
            self.assertEqual(request_result["status"], "completed", {"request": request_result, "build": build})
            self.assertEqual(request_result["callback_status_code"], 200, request_result)
            plan = call("publisher", {"action": "get", "plan_id": result["json"]["plan"]["id"]})["json"]["plan"]
            self.assertEqual(plan["status"], "ready", plan)
            self.assertEqual(plan["provider_id"], "website-studio")
            self.assertTrue(plan["release"]["file_count"] > 0)
            self.assertFalse(list((Path(bindings["publisher"].data_root) / "public/bindings").glob("*.json")))
            original = call("website-studio", {"action": "read_file", "site_id": site["id"], "path": "index.html"})["json"]["file"]
            call("website-studio", {"action": "write_file", "site_id": site["id"], "path": "index.html", "content": "<h1>Changed after plan</h1>", "expected_hash": original["hash"]})
            data_root = Path(bindings["publisher"].data_root)
            config = load(data_root)
            projection = root / "projection.json"
            atomic_write(projection, encoded({"version": 1, "domain": config["domain"], "namespaces": [config["namespace"]], "expires": time.time() + 8}))
            runtime = PublicRuntime(domain=config["domain"], mounts={config["namespace"]: data_root / "public"}, projection=projection)
            def local_probe(host, release, entry_hash):
                status, headers, content = runtime.response("GET", host, "/")
                self.assertEqual(status, 200)
                self.assertEqual(headers["X-External-Release"], release["release_id"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry_hash)
                self.assertNotIn(b"Changed after plan", content)
                return {"status": "healthy", "checked_at": time.time()}
            call("publisher", {"action": "plan.approve", "plan_id": plan["id"], "plan_digest": plan["plan_digest"], "confirm": True})
            app = Service(data_root, context("proof", user_id="admin-proof", provider_id="website-studio"), probe=local_probe, preflight=lambda _host: None)
            self.assertEqual(app.handle(apply_args(plan))["status"], "published")
            for surface, entrypoint, name_key, name in (("cli", "cli/app_cli.py", "command_name", "external-apps"), ("mcp", "mcp/server.py", "tool_name", "external_apps")):
                response = run_json_entrypoint(APP_ROOT / entrypoint, cwd=APP_ROOT, payload={
                    "surface": surface, name_key: name, "workspace_id": "proof", "app_id": "publisher", "data_root": str(data_root),
                    "user_id": "admin-proof", "workspace_role": "admin", "arguments": {"action": "list"},
                })
                self.assertEqual(response["status_code"], 200, response)
                self.assertEqual(response["items"][0]["status"], "published")
            if spa:
                status, _, content = runtime.response("GET", plan["hostname"], "/dashboard/deep", {"accept": "text/html"})
                self.assertEqual(status, 200)
                self.assertIn(b"/_releases/", content)
                artifact = data_root / "public/artifacts" / plan["release"]["digest"] / "files"
                chunks = list(artifact.glob("assets/*.js"))
                self.assertGreaterEqual(len(chunks), 2)
                for path in chunks:
                    target = "/_releases/" + plan["release_id"] + "/" + path.relative_to(artifact).as_posix()
                    self.assertEqual(runtime.response("GET", plan["hostname"], target)[0], 200)


def vite_archive(root):
    """Real pinned Vite, not the fake-vite fixture used by older smoke tests."""
    root.mkdir()
    version = json.loads((APP_ROOT / "node_modules/vite/package.json").read_text())["version"]
    (root / "package.json").write_text(json.dumps({"name": "synthetic-external-spa", "version": "1.0.0", "type": "module", "scripts": {"build": "vite build"}, "devDependencies": {"vite": version}}))
    (root / "index.html").write_text('<!doctype html><html><head><title>SPA proof</title></head><body><div id="app"></div><script type="module" src="/main.js"></script></body></html>')
    (root / "main.js").write_text('import("./lazy.js").then(m => {document.querySelector("#app").textContent = m.default + location.pathname;});')
    (root / "lazy.js").write_text('export default "Synthetic SPA ";')
    subprocess.run(["npm", "install", "--package-lock-only", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, check=True, capture_output=True, timeout=60)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path in root.iterdir():
            if path.is_file():
                archive.write(path, path.name)
    return base64.b64encode(stream.getvalue()).decode()


if __name__ == "__main__":
    unittest.main()
