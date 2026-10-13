"""One-time local provisioning: Core owns the raw API key; OpenWA persists its hash."""
import json
import os
import secrets
import subprocess
import time
import urllib.request
import urllib.error
from local_gateway import DATA_ROOT, command, environment

def cli(owner, name, flags):
    result=subprocess.run(['maverick',*owner,'run',name,*flags,'--json'],env={**os.environ,'MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE':'full'},capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('A governed Maverick provisioning operation failed: '+name)
    value=json.loads(result.stdout)
    if value.get('ok') is False or value.get('status_code',200)>=400:
        raise RuntimeError('A governed Maverick provisioning operation failed: '+name)
    return value

def bootstrap():
    if (DATA_ROOT / 'main.sqlite').exists():
        raise RuntimeError('This gateway is already initialized; use the native provider CLI to start or restart.')
    key='owa_k1_'+secrets.token_hex(32)
    alias='openwa-default-gateway'
    inventory=cli(['core','cli'],'core.secrets.list',[])
    existing=next((item for item in inventory.get('secrets',[]) if isinstance(item,dict) and item.get('alias')==alias),None)
    grants=cli(['core','cli'],'core.secret_grants.list',['--workspace-id','default'])
    active=[item for item in grants.get('items',[]) if isinstance(item,dict) and item.get('app_id')=='openwa'
            and item.get('logical_name')=='openwa-api-key' and item.get('effective_status')=='active']
    expected=['maverick://app.backend/backend','maverick://app.backend/cli/openwa','maverick://app.backend/mcp/*']
    if active and not any(item.get('secret_ref')=='platform:secret-alias/'+alias and set(expected)<=set(item.get('target_patterns',[])) for item in active):
        raise RuntimeError('The app is bound to a different or restricted credential. Configure its local provider grant explicitly in Vault before bootstrapping.')
    if existing:
        cli(['core','cli'],'core.secrets.rotate',['--secret-id',existing['secret_id'],'--raw-value',key])
    else:
        cli(['core','cli'],'core.secrets.create',['--label','OpenWA default gateway','--alias',alias,'--raw-value',key])
    if not active:
      cli(['core','cli'],'core.secret_grants.create',['--app-id','openwa','--logical-name','openwa-api-key','--alias',alias,
        '--actions','["app.backend"]','--target-patterns','["maverick://app.backend/backend","maverick://app.backend/cli/openwa","maverick://app.backend/mcp/*"]',
        '--reason','Native OpenWA application installed by the workspace administrator.'])
    env={**environment(),'API_MASTER_KEY':key}
    # The foreground bootstrap process is always stopped, including cancellation and errors.
    DATA_ROOT.mkdir(parents=True,exist_ok=True)
    generated=DATA_ROOT/'data'/'.env.generated'
    generated.parent.mkdir(parents=True,exist_ok=True)
    generated.write_text('# Configured by the native Maverick OpenWA installer; secrets remain in Core.\n')
    generated.chmod(0o600)
    process=subprocess.Popen(command(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
    try:
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            if process.poll() is not None:
                diagnostic=process.stderr.read().decode(errors='replace').replace(key,'[redacted]')[-4000:]
                raise RuntimeError('The OpenWA bootstrap process did not start: '+diagnostic)
            request=urllib.request.Request('http://127.0.0.1:2785/api/auth/validate',data=b'{}',headers={'Content-Type':'application/json','X-API-Key':key},method='POST')
            try:
                with urllib.request.urlopen(request,timeout=2) as response:
                    if json.load(response).get('valid'):break
            except (OSError,urllib.error.URLError):time.sleep(.5)
        else:raise RuntimeError('OpenWA did not become ready within the bootstrap timeout.')
        cli(['app','openwa','cli'],'openwa',['--action','connection.save','--url','http://127.0.0.1:2785'])
    finally:
        process.terminate()
        try:process.wait(timeout=12)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    print(json.dumps({'credential':'stored_in_core','gateway':'initialized','origin':'http://127.0.0.1:2785'}))

if __name__=='__main__':bootstrap()
