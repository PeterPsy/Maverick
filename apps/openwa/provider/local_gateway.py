"""Operator-owned OpenWA provider process, isolated from other workspace files."""
from pathlib import Path
import os
import shutil

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT.parents[1] / 'workspaces' / 'default' / 'data' / 'openwa' / 'gateway'
INSTALL_ROOT = APP_ROOT.parents[1]
TOOLCHAINS = INSTALL_ROOT / '.toolchains'
SOURCE_ROOT = TOOLCHAINS / 'openwa-0.24.0'
NODE = TOOLCHAINS / 'node/bin/node'
CHROME = TOOLCHAINS / 'puppeteer/chrome/linux-146.0.7680.31/chrome-linux64/chrome'
MEDIA_LIB = TOOLCHAINS / 'media/usr/lib/x86_64-linux-gnu'

def environment():
    return {'PATH': f'{NODE.parent}:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'NODE_ENV': 'production',
        'LD_LIBRARY_PATH': str(MEDIA_LIB), 'HOME': '/data',
        'PORT': '2785', 'SERVE_DASHBOARD': 'false', 'ENABLE_SWAGGER': 'false', 'MCP_ENABLED': 'false',
        'ALLOW_DEV_API_KEY': 'false', 'AUTO_START_SESSIONS': 'true', 'LOG_LEVEL': 'warn', 'LOG_FORMAT': 'json',
        'MAIN_DATABASE_NAME': '/data/main.sqlite', 'DATABASE_NAME': '/data/openwa.sqlite',
        'DATABASE_TYPE': 'sqlite', 'DATABASE_SYNCHRONIZE': 'false', 'MAIN_DATABASE_SYNCHRONIZE': 'false',
        'SESSION_DATA_PATH': '/data/sessions', 'BAILEYS_AUTH_DIR': '/data/baileys', 'STORAGE_LOCAL_PATH': '/data/media',
        'PLUGIN_STATE_DIR': '/data/plugins', 'PLUGINS_DIR': '/data/plugins/packages',
        'ENGINE_TYPE': 'whatsapp-web.js', 'PUPPETEER_EXECUTABLE_PATH': str(CHROME),
        'QUEUE_ENABLED': 'false', 'REDIS_ENABLED': 'false', 'CACHE_ENABLED': 'false',
        'SEND_PACING_ENABLED': 'false', 'MAX_CONCURRENT_SESSIONS': '2', 'WEBHOOK_SSRF_PROTECT': 'true'}

def command():
    bwrap = shutil.which('bwrap')
    if not bwrap or not (SOURCE_ROOT / 'dist/main.js').is_file() or not NODE.is_file() or not CHROME.is_file():
        raise RuntimeError('The verified OpenWA build, installation Node/Chrome and bubblewrap are required.')
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.chmod(0o700)
    args = [bwrap,'--die-with-parent','--unshare-user','--uid','0','--gid','0','--unshare-pid','--unshare-ipc','--unshare-uts']
    for source, target in [('/usr','/usr'),('/lib','/lib'),('/lib64','/lib64'),
            ('/etc/ssl','/etc/ssl'),('/etc/fonts','/etc/fonts'),('/etc/resolv.conf','/etc/resolv.conf'),('/etc/hosts','/etc/hosts'),('/etc/nsswitch.conf','/etc/nsswitch.conf')]:
        if Path(source).exists(): args += ['--ro-bind',source,target]
    return args + ['--ro-bind',str(TOOLCHAINS),str(TOOLCHAINS),
        '--ro-bind',str(APP_ROOT / 'provider/passwd'),'/etc/passwd', '--ro-bind',str(SOURCE_ROOT),'/app','--bind',str(DATA_ROOT),'/data',
        '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--chdir','/data',str(NODE),'/app/dist/main.js']

if __name__ == '__main__':
    if not (DATA_ROOT / 'main.sqlite').is_file():
        raise SystemExit('Bootstrap the gateway through provider/bootstrap_local.py before starting the supervisor.')
    args = command()
    os.execve(args[0], args, environment())
