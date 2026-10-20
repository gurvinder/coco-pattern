#!/usr/bin/env python3
"""Read-only gate for a full pattern install on an empty OpenShift cluster."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess


def get(resource):
    return json.loads(subprocess.check_output(
        ["oc", "get", resource, "-A", "-o", "json", "--request-timeout=30s"],
        text=True,
    ))


def names(objects):
    return [
        "/".join(filter(None, (x["metadata"].get("namespace"), x["metadata"]["name"])))
        for x in objects
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = {}
    operators = get("clusteroperators.config.openshift.io")["items"]

    # A full rehearsal includes the framework operators, not just the workload.
    for resource in ("subscriptions.operators.coreos.com", "persistentvolumeclaims",
                     "persistentvolumes", "kubeletconfigs.machineconfiguration.openshift.io"):
        checks[resource] = names(get(resource)["items"])
    checks["nonPlatformCSVs"] = names([
        x for x in get("clusterserviceversions.operators.coreos.com")["items"]
        if x["metadata"]["name"] != "packageserver"
    ])
    crds = get("customresourcedefinitions")["items"]
    extension_group = re.compile(
        r"(?:.*argoproj\.io|.*hybrid-cloud-patterns\.io|"
        r".*opendatahub\.io|serving\.kserve\.io|.*llm-d\.ai|"
        r".*inference.*\.(?:x-)?k8s\.io|.*confidentialcontainers\.org|"
        r"kataconfiguration\.openshift\.io|nvidia\.com|"
        r".*nfd.*|.*topolvm\.io|.*open-cluster-management\.io|"
        r"multicluster\.openshift\.io|.*kubevirt\.io|"
        r".*external-secrets\.io|.*cert-manager\.io|.*kyverno\.io|"
        r".*hive.*\.openshift\.io|.*hypershift\.openshift\.io|"
        r"core\.observatorium\.io|.*istio\.io|submariner\.io|"
        r".*intel\.com|wgpolicyk8s\.io|"
        r".*noobaa\.io|objectbucket\.io|.*ocs\.openshift\.io|"
        r".*odf\.openshift\.io|ceph\.rook\.io|csi\.ceph\.io|"
        r"csiaddons\.openshift\.io|ramendr\.openshift\.io|"
        r"replication\.storage\.openshift\.io|groupsnapshot\.storage\.openshift\.io)"
    )
    checks["extensionCRDs"] = names([
        x for x in crds if extension_group.fullmatch(x["spec"]["group"])
        or x["metadata"]["name"] in {
            "certmanagers.operator.openshift.io", "istiocsrs.operator.openshift.io",
            "trustmanagers.operator.openshift.io",
            "externalsecretsconfigs.operator.openshift.io",
            "externalsecretsmanagers.operator.openshift.io",
            "gitopsservices.pipelines.openshift.io",
            "applications.app.k8s.io",
        }
    ])
    # ACM can leave provisioning APIs after its component is disabled. Some
    # IPAM/Metal3 APIs belong to the OpenShift release; their owner proves that
    # they must be retained even though their group ends in cluster.x-k8s.io.
    def release_owned(crd):
        return any(
            owner.get("apiVersion") == "config.openshift.io/v1"
            and owner.get("kind") == "ClusterVersion"
            and owner.get("controller") is True
            for owner in crd["metadata"].get("ownerReferences", [])
        )

    checks["legacyProvisionerCRDs"] = names([
        x for x in crds
        if not release_owned(x) and (
            x["spec"]["group"].endswith(("agent-install.openshift.io", "cluster.x-k8s.io"))
            or x["spec"]["group"] == "openstack.k-orc.cloud")
    ])
    checks["confidentialRuntimeClasses"] = names([
        x for x in get("runtimeclasses.node.k8s.io")["items"]
        if x["metadata"]["name"].startswith(("kata", "nvidia"))
    ])
    checks["patternMachineConfigs"] = names([
        x for x in get("machineconfigs.machineconfiguration.openshift.io")["items"]
        if x["metadata"]["name"] == "50-enable-sandboxed-containers-extension"
        or x["metadata"]["name"].startswith(("99-coco-", "99-gpu-", "99-enable-coco-"))
    ])
    extension_namespaces = {
        "assisted-installer", "baremetal", "cert-manager", "cert-manager-operator",
        "default-broker", "hive", "hypershift", "local-cluster", "external-secrets",
        "external-secrets-operator", "gpu-workload", "hello-openshift",
        "imperative", "intel-dcap", "intel-dcap-operator-system", "kbs-access",
        "kserve", "kubevirt-vms", "kyverno", "multicluster-engine",
        "nvidia-gpu-operator", "openshift-cnv", "openshift-gitops",
        "openshift-gitops-operator", "openshift-nfd",
        "openshift-sandboxed-containers-operator", "openshift-storage",
        "patterns-operator", "rhoai-confidential-qwen", "rhoai-model-publisher",
        "trustee-operator-system", "vault", "vp-gitops",
    }
    def extension_namespace(name):
        return name in extension_namespaces or name.startswith(
            ("redhat-ods-", "open-cluster-management"))

    checks["extensionNamespaces"] = names([
        x for x in get("namespaces")["items"]
        if extension_namespace(x["metadata"]["name"])
    ])
    for resource in ("validatingwebhookconfigurations", "mutatingwebhookconfigurations"):
        checks[resource] = names([
            x for x in get(resource)["items"]
            if any(extension_namespace(w.get("clientConfig", {}).get(
                "service", {}).get("namespace", "")) for w in x.get("webhooks", []))
        ])
    checks["extensionAPIServices"] = names([
        x for x in get("apiservices.apiregistration.k8s.io")["items"]
        if extension_namespace(x["spec"].get("service", {}).get("namespace", ""))
    ])
    console_plugins = [
        x for x in get("consoleplugins.console.openshift.io")["items"]
        if extension_namespace(x["spec"].get("backend", {}).get(
            "service", {}).get("namespace", ""))
    ]
    checks["extensionConsolePlugins"] = names(console_plugins)
    # Also catch enabled names after their backing ConsolePlugin was deleted.
    plugin_names = {x["metadata"]["name"] for x in console_plugins} | {
        "patterns-operator-console-plugin", "gitops-plugin", "odf-console",
    }
    checks["enabledExtensionConsolePlugins"] = sorted({
        name for console in get("consoles.operator.openshift.io")["items"]
        for name in console["spec"].get("plugins", []) if name in plugin_names
    })
    checks["rhoaiInjectedConfigMaps"] = names([
        x for x in get("configmaps")["items"]
        if x["metadata"]["name"] in {
            "odh-kserve-custom-ca-bundle", "odh-trusted-ca-bundle",
        }
    ])
    checks["patternStorageClasses"] = names([
        x for x in get("storageclasses.storage.k8s.io")["items"]
        if any(token in x.get("provisioner", "") for token in ("topolvm", "noobaa", "ceph"))
    ])
    extension_name = re.compile(
        r"coco|rhoai|rhods|kserve|kbs|trustee|kyverno|nvidia|lvms|topolvm|"
        r"patterns-|gitops|cert-manager|external-secrets|multicluster|"
        r"open-cluster|hypershift|hive|kubevirt|nfd|intel-dcap|kata-|"
        r"klusterlet|imperative|vault-|assisted-installer|storageclass-default-patcher|"
        r"noobaa|cnpg|ceph|rook|(?:^|[-.])odf|(?:^|[-.])ocs|recipe|csi-addons|"
        r"objectbucket|ramendr|replication\.storage|groupsnapshot\.storage",
        re.IGNORECASE,
    )
    checks["extensionPermissions"] = names([
        x for x in get("clusterroles,clusterrolebindings,securitycontextconstraints")["items"]
        if (extension_name.search(x["metadata"]["name"])
            or any(extension_namespace(subject.get("namespace", ""))
                   for subject in x.get("subjects", [])))
        and x["metadata"].get("labels", {}).get("kubernetes.io/bootstrapping")
        != "rbac-defaults"
    ])
    nodes = get("nodes")["items"]
    checks["staleHardwareDiscoveryLabels"] = [
        x["metadata"]["name"] + "/" + label for x in nodes
        for label in x["metadata"].get("labels", {})
        if label.startswith(("feature.node.kubernetes.io/", "nvidia.com/",
                             "nfd.node.kubernetes.io/", "amd.feature.node.kubernetes.io/",
                             "intel.feature.node.kubernetes.io/", "ibm.feature.node.kubernetes.io/"))
    ]
    checks["activeGPUAllocations"] = names([
        x for x in nodes
        if any(int(value) > 0 for name, value in x["status"].get("allocatable", {}).items()
               if name.startswith("nvidia.com/"))
    ])
    checks["unreadyNodes"] = names([
        x for x in nodes
        if not any(c["type"] == "Ready" and c["status"] == "True"
                   for c in x["status"].get("conditions", []))
        or x["spec"].get("unschedulable", False)
    ])
    pools = get("machineconfigpools.machineconfiguration.openshift.io")["items"]
    checks["unsettledMachineConfigPools"] = names([
        x for x in pools
        if x.get("spec", {}).get("paused", False)
        or not any(c["type"] == "Updated" and c["status"] == "True"
                   for c in x["status"].get("conditions", []))
        or any(c["type"] in ("Updating", "Degraded") and c["status"] == "True"
               for c in x["status"].get("conditions", []))
    ])
    checks["unhealthyClusterOperators"] = names([
        x for x in operators
        if not any(c["type"] == "Available" and c["status"] == "True"
                   for c in x["status"].get("conditions", []))
        or any(c["type"] in ("Degraded", "Progressing") and c["status"] == "True"
               for c in x["status"].get("conditions", []))
    ])
    result = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Full pattern/operator reset on existing OpenShift; not an OpenShift rebuild",
        "passed": bool(nodes and pools and operators) and not any(checks.values()),
        "checks": checks,
        "nodes": [{"name": x["metadata"]["name"],
                   "bootID": x["status"]["nodeInfo"]["bootID"]} for x in nodes],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
