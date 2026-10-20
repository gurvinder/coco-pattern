#!/usr/bin/env bash
# Ordered, administrator-run installation helpers; no resident custom controller.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/scripts/rhoai-config.sh"
HELM=${HELM:-helm}
DEMO_NAMESPACE=${DEMO_NAMESPACE:-rhoai-confidential-qwen}
PUBLISHER_NAMESPACE=${PUBLISHER_NAMESPACE:-rhoai-model-publisher}
STATE_DIR=${STATE_DIR:-$ROOT/.private/rhoai}
STORAGE_CLASS=${STORAGE_CLASS:-lvms-vg1}
export ROOT DEMO_NAMESPACE PUBLISHER_NAMESPACE STATE_DIR STORAGE_CLASS
umask 077
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
need() { command -v "$1" >/dev/null || { echo "Missing prerequisite: $1" >&2; exit 1; }; }
for command in oc "$HELM" python3 openssl; do need "$command"; done
[[ $("$HELM" version --short) == v3.* ]] || { echo 'Helm 3 is required' >&2; exit 1; }
python3 -c 'import yaml' || { echo 'Install the pinned installation dependencies' >&2; exit 1; }
namespace() { oc create namespace "$1" --dry-run=client -o yaml | oc apply -f -; }
case "${1:-help}" in
  preflight)
    oc whoami >/dev/null
    oc get runtimeclass kata-cc-nvidia-gpu -o json | python3 -c 'import json,os,sys; r=json.load(sys.stdin); tee={"amd-snp-gpu":"snp","intel-tdx-gpu":"tdx"}[os.environ["HARDWARE_PROFILE"]]; assert r["handler"]=="kata-"+tee+"-nvidia-gpu", "RuntimeClass does not match the selected CoCo hardware profile"'
    oc get storageclass "$STORAGE_CLASS" >/dev/null
    oc get kbsconfig kbsconfig -n trustee-operator-system >/dev/null
    oc get nodes -o json | python3 -c 'import json,sys; nodes=json.load(sys.stdin)["items"]; eligible=[]
for node in nodes:
 a=node["metadata"].get("annotations",{}); prefix="machineconfiguration.openshift.io/"
 ready=any(c["type"]=="Ready" and c["status"]=="True" for c in node["status"].get("conditions",[]))
 configured=a.get(prefix+"currentConfig")==a.get(prefix+"desiredConfig") and a.get(prefix+"state","Done")=="Done"
 if ready and configured and not node["spec"].get("unschedulable",False) and int(node["status"]["allocatable"].get("nvidia.com/pgpu","0"))>=1: eligible.append(node)
assert eligible, "No ready, schedulable confidential GPU node with completed machine configuration; wait for node recovery"
print("CoCo runtime, block-storage class and configured passthrough GPU node present")'
    oc rollout status deployment/trustee-deployment -n trustee-operator-system --timeout="${PREFLIGHT_TIMEOUT:-10m}"
    oc rollout status deployment/kyverno-admission-controller -n kyverno --timeout="${PREFLIGHT_TIMEOUT:-10m}"
    # Two controllers watching the same APIs must never compete.
    oc get deployment kserve-controller-manager -n kserve --ignore-not-found -o json | \
      python3 -c 'import sys,json; s=sys.stdin.read(); assert not s or json.loads(s)["spec"].get("replicas",1)==0, "Retire the old upstream KServe owner before installing RHOAI"'
    ;;
  platform)
    # Installation belongs to Argo CD. This optional command only waits/checks.
    for ((i=0; i<360; i++)); do
      csv=$(oc get csv/rhods-operator.3.6.0-ea.2 -n redhat-ods-operator --ignore-not-found -o name)
      [ -n "$csv" ] && break
      sleep 5
    done
    [ -n "${csv:-}" ] || { echo 'RHOAI is not installed; inspect the rhoai-platform Argo application'; exit 1; }
    oc wait --for=jsonpath='{.status.phase}'=Succeeded csv/rhods-operator.3.6.0-ea.2 -n redhat-ods-operator --timeout=15m
    for ((i=0; i<180; i++)); do
      dsc=$(oc get datasciencecluster/default-dsc --ignore-not-found -o name)
      [ -n "$dsc" ] && break
      sleep 5
    done
    [ -n "${dsc:-}" ] || { echo 'RHOAI DataScienceCluster is not configured; inspect rhoai-platform'; exit 1; }
    oc wait --for=condition=Ready datasciencecluster/default-dsc --timeout=15m
    oc wait --for=condition=Established crd/llminferenceservices.serving.kserve.io --timeout=5m
    ;;
  build)
    namespace "$DEMO_NAMESPACE"
    python3 - <<'PY'
import hashlib,json,os,pathlib
r=pathlib.Path(os.environ['ROOT'])/'build/storage-initializer'
p=json.loads((r/'provenance.json').read_text())
assert hashlib.sha256((r/'jwe_decryptor.py').read_bytes()).hexdigest()==p['sha256'], 'Unreviewed decryptor change'
PY
    sed "s/namespace: rhoai-confidential-qwen/namespace: $DEMO_NAMESPACE/g" "$ROOT/build/storage-initializer/build.yaml" | oc apply -f -
    build=$(oc start-build storage-initializer-streaming -n "$DEMO_NAMESPACE" --from-dir="$ROOT/build/storage-initializer" -o name)
    oc logs -f -n "$DEMO_NAMESPACE" "$build"
    oc wait --for=jsonpath='{.status.phase}'=Complete -n "$DEMO_NAMESPACE" "$build" --timeout=20m
    oc get "$build" -n "$DEMO_NAMESPACE" -o json | python3 -c 'import json,sys,os,pathlib; b=json.load(sys.stdin); digest=b["status"]["output"]["to"]["imageDigest"]; assert digest.startswith("sha256:"); pathlib.Path(os.environ["STATE_DIR"],"initializer-image").write_text("image-registry.openshift-image-registry.svc:5000/"+os.environ["DEMO_NAMESPACE"]+"/storage-initializer-streaming@"+digest+"\n")'
    ;;
  publish)
    : "${MODEL_KEY_FILE:?Set MODEL_KEY_FILE to the private JWK file enrolled with Trustee}"
    namespace "$PUBLISHER_NAMESPACE"
    oc create secret generic model-publisher-key -n "$PUBLISHER_NAMESPACE" --from-file=model-key.json="$MODEL_KEY_FILE" --dry-run=client -o yaml | oc apply -f -
    distribution_args=()
    if [ -f "$RHOAI_SITE_DIR/values-distribution.yaml" ]; then
      distribution_args=(-f "$RHOAI_SITE_DIR/values-distribution.yaml")
    fi
    "$HELM" template publisher "$ROOT/charts/hub/rhoai-model-publisher" -n "$PUBLISHER_NAMESPACE" --set storageClass="$STORAGE_CLASS" ${distribution_args[@]+"${distribution_args[@]}"} > "$STATE_DIR/publisher.yaml"
    oc apply -f "$STATE_DIR/publisher.yaml"
    job=$(python3 -c 'import os,yaml,pathlib; print(next(x["metadata"]["name"] for x in yaml.safe_load_all((pathlib.Path(os.environ["STATE_DIR"])/"publisher.yaml").read_text()) if x and x["kind"]=="Job"))')
    export PUBLICATION_JOB=$job
    python3 - <<'PY'
import json,os,pathlib,subprocess,time
job=os.environ['PUBLICATION_JOB'];ns=os.environ['PUBLISHER_NAMESPACE']
deadline=time.monotonic()+1800
while time.monotonic()<deadline:
 status=json.loads(subprocess.check_output(['oc','get','job',job,'-n',ns,'-o','json'],text=True)).get('status',{})
 if status.get('succeeded',0)>=1:break
 if any(c['type']=='Failed' and c['status']=='True' for c in status.get('conditions',[])):
  log=pathlib.Path(os.environ['STATE_DIR'])/'publication-failed.log'
  with log.open('w') as output:subprocess.run(['oc','logs','job/'+job,'-n',ns],stdout=output,check=False)
  raise SystemExit('Publication failed; inspect '+str(log)+' and the retained Job before retrying.')
 time.sleep(5)
else:raise SystemExit('Publication timed out; inspect the retained Job.')
PY
    oc logs "job/$job" -n "$PUBLISHER_NAMESPACE" > "$STATE_DIR/publication.log"
    if [[ "$job" == publish-qwen-* ]]; then
      python3 - <<'PY'
import json,os,pathlib
p=pathlib.Path(os.environ['STATE_DIR'])
line=next(x for x in (p/'publication.log').read_text().splitlines() if x.startswith('S3_PUBLICATION_VERIFIED '))
receipt=json.loads(line.split(' ',1)[1]);assert receipt['verified'] is True
(p/'publication.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Verified S3 release:',receipt['uri'])
PY
      # The generic ephemeral PVC is owned by this Job's pod.
      oc delete "job/$job" -n "$PUBLISHER_NAMESPACE"
    else
      oc rollout status deployment/encrypted-model -n "$PUBLISHER_NAMESPACE" --timeout=5m
    fi
    ;;
  verify)
    : "${CHAT_CA_FILE:?Set CHAT_CA_FILE to the demo CA certificate}"
    host=$(oc get route qwen-chat -n "$DEMO_NAMESPACE" -o jsonpath='{.spec.host}')
    oc get pods -n "$DEMO_NAMESPACE" -l app.kubernetes.io/name=qwen-confidential -o json > "$STATE_DIR/pods.json"
    python3 - <<'PY'
import json,os,pathlib
pods=json.loads((pathlib.Path(os.environ['STATE_DIR'])/'pods.json').read_text())['items']
pods=[p for p in pods if not p['metadata'].get('deletionTimestamp') and p['status']['phase'] not in ['Failed','Succeeded']]
assert len(pods)==1
p=pods[0]; assert p['spec']['runtimeClassName']=='kata-cc-nvidia-gpu'
assert {'main','chat'} <= {c['name'] for c in p['spec']['containers']}
assert all(c['ready'] for c in p['status']['containerStatuses'])
assert any(c['name']=='storage-initializer' and c['state'].get('terminated',{}).get('exitCode')==0 for c in p['status']['initContainerStatuses'])
print('SAME_CONFIDENTIAL_POD_AND_MODEL_INIT_PASS',p['metadata']['uid'])
PY
    curl --fail --silent --show-error --cacert "$CHAT_CA_FILE" "https://$host/healthz"
    curl --fail --silent --show-error --cacert "$CHAT_CA_FILE" --max-time 120 \
      -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Reply with a short greeting for the confidential AI demonstration."}]}' \
      "https://$host/api/chat" > "$STATE_DIR/chat-response.json"
    python3 -c 'import json,os,pathlib; r=json.loads((pathlib.Path(os.environ["STATE_DIR"])/"chat-response.json").read_text()); text=r["choices"][0]["message"]["content"]; assert text.strip(); print("CHAT_RESPONSE_PASS:",text)'
    printf '\nChat URL: https://%s\n' "$host"
    ;;
  *)
    echo 'Usage: scripts/rhoai-demo.sh {preflight|platform|build|publish|verify}'
    echo 'See docs/rhoai/install.md for key enrollment, measured policy and GitOps ownership.'
    ;;
esac
