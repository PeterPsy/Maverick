"""Dedicated bounded Unix HTTP listener. No Core routing or credentials."""
import argparse
from http.server import BaseHTTPRequestHandler
import json
import mimetypes
from pathlib import Path
import signal
from socketserver import ThreadingMixIn, UnixStreamServer
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from errors import CrmError, error_payload
from external_hosting import settings
from public_server.policy import execute

MAX_BODY = 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "form-action 'none'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'")


class Runtime:
    def __init__(self, root, assets, projection, hostname, access):
        self.root, self.assets, self.projection = Path(root), Path(assets), Path(projection)
        self.hostname, self.access = hostname, access

    def authorized(self):
        try:
            state = json.loads(self.projection.read_text())
            current = settings(self.root)
            return (current['enabled'] and current['access'] == self.access
                    and state['hostname'] == self.hostname and state['revision'] == current['revision']
                    and time.time() < state['expires'] <= time.time() + 10)
        except (OSError, ValueError, KeyError, TypeError, CrmError):
            return False

    def response(self, method, host, target, headers, body=b''):
        if host != self.hostname or not self.authorized():
            return 404, 'application/json', b'{"error":"surface_unavailable"}'
        parsed = urlsplit(target)
        path = parsed.path
        if (parsed.scheme or parsed.netloc or parsed.fragment or not path.startswith('/')
                or '%' in path or '\\' in path or '//' in path or any(part in {'.', '..'} for part in path.split('/'))):
            return 400, 'application/json', b'{"error":"invalid_path"}'
        if path == '/api/apps/crm/backend' and method == 'POST':
            # The anonymous API is public, but browsers cannot drive writes via
            # forms, opaque origins or a same-site sibling. No credential-based CORS.
            if headers.get('origin') != 'https://' + self.hostname or headers.get('content-type') != 'application/json':
                return 403, 'application/json', b'{"error":"same_origin_json_required"}'
            try:
                code, value = execute(self.root, json.loads(body), access=self.access)
            except CrmError as error:
                code, value = error.status_code, error_payload(error)
            except (ValueError, TypeError, RecursionError):
                code, value = 400, {'error': 'invalid_request'}
            except Exception:
                code, value = 500, {'error': 'crm_request_failed', 'message': 'CRM request failed.'}
            encoded = json.dumps(value, ensure_ascii=True).encode()
            if len(encoded) > MAX_RESPONSE:
                return 413, 'application/json', b'{"error":"response_too_large"}'
            return code, 'application/json', encoded
        if method not in {'GET', 'HEAD'}:
            return 405, 'application/json', b'{"error":"method_not_allowed"}'
        if path in {'/', '/apps/crm/', '/apps/crm/index.html'}:
            content = (self.assets / 'index.html').read_text()
            content = content.replace('<html ', '<html data-crm-public-access="' + self.access + '" ', 1)
            return 200, 'text/html; charset=utf-8', content.encode()
        if path.startswith('/apps/crm/assets/'):
            relative = path[len('/apps/crm/'):]
            file = self.assets / relative
            if file.suffix not in {'.js', '.css', '.woff', '.woff2', '.svg', '.png', '.ico'}:
                return 404, 'application/json', b'{}'
            if file.is_file() and not any(p.is_symlink() for p in (file, *file.parents)) and file.stat().st_size <= MAX_RESPONSE:
                return 200, mimetypes.guess_type(str(file))[0] or 'application/octet-stream', file.read_bytes()
        return 404, 'application/json', b'{"error":"not_found"}'


class Handler(BaseHTTPRequestHandler):
    server_version = 'CRM'
    sys_version = ''
    timeout = 10

    def log_message(self, *_args):
        pass

    def do_GET(self):
        try:
            hosts = self.headers.get_all('Host', [])
            lengths = self.headers.get_all('Content-Length', [])
            if len(hosts) != 1 or len(lengths) > 1 or self.headers.get('Transfer-Encoding'):
                raise ValueError()
            size = int(lengths[0]) if lengths else 0
            if size < 0 or size > MAX_BODY or (self.command != 'POST' and size):
                raise ValueError()
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError()
            code, mime, content = self.server.runtime.response(
                self.command, hosts[0], self.path, {key.lower(): value for key, value in self.headers.items()}, body)
        except (ValueError, OSError):
            code, mime, content = 400, 'application/json', b'{"error":"invalid_request"}'
        self.send_response(code)
        for key, value in {
            'Content-Type': mime, 'Content-Length': str(len(content)), 'Cache-Control': 'no-store',
            'Content-Security-Policy': CSP, 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Origin-Agent-Cluster': '?1', 'X-Robots-Tag': 'noindex, nofollow',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
        }.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET


class Server(ThreadingMixIn, UnixStreamServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, path, runtime):
        self.runtime = runtime
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(str(path), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser()
    for key in ('root', 'assets', 'projection', 'hostname', 'access', 'socket'):
        parser.add_argument('--' + key, required=True)
    args = vars(parser.parse_args())
    path = Path(args.pop('socket'))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with Server(path, Runtime(**args)) as server:
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
