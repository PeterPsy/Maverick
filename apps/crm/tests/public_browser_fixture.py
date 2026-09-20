"""Foreground browser fixture: disposable CRM, real confined HTTP runtime."""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP / 'backend'), str(APP.parents[1])]
from external_hosting import atomic_json
from public_server.confinement import command
from service import handle_action

HOST = 'crm.apps.example.test'


def main():
    with tempfile.TemporaryDirectory(prefix='crm-public-browser-') as temporary:
        base = Path(temporary)
        data, state, listener = (base / name for name in ('data', 'state', 'listener'))
        state.mkdir(); listener.mkdir()
        handle_action(data, 'crm.create_contact', {'display_name': 'Public Browser Contact', 'email': 'browser@example.test'})
        atomic_json(data / 'external-hosting/access.json', {'enabled': True, 'access': 'read-only', 'revision': 1})
        atomic_json(data / 'external-hosting/deployment.json', {'installation_domain': 'example.test'})
        stopped = threading.Event()

        def renew():
            while not stopped.is_set():
                atomic_json(state / 'authority.json', {'hostname': HOST, 'revision': 1, 'expires': time.time() + 8})
                stopped.wait(1)

        lease = threading.Thread(target=renew, daemon=True); lease.start()
        child = subprocess.Popen(command(app=APP, data=data, state=state,
                                         listener=listener, host=HOST, access='read-only'),
                                 env={'PATH': '/usr/bin:/bin'}, stdin=subprocess.DEVNULL)

        class Bridge(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                connection = HTTPConnection('fixture', timeout=10)
                connection.sock = socket.socket(socket.AF_UNIX)
                connection.sock.connect(str(listener / 'public.sock'))
                headers = {'Host': HOST}
                if self.headers.get('Content-Type'):
                    headers['Content-Type'] = self.headers['Content-Type']
                if self.headers.get('Origin') == f'http://127.0.0.1:{self.server.server_port}':
                    headers['Origin'] = 'https://' + HOST
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(response.read())
                except BrokenPipeError:
                    pass
                finally:
                    connection.close()

            do_POST = do_GET

        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            deadline = time.time() + 10
            while not (listener / 'public.sock').exists():
                if child.poll() is not None or time.time() >= deadline:
                    raise RuntimeError('confined_fixture_start_failed')
                time.sleep(.05)
            with ThreadingHTTPServer(('127.0.0.1', 0), Bridge) as server:
                print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}'}), flush=True)
                server.serve_forever(poll_interval=.1)
        finally:
            stopped.set(); lease.join(timeout=2)
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)


if __name__ == '__main__':
    main()
