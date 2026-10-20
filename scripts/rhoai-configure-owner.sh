#!/usr/bin/env bash
# Only selected site files are written. Shared charts/defaults remain generic.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/scripts/rhoai-config.sh"
STATE_DIR=${STATE_DIR:-$ROOT/.private/rhoai}
MODE=${1:-bootstrap}
export ROOT STATE_DIR MODE
python3 - <<'PY'
import base64,gzip,hashlib,os,pathlib,shutil,yaml
root=pathlib.Path(os.environ['ROOT']).resolve();state=pathlib.Path(os.environ['STATE_DIR'])
site=pathlib.Path(os.environ['RHOAI_SITE_DIR']);site.mkdir(parents=True,exist_ok=True)
mode=os.environ['MODE'];assert mode in ('bootstrap','ready')
assert pathlib.Path(os.environ.get('COCO_CHECKOUT',str(root))).resolve()==root.resolve(), 'Use this fork as COCO_CHECKOUT'
path=site/'values-site.yaml';values=yaml.safe_load(path.read_text()) if path.exists() else {}
values=values or {};apps=values.setdefault('clusterGroup',{}).setdefault('applications',{})
apps.setdefault('rhoai-platform',{})['disabled']=False
if mode=='ready':
 workload=yaml.safe_load((state/'site.yaml').read_text())
 identity=hashlib.sha256(gzip.decompress(base64.b64decode(workload['guest']['initdata']))).hexdigest()
 binding=yaml.safe_load((state/'trustee-binding.yaml').read_text())
 expected=binding['kbs']['resourcePolicy']['confidentialGuestBindings']['rhoai-qwen-secrets']
 assert expected['tee']=={'amd-snp-gpu':'snp','intel-tdx-gpu':'tdx'}[os.environ['HARDWARE_PROFILE']], 'Binding TEE does not match selected CoCo profile'
 assert expected['initData']==identity, 'Binding differs from measured guest'
 shutil.copyfile(state/'site.yaml',site/'values-qwen.yaml')
 shutil.copyfile(state/'trustee-binding.yaml',site/'values-trustee.yaml')
 for name in ('rhoai-model-publisher','rhoai-confidential-qwen'):apps.setdefault(name,{})['disabled']=False
elif not (state/'site.yaml').exists():
 for name in ('rhoai-model-publisher','rhoai-confidential-qwen'):apps.setdefault(name,{})['disabled']=True
 (site/'values-qwen.yaml').write_text('{}\n')
 (site/'values-trustee.yaml').write_text('kbs:\n  resourcePolicy:\n    confidentialGuestBindings: {}\n')
path.write_text('# Public configuration for this site only.\n'+yaml.safe_dump(values,sort_keys=False))
print('Prepared',mode,'for',os.environ['HARDWARE_PROFILE'],'in',site.relative_to(root))
print('Commit and push the site files. Private keys were not copied.')
PY
