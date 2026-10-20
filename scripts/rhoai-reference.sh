#!/usr/bin/env bash
# Trusted workstation calculation from release artifacts, never from a quote.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/scripts/rhoai-config.sh"
STATE_DIR=${STATE_DIR:-$ROOT/.private/rhoai}
: "${REGISTRY_AUTH_FILE:?Supply entitled registry authentication}"
export STATE_DIR REGISTRY_AUTH_FILE
python3 - <<'PY'
import hashlib,json,logging,os,pathlib,shutil,yaml
from importlib.metadata import version
from veritas.platforms.baremetal import BaremetalExtractor
p=pathlib.Path(os.environ['STATE_DIR']);inputs=yaml.safe_load((p/'reference-inputs.yaml').read_text())
tee={'amd-snp-gpu':'snp','intel-tdx-gpu':'tdx'}[os.environ['HARDWARE_PROFILE']]
assert inputs['tee']==tee
platform=inputs.get('platformReferences',{})
if tee=='snp':
 required={'snp_bootloader','snp_tee_svn','snp_snp_svn','snp_microcode'}
 assert set(platform)==required, 'Supply the four SNP TCB reference arrays from independently verified platform collateral'
 assert all(isinstance(v,list) and v and all(type(n) is int and 0<=n<=255 for n in v) for v in platform.values()), 'SNP TCB references must be nonempty arrays of SVN bytes'
if tee=='tdx':assert shutil.which('tdx-measure'), 'Install the stock tdx-measure prerequisite'
assert inputs['vcpus']>=1 and inputs['memoryMiB']>=1
cmdline=inputs['kernelCommandLine'].strip()
assert f"nr_cpus={inputs['vcpus']}" in cmdline.split(), 'Reference CPU count differs from the reviewed kernel command line'
class ConfidentialGpuExtractor(BaremetalExtractor):
    GPU_INITRD_GLOB='osbuilder-images/*/kata-cc-nvidia-gpu*.initrd'
logging.basicConfig(level=logging.INFO)
extractor=ConfidentialGpuExtractor(tee,authfile=os.environ['REGISTRY_AUTH_FILE'],ocp_versions=[inputs['ocpVersion']],kernel_cmdline=cmdline,gpu=True,mem_size=inputs['memoryMiB']*1024*1024)
values={v.name:v.values for v in extractor.extract()}
fields={'launchMeasurement':'snp_launch_measurement'} if tee=='snp' else {'mrTd':'mr_td','rtmr1':'rtmr_1','rtmr2':'rtmr_2'}
expected={'tee':tee}
for field,key in fields.items():
 assert len(values.get(key,[]))==1, 'Expected exactly one confidential GPU reference: '+key
 expected[field]=values[key][0]
if tee=='tdx':
 assert inputs.get('xfam'), 'Supply the independently reviewed TDX XFAM setting'
 values['xfam']=[inputs['xfam']]
# Platform TCB values come from independently verified collateral.
for key,value in platform.items():
 assert key.startswith('snp_') and key!='snp_launch_measurement'
 values[key]=value
(p/'firmware-reference-values.json').write_text(json.dumps(values,indent=2)+'\n')
(p/'tee-reference.yaml').write_text(yaml.safe_dump(expected))
(p/'reference-provenance.json').write_text(json.dumps({'source':'OCP release artifacts through stock veritas','calculatorVersion':version('osc-veritas'),'inputs':inputs,'references':expected},indent=2)+'\n')
print('Computed exact confidential GPU references for',tee)
print('Enroll firmware-reference-values.json through normal CoCo values-secret before preparing the guest.')
PY
