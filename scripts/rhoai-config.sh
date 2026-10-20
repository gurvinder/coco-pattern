#!/usr/bin/env bash
# Read the normal Pattern install values; there is one TEE choice.
RHOAI_INSTALL_VALUES=${RHOAI_INSTALL_VALUES:-$ROOT/sites/example/install.yaml}
export ROOT RHOAI_INSTALL_VALUES
rhoai_config=$(python3 - <<'PY'
import os,pathlib,re,shlex,yaml
root=pathlib.Path(os.environ['ROOT']).resolve()
path=pathlib.Path(os.environ['RHOAI_INSTALL_VALUES'])
if not path.is_absolute():path=root/path
config=yaml.safe_load(path.read_text())
base=yaml.safe_load((root/'values-global.yaml').read_text())['global']
parameters=config.get('main',{}).get('extraParameters',[])
assert not any(p['name'] in ('global.hardware.profile','global.rhoai.site') for p in parameters), 'Put the profile and site under global in install.yaml, not extraParameters'
selected=config.get('global',{})
profile=selected.get('hardware',{}).get('profile',base['hardware']['profile'])
site=selected.get('rhoai',{}).get('site',base['rhoai']['site'])
assert profile in ('intel-tdx-gpu','amd-snp-gpu'), 'Select intel-tdx-gpu or amd-snp-gpu in the Pattern install values'
assert re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)+',site), 'Use a repository-relative site directory'
assert (root/site).resolve().is_relative_to(root), 'Site must be inside this fork'
assert path.resolve()==(root/site/'install.yaml').resolve(), 'Use the selected site install.yaml'
assert config.get('global',{}).get('extraValueFiles')==[site+'/install.yaml'], 'global.extraValueFiles must load this install.yaml before shared values are expanded'
for key,value in {'RHOAI_INSTALL_VALUES':str(path.resolve()),'HARDWARE_PROFILE':profile,'RHOAI_SITE_DIR':str(root/site)}.items():
 print('export '+key+'='+shlex.quote(value))
PY
) || return 1
eval "$rhoai_config"
unset rhoai_config
