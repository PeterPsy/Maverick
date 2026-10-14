"""Reproduce the pinned provider build without copying unrelated Loopino apps."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

APP = Path(__file__).resolve().parents[1]
TARGET = APP.parents[1] / '.toolchains' / 'openwa-0.24.0'
REPOSITORY = 'https://github.com/rmyndharis/OpenWA'
COMMIT = '8a45366a287750cf52c2658b0b783747cf51fad2'

def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, 'PUPPETEER_SKIP_DOWNLOAD':'true'})

def install():
    if TARGET.exists():
        provenance = TARGET / 'install-provenance.json'
        if provenance.is_file() and json.loads(provenance.read_text()).get('commit') == COMMIT and (TARGET/'dist/main.js').is_file():
            print(json.dumps({'status':'already_installed','commit':COMMIT}))
            return
        raise RuntimeError('An incomplete or different provider build exists. Stop its supervisor and preserve it before reinstalling.')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TARGET.parent, prefix='.openwa-source-') as temporary:
        source=Path(temporary)/'source'
        run(['git','clone','--no-checkout',REPOSITORY,str(source)], APP)
        run(['git','checkout','--detach',COMMIT], source)
        resolved=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
        if resolved != COMMIT:raise RuntimeError('The provider revision does not match the pinned source.')
        shutil.copytree(source,TARGET,ignore=shutil.ignore_patterns('.git'))
    p=TARGET/'src/main.ts'
    original=p.read_text()
    if 'await app.listen(port);' not in original:raise RuntimeError('The reviewed listener patch no longer matches.')
    p.write_text(original.replace('await app.listen(port);',"await app.listen(port, '127.0.0.1');"))
    p=TARGET/'src/modules/auth/auth.service.ts'
    original=p.read_text()
    if 'writeBootstrapKey(displayKey);' not in original or 'bannerKeyLine(displayKey, isNewKey)' not in original:
        raise RuntimeError('The reviewed credential patch no longer matches.')
    p.write_text(original.replace('writeBootstrapKey(displayKey);','if (!process.env.API_MASTER_KEY) writeBootstrapKey(displayKey);')
                        .replace('bannerKeyLine(displayKey, isNewKey)','bannerKeyLine(displayKey, false)'))
    p=TARGET/'package.json';package=json.loads(p.read_text());package['overrides']['music-metadata']='11.16.0';p.write_text(json.dumps(package,indent=2)+'\n')
    shutil.copyfile(APP/'provider/provider-package-lock.json', TARGET/'package-lock.json')
    run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],TARGET)
    run(['npm','rebuild','better-sqlite3','sharp'],TARGET)
    patch_script="const p=require('./scripts/postinstall.js');for(const s of p.planSteps(process.cwd()).filter(x=>x.name!=='dashboard dependencies (npm ci)')){const r=require('node:child_process').spawnSync(s.command,s.args||[],s.options);if(r.status!==0)process.exit(r.status||1)}"
    run(['node','-e',patch_script],TARGET)
    run(['npm','run','build'],TARGET)
    (TARGET/'install-provenance.json').write_text(json.dumps({'repository':REPOSITORY,'commit':COMMIT,'version':'0.24.0',
        'patches':['loopback listener','Core-owned API bootstrap','music-metadata 11.16.0','upstream engine repairs']},indent=2)+'\n')
    print(json.dumps({'status':'installed','commit':COMMIT}))

if __name__=='__main__':install()
