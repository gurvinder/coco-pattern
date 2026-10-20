#!/usr/bin/env bash
# Negative checks run in the already-trusted publisher namespace, not the guest.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
source "$ROOT/scripts/rhoai-config.sh"
STATE_DIR=${STATE_DIR:-$ROOT/.private/rhoai}
PUBLISHER_NAMESPACE=${PUBLISHER_NAMESPACE:-rhoai-model-publisher}
export ROOT STATE_DIR PUBLISHER_NAMESPACE
umask 077
python3 - <<'PY'
import json,os,pathlib,yaml
r=pathlib.Path(os.environ['ROOT']);p=pathlib.Path(os.environ['STATE_DIR'])
ns=os.environ['PUBLISHER_NAMESPACE'];s=yaml.safe_load((pathlib.Path(os.environ['RHOAI_SITE_DIR'])/'values-distribution.yaml').read_text())['distribution']['s3']
receipt=json.loads((p/'publication.json').read_text());assert receipt['uri']==s['uri']
name='verify-model-s3'
meta={'name':name,'namespace':ns}
objects=[
 {'apiVersion':'external-secrets.io/v1','kind':'ExternalSecret','metadata':meta,'spec':{
  'secretStoreRef':{'name':'vault-backend','kind':'ClusterSecretStore'},
  'target':{'name':name},'data':[{'secretKey':'credentials','remoteRef':{'key':s['readerVaultPath'],'property':'credentials'}}]}},
 {'apiVersion':'v1','kind':'ConfigMap','metadata':meta,'data':{
  'verify.py':(r/'tests/rhoai/verify_s3.py').read_text(),
  'model.sha256':(r/'charts/hub/rhoai-model-publisher/files/model.sha256').read_text(),
  'wrong-ca.crt':(p/'chat-ca.crt').read_text(),
  's3-ca.crt':s['caBundle']}},
]
image=yaml.safe_load((r/'charts/hub/rhoai-model-publisher/values.yaml').read_text())['image']
env={'MODEL_URI':s['uri'],'EXPECTED_SHA256':receipt['sha256'],'AWS_ENDPOINT_URL':s['endpoint'],
 'AWS_DEFAULT_REGION':s['region'],'AWS_SHARED_CREDENTIALS_FILE':'/credentials/credentials',
 'AWS_EC2_METADATA_DISABLED':'true','S3_VERIFY_SSL':'true','S3_USER_VIRTUAL_BUCKET':'false'}
if s['caBundle']:env['AWS_CA_BUNDLE']='/scripts/s3-ca.crt'
objects.append({'apiVersion':'batch/v1','kind':'Job','metadata':meta,'spec':{
 'backoffLimit':0,'activeDeadlineSeconds':600,'template':{
  'metadata':{'labels':{'coco.io/skip-initdata':'true'}},
  'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,
   'containers':[{'name':'verify','image':image,'command':['python3','/scripts/verify.py'],
    'env':[{'name':k,'value':v} for k,v in env.items()],
    'resources':{'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1','memory':'512Mi'}},
    'volumeMounts':[{'name':n,'mountPath':m,'readOnly':True} for n,m in [('scripts','/scripts'),('credentials','/credentials'),('publisher','/publisher-credentials'),('key','/keys')]]}],
   'volumes':[{'name':'scripts','configMap':{'name':name}},{'name':'credentials','secret':{'secretName':name}},
    {'name':'publisher','secret':{'secretName':s['publisherCredentialsSecret']}},
    {'name':'key','secret':{'secretName':'model-publisher-key'}}]}}}})
(p/'s3-test.yaml').write_text(yaml.safe_dump_all(objects))
PY
oc delete job verify-model-s3 -n "$PUBLISHER_NAMESPACE" --ignore-not-found
oc apply -f "$STATE_DIR/s3-test.yaml"
oc wait --for=condition=Complete job/verify-model-s3 -n "$PUBLISHER_NAMESPACE" --timeout=10m
oc logs job/verify-model-s3 -n "$PUBLISHER_NAMESPACE" > "$STATE_DIR/s3-negative-result.log"
cat "$STATE_DIR/s3-negative-result.log"
oc delete -f "$STATE_DIR/s3-test.yaml"
