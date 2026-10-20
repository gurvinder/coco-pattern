#!/usr/bin/env bash
# One-time credential enrollment and public site configuration. ODF stays GitOps-owned.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/scripts/rhoai-config.sh"
STATE_DIR=${STATE_DIR:-$ROOT/.private/rhoai}
export ROOT STATE_DIR
umask 077
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
python3 - "${1:?Usage: rhoai-s3.sh odf|external}" <<'PY'
import base64
import configparser
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid
import yaml

root = Path(os.environ['ROOT'])
state = Path(os.environ['STATE_DIR'])
site = Path(os.environ['RHOAI_SITE_DIR'])
mode = sys.argv[1]
assert mode in ('odf', 'external'), 'Choose odf or external'

def oc(*args):
    return subprocess.check_output(['oc', *args], text=True)

def get(kind, name, namespace):
    return json.loads(oc('get', kind, name, '-n', namespace, '-o', 'json'))

def wait(kind, name, namespace, phase=None):
    deadline = time.monotonic()+1200
    while time.monotonic() < deadline:
        raw = oc('get', kind, name, '-n', namespace, '-o', 'json', '--ignore-not-found')
        if raw:
            status = json.loads(raw).get('status', {})
            if phase and status.get('phase') == phase:
                return
            conditions = status.get('conditions', [])
            if not phase and any(c['type'] == 'Complete' and c['status'] == 'True' for c in conditions):
                return
            assert status.get('phase') != 'Rejected', 'ODF rejected '+kind+'/'+name
            assert not any(c['type'] == 'Failed' and c['status'] == 'True' for c in conditions), 'ODF Job failed: '+name
        time.sleep(5)
    raise TimeoutError('ODF resource not ready: '+kind+'/'+name)

def credentials(data):
    parser = configparser.ConfigParser(interpolation=None)
    parser['default'] = data
    output = io.StringIO()
    parser.write(output)
    return output.getvalue()

def validate_credentials(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    assert parser.sections() == ['default'], 'Use one [default] SDK credential profile'
    data = dict(parser['default'])
    assert {'aws_access_key_id', 'aws_secret_access_key'} <= data.keys()
    assert data.keys() <= {'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token'}
    assert all(value and '\n' not in value for value in data.values())
    return credentials(data)

region = os.environ.get('S3_REGION', 'us-east-1')
if mode == 'odf':
    namespace = os.environ.get('ODF_NAMESPACE', 'openshift-storage')
    settings = yaml.safe_load((root/'charts/hub/rhoai-object-storage/values.yaml').read_text())['objectStorage']
    if (site/'values-object-storage.yaml').exists():
        settings.update(yaml.safe_load((site/'values-object-storage.yaml').read_text())['objectStorage'])
    wait('obc', settings['bucket'], namespace, 'Bound')
    for name in (settings['publisherAccount'], settings['readerAccount']):
        wait('noobaaaccount', name, namespace, 'Ready')
    wait('job', 'rhoai-object-storage-policy', namespace)
    bucket = get('configmap', settings['bucket'], namespace)['data']['BUCKET_NAME']
    endpoint = 'https://s3.'+namespace+'.svc'
    ca = get('configmap', 'rhoai-object-storage-ca', namespace)['data']['service-ca.crt']
    files = {}
    for role, account in [('publisher', settings['publisherAccount']), ('reader', settings['readerAccount'])]:
        secret = get('secret', 'noobaa-account-'+account, namespace)['data']
        files[role] = credentials({
            'aws_access_key_id': base64.b64decode(secret['AWS_ACCESS_KEY_ID']).decode(),
            'aws_secret_access_key': base64.b64decode(secret['AWS_SECRET_ACCESS_KEY']).decode(),
        })
    release = os.environ.get('S3_RELEASE_ID')
    record = state/'s3-release.json'
    if not release and record.exists():
        old = json.loads(record.read_text())
        assert old['endpoint'] == endpoint and old['bucket'] == bucket, 'S3 destination changed; choose a new S3_RELEASE_ID'
        release = old['release']
    release = release or uuid.uuid4().hex
    assert re.fullmatch('[A-Za-z0-9_-]+', release), 'Invalid release ID'
    uri = 's3://'+bucket+'/'+settings['prefix']+'/'+release+'/qwen.tar'
    record.write_text(json.dumps({'endpoint': endpoint, 'bucket': bucket, 'release': release})+'\n')
else:
    endpoint = os.environ['S3_ENDPOINT']
    uri = os.environ['S3_URI']
    ca = Path(os.environ['S3_CA_FILE']).read_text() if os.environ.get('S3_CA_FILE') else ''
    files = {role: Path(os.environ['S3_'+role.upper()+'_CREDENTIALS_FILE']).read_text()
             for role in ('publisher', 'reader')}

parsed = urlparse(uri)
endpoint_url = urlparse(endpoint)
assert endpoint_url.scheme == 'https' and endpoint_url.hostname and not endpoint_url.username
assert not endpoint_url.password and not endpoint_url.query and not endpoint_url.fragment
assert parsed.scheme == 's3' and parsed.netloc and not parsed.query and not parsed.fragment
assert parsed.path.endswith('/qwen.tar') and len(parsed.path.strip('/').split('/')) >= 3
assert '..' not in parsed.path.split('/')
files = {role: validate_credentials(text) for role, text in files.items()}
identities = []
for text in files.values():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    identities.append(parser['default']['aws_access_key_id'])
assert len(set(identities)) == 2, 'Use distinct publisher-write and inference-read access-key IDs'
if os.environ.get('VAULT_ADMIN_TOKEN_FILE'):
    token = Path(os.environ['VAULT_ADMIN_TOKEN_FILE']).read_text().strip()
else:
    handoff = get('secret', 'vaultkeys', 'imperative')
    token = json.loads(base64.b64decode(handoff['data']['vault_data_json']))['root_token']
for role, text in files.items():
    (state/('s3-'+role+'.credentials')).write_text(text)
    vault_path = 'secret/hub/rhoaiS3'+role.title()
    subprocess.run(
        ['oc', 'exec', '-i', '-n', 'vault', 'vault-0', '--', 'sh', '-c',
         'set -eu; read -r VAULT_TOKEN; export VAULT_TOKEN; exec vault kv put '+vault_path+' -'],
        input=token+'\n'+json.dumps({'credentials': text}), text=True,
        stdout=subprocess.DEVNULL, check=True,
    )
public = {'distribution': {'backend': 's3', 's3': {
    'uri': uri, 'endpoint': endpoint, 'region': region, 'caBundle': ca,
    'readerCredentialsSecret': 'model-s3-reader',
    'readerVaultPath': 'secret/data/hub/rhoaiS3Reader',
    'publisherCredentialsSecret': 'model-s3-publisher',
    'publisherVaultPath': 'secret/data/hub/rhoaiS3Publisher',
}}}
(site/'values-distribution.yaml').write_text(yaml.safe_dump(public, sort_keys=False))
(state/'s3-ca.crt').write_text(ca)
print('S3 credentials enrolled in Vault; public configuration:', site/'values-distribution.yaml')
print('Publish and verify before preparing the measured guest:', uri)
PY
