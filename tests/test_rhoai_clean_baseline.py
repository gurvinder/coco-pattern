"""A clean-install claim must fail closed on leftovers or incomplete evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "baseline", Path(__file__).parent / "rhoai" / "check_clean_baseline.py"
)
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def clean_inventory():
    return {
        "nodes": [{"metadata": {"name": "node"}, "spec": {}, "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "nodeInfo": {"bootID": "fresh-boot"}}}],
        "machineconfigpools.machineconfiguration.openshift.io": [{
            "metadata": {"name": "master"}, "status": {"conditions": [
                {"type": "Updated", "status": "True"}]}}],
        "clusteroperators.config.openshift.io": [{
            "metadata": {"name": "kube-apiserver"}, "status": {"conditions": [
                {"type": "Available", "status": "True"}]}}],
    }


class CleanBaselineTests(unittest.TestCase):
    def run_gate(self, inventory):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.json"
            with patch.object(baseline, "get",
                              side_effect=lambda r: {"items": inventory.get(r, [])}), \
                    patch("sys.argv", ["check", "--output", str(output)]), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as result:
                baseline.main()
            return result.exception.code, json.loads(output.read_text())

    def test_healthy_empty_cluster_passes(self):
        code, record = self.run_gate(clean_inventory())
        self.assertEqual(code, 0)
        self.assertTrue(record["passed"])

    def test_internal_rhoai_orphan_blocks_clean_claim(self):
        inventory = clean_inventory()
        inventory["customresourcedefinitions"] = [{
            "metadata": {"name": "kserves.components.platform.opendatahub.io"},
            "spec": {"group": "components.platform.opendatahub.io"}}]
        code, record = self.run_gate(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(len(record["checks"]["extensionCRDs"]), 1)

    def test_acm_generic_application_and_provisioning_apis_block_clean_claim(self):
        for name, group in (
            ("applications.app.k8s.io", "app.k8s.io"),
            ("clusters.cluster.x-k8s.io", "cluster.x-k8s.io"),
            ("inferencepools.inference.networking.x-k8s.io",
             "inference.networking.x-k8s.io"),
            ("noobaas.noobaa.io", "noobaa.io"),
            ("clusters.postgresql.cnpg.noobaa.io", "postgresql.cnpg.noobaa.io"),
            ("storageclusters.ocs.openshift.io", "ocs.openshift.io"),
            ("objectbucketclaims.objectbucket.io", "objectbucket.io"),
            ("drivers.csi.ceph.io", "csi.ceph.io"),
            ("recipes.ramendr.openshift.io", "ramendr.openshift.io"),
            ("volumereplications.replication.storage.openshift.io", "replication.storage.openshift.io"),
        ):
            with self.subTest(name=name):
                inventory = clean_inventory()
                inventory["customresourcedefinitions"] = [{
                    "metadata": {"name": name}, "spec": {"group": group}}]
                self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_core_owned_cluster_api_is_preserved(self):
        inventory = clean_inventory()
        inventory["customresourcedefinitions"] = [{
            "metadata": {"name": "ipaddresses.ipam.cluster.x-k8s.io",
                         "ownerReferences": [{
                             "apiVersion": "config.openshift.io/v1",
                             "kind": "ClusterVersion", "name": "version",
                             "controller": True}]},
            "spec": {"group": "ipam.cluster.x-k8s.io"}}]
        self.assertEqual(self.run_gate(inventory)[0], 0)

    def test_volume_or_shared_operator_blocks_clean_claim(self):
        for resource in ("persistentvolumes", "subscriptions.operators.coreos.com"):
            with self.subTest(resource=resource):
                inventory = clean_inventory()
                inventory[resource] = [{"metadata": {"name": "retained"}}]
                self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_empty_health_inventory_is_not_success(self):
        for resource in clean_inventory():
            with self.subTest(resource=resource):
                inventory = clean_inventory()
                inventory[resource] = []
                self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_retained_dependency_permissions_block_clean_claim(self):
        inventory = clean_inventory()
        inventory["clusterroles,clusterrolebindings,securitycontextconstraints"] = [
            {"metadata": {"name": "rhoai-dependency"}}
        ]
        self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_odf_storageclass_and_permissions_block_clean_claim(self):
        for resource, item in (
            ("storageclasses.storage.k8s.io", {
                "metadata": {"name": "openshift-storage.noobaa.io"},
                "provisioner": "openshift-storage.noobaa.io/obc"}),
            ("clusterroles,clusterrolebindings,securitycontextconstraints", {
                "metadata": {"name": "ceph-csi-clientprofiles-editor-role"}}),
        ):
            inventory = clean_inventory()
            inventory[resource] = [item]
            self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_extension_console_entries_block_but_core_plugins_remain(self):
        for namespace, name, expected in (
            ("openshift-storage", "odf-console", 1),
            ("patterns-operator", "patterns-operator-console-plugin", 1),
            ("openshift-monitoring", "monitoring-plugin", 0),
        ):
            with self.subTest(name=name):
                inventory = clean_inventory()
                inventory["consoleplugins.console.openshift.io"] = [{
                    "metadata": {"name": name},
                    "spec": {"backend": {"service": {"namespace": namespace}}}}]
                self.assertEqual(self.run_gate(inventory)[0], expected)
                # An enabled stale extension is also a leftover after CR deletion.
                inventory["consoleplugins.console.openshift.io"] = []
                inventory["consoles.operator.openshift.io"] = [{
                    "metadata": {"name": "cluster"}, "spec": {"plugins": [name]}}]
                self.assertEqual(self.run_gate(inventory)[0], expected)

    def test_old_gpu_readiness_and_runtime_discovery_cannot_satisfy_new_run(self):
        for label in ("nvidia.com/cc.ready.state", "feature.node.kubernetes.io/runtime.kata",
                      "amd.feature.node.kubernetes.io/snp",
                      "intel.feature.node.kubernetes.io/tdx",
                      "ibm.feature.node.kubernetes.io/se"):
            inventory = clean_inventory()
            inventory["nodes"][0]["metadata"]["labels"] = {label: "true"}
            self.assertEqual(self.run_gate(inventory)[0], 1)
        for value, expected in (("1", 1), ("0", 0)):
            inventory = clean_inventory()
            inventory["nodes"][0]["status"]["allocatable"] = {"nvidia.com/pgpu": value}
            self.assertEqual(self.run_gate(inventory)[0], expected)

    def test_stock_tdx_machine_configuration_cannot_survive_clean_reset(self):
        inventory = clean_inventory()
        inventory["machineconfigs.machineconfiguration.openshift.io"] = [{
            "metadata": {"name": "99-enable-coco-master"}}]
        self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_rhoai_ca_injection_in_a_surviving_core_namespace_is_a_leftover(self):
        inventory = clean_inventory()
        inventory["configmaps"] = [{"metadata": {
            "namespace": "openshift-monitoring", "name": "odh-kserve-custom-ca-bundle"}}]
        self.assertEqual(self.run_gate(inventory)[0], 1)
        inventory["configmaps"][0]["metadata"]["name"] = "kube-root-ca.crt"
        self.assertEqual(self.run_gate(inventory)[0], 0)

    def test_generic_binding_to_deleted_extension_namespace_blocks_clean_claim(self):
        inventory = clean_inventory()
        inventory["clusterroles,clusterrolebindings,securitycontextconstraints"] = [{
            "metadata": {"name": "role-tokenreview-binding"},
            "subjects": [{"kind": "ServiceAccount", "namespace": "external-secrets",
                          "name": "ocp-external-secrets"}]}]
        self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_unsettled_node_or_pool_blocks_clean_claim(self):
        inventory = clean_inventory()
        inventory["nodes"][0]["spec"]["unschedulable"] = True
        self.assertEqual(self.run_gate(inventory)[0], 1)
        inventory = clean_inventory()
        inventory["machineconfigpools.machineconfiguration.openshift.io"][0][
            "status"]["conditions"].append({"type": "Updating", "status": "True"})
        self.assertEqual(self.run_gate(inventory)[0], 1)
        inventory = clean_inventory()
        inventory["machineconfigpools.machineconfiguration.openshift.io"][0]["spec"] = {
            "paused": True}
        self.assertEqual(self.run_gate(inventory)[0], 1)

    def test_api_failure_does_not_become_empty_inventory(self):
        with patch.object(baseline.subprocess, "check_output",
                          side_effect=subprocess.CalledProcessError(1, "oc")):
            with self.assertRaises(subprocess.CalledProcessError):
                baseline.get("nodes")
