"""Operator-owned OpenWA provider process, isolated from other workspace files."""
from pathlib import Path
import os
import shutil

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT.parents[1] / 'workspaces' / 'default' / 'data' / 'openwa' / 'gateway'
SOURCE_ROOT = APP_ROOT / 'provider' / 'upstream'

def environment():
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'NODE_ENV': 'production',
        'PORT': '2785', 'SERVE_DASHBOARD': 'false', 'ENABLE_SWAGGER': 'false', 'MCP_ENABLED': 'false',
        'ALLOW_DEV_API_KEY': 'false', 'AUTO_START_SESSIONS': 'true', 'LOG_LEVEL': 'warn', 'LOG_FORMAT': 'json',
        'MAIN_DATABASE_NAME': '/data/main.sqlite', 'DATABASE_NAME': '/data/openwa.sqlite',
        'DATABASE_TYPE': 'sqlite', 'DATABASE_SYNCHRONIZE': 'false', 'MAIN_DATABASE_SYNCHRONIZE': 'false',
        'SESSION_DATA_PATH': '/data/sessions', 'BAILEYS_AUTH_DIR': '/data/baileys', 'STORAGE_LOCAL_PATH': '/data/media',
        'PLUGIN_STATE_DIR': '/data/plugins', 'PLUGINS_DIR': '/data/plugins/packages',
        'ENGINE_TYPE': 'whatsapp-web.js', 'PUPPETEER_EXECUTABLE_PATH': '/opt/google/chrome/chrome',
        'QUEUE_ENABLED': 'false', 'REDIS_ENABLED': 'false', 'CACHE_ENABLED': 'false',
        'SEND_PACING_ENABLED': 'false', 'MAX_CONCURRENT_SESSIONS': '2', 'WEBHOOK_SSRF_PROTECT': 'true'}

def command():
    if not shutil.which('bwrap') or not (SOURCE_ROOT / 'dist/main.js').is_file():
        raise RuntimeError('The verified OpenWA build and bubblewrap are required.')
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.chmod(0o700)
    args = ['bwrap','--die-with-parent','--unshare-user','--uid','0','--gid','0','--unshare-pid','--unshare-ipc','--unshare-uts']
    for source, target in [('/usr','/usr'),('/lib','/lib'),('/lib64','/lib64'),('/opt/google/chrome','/opt/google/chrome'),
            ('/etc/ssl','/etc/ssl'),('/etc/fonts','/etc/fonts'),('/etc/resolv.conf','/etc/resolv.conf'),('/etc/hosts','/etc/hosts'),('/etc/nsswitch.conf','/etc/nsswitch.conf')]:
        if Path(source).exists(): args += ['--ro-bind',source,target]
    return args + ['--ro-bind',str(APP_ROOT / 'provider/passwd'),'/etc/passwd', '--ro-bind',str(SOURCE_ROOT),'/app','--bind',str(DATA_ROOT),'/data',
        '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--chdir','/data','/usr/local/bin/node','/app/dist/main.js']

if __name__ == '__main__':
    if not (DATA_ROOT / 'main.sqlite').is_file():
        raise SystemExit('Bootstrap the gateway through provider/bootstrap_local.py before starting the supervisor.')
    os.execvpe('bwrap', command(), environment())
