"""Explicit start/status/stop paths for the dedicated local provider supervisor."""
from pathlib import Path
import json
import subprocess
import sys
import time
import urllib.request

APP_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = APP_ROOT.parents[1] / 'data' / 'openwa' / 'supervisor'
NAME = 'maverick-openwa-default'

def run(action):
    SUPERVISOR.mkdir(parents=True, exist_ok=True)
    SUPERVISOR.chmod(0o700)
    env = {'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','PM2_HOME':str(SUPERVISOR)}
    if action == 'start':
        args = ['pm2','start',str(APP_ROOT / 'runtime/local_gateway.py'),'--name',NAME,'--interpreter','/usr/bin/python3',
                '--cwd',str(APP_ROOT),'--max-memory-restart','600M','--restart-delay','5000','--time']
    elif action == 'status':args=['pm2','pid',NAME]
    elif action == 'stop':args=['pm2','stop',NAME]
    elif action == 'restart':args=['pm2','restart',NAME]
    else:raise ValueError('Use start, status, restart or stop.')
    result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=30)
    if action in ('start','restart') and result.returncode==0:
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:2785/api/health/ready',timeout=2) as response:
                    if response.status==200:break
            except OSError:time.sleep(.5)
        else:raise SystemExit('The OpenWA process started but its API did not become ready. Inspect only its scoped supervisor logs.')
    if action == 'status':
        lines=[int(x) for x in result.stdout.splitlines() if x.isdigit()]
        print(json.dumps({'name':NAME,'running':any(lines),'pids':[x for x in lines if x]}))
    else:
        print(json.dumps({'name':NAME,'action':action,'ok':result.returncode==0}))
        if result.returncode:raise SystemExit('The dedicated OpenWA supervisor operation failed.')

if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'status')
