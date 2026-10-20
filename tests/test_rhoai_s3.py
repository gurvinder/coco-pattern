"""S3 configuration must preserve measured TLS and separate credential scopes."""
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM", "helm")


class S3Configuration(unittest.TestCase):
    def setUp(self):
        self.values = {
            "guest": {"initdata": "test"},
            "images": {"initializer": "example.invalid/init@sha256:" + "a" * 64},
            "model": {"uri": "s3://models/qwen3-0.6b/release/qwen.tar"},
            "distribution": {"backend": "s3", "s3": {
                "uri": "s3://models/qwen3-0.6b/release/qwen.tar",
                "endpoint": "https://s3.example.invalid",
                "caBundle": "public-ca\n",
            }},
        }

    def render(self, chart, values, success=True):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as file:
            yaml.safe_dump(values, file)
            file.flush()
            result = subprocess.run(
                [HELM, "template", "test", str(ROOT / chart), "-f", file.name],
                text=True, capture_output=True)
        if not success:
            self.assertNotEqual(result.returncode, 0)
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        return [item for item in yaml.safe_load_all(result.stdout) if item]

    def qwen(self, values=None):
        return self.render("charts/coco-supported/rhoai-confidential-qwen", values or self.values)

    def test_s3_credentials_only_reach_initializer(self):
        objects = self.qwen()
        template = next(o["spec"]["template"] for o in objects if o["kind"] == "LLMInferenceServiceConfig")
        for container in template["initContainers"] + template["containers"]:
            mounts = {m["name"]: m for m in container.get("volumeMounts", [])}
            if container["name"] == "storage-initializer":
                self.assertTrue(mounts["model-s3"]["readOnly"])
                env = {e["name"]: e["value"] for e in container["env"]}
                self.assertEqual(env["S3_VERIFY_SSL"], "true")
                self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], "/var/run/model-s3/credentials")
                self.assertTrue(env["AWS_CA_BUNDLE"].startswith("/dev/shm/verified-"))
                self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
                self.assertIn(hashlib.sha256(b"public-ca\n").hexdigest(), "\n".join(container["command"]))
            else:
                self.assertNotIn("model-s3", mounts)
                self.assertNotIn("s3-ca", mounts)
        ca = next(o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"].endswith("-s3-ca"))
        self.assertEqual(ca["data"]["ca.crt"], "public-ca\n")
        external = next(o for o in objects if o["kind"] == "ExternalSecret")
        self.assertEqual(external["spec"]["data"][0]["remoteRef"]["key"], "secret/data/hub/rhoaiS3Reader")

    def test_ca_and_endpoint_change_measured_command_or_environment(self):
        def measured(values):
            objects = self.qwen(values)
            template = next(o["spec"]["template"] for o in objects if o["kind"] == "LLMInferenceServiceConfig")
            return next(c for c in template["initContainers"] if c["name"] == "storage-initializer")
        original = measured(self.values)
        changed = copy.deepcopy(self.values)
        changed["distribution"]["s3"]["caBundle"] = "another-ca\n"
        self.assertNotEqual(original["command"], measured(changed)["command"])
        changed = copy.deepcopy(self.values)
        changed["distribution"]["s3"]["endpoint"] = "https://other.example.invalid"
        self.assertNotEqual(original["env"], measured(changed)["env"])

    def test_tls_downgrade_and_mismatched_release_rejected(self):
        for change in ("endpoint", "uri"):
            values = copy.deepcopy(self.values)
            values["distribution"]["s3"][change] = (
                "http://insecure.example.invalid" if change == "endpoint"
                else "s3://models/qwen3-0.6b/other/qwen.tar")
            self.render("charts/coco-supported/rhoai-confidential-qwen", values, success=False)

    def test_s3_publisher_has_temporary_workspace_and_no_http_server(self):
        objects = self.render("charts/hub/rhoai-model-publisher", self.values)
        self.assertFalse({"Deployment", "Service", "PersistentVolumeClaim"} & {o["kind"] for o in objects})
        job = next(o for o in objects if o["kind"] == "Job")
        self.assertIn("ephemeral", job["spec"]["template"]["spec"]["volumes"][0])
        external = next(o for o in objects if o["kind"] == "ExternalSecret")
        self.assertEqual(external["spec"]["data"][0]["remoteRef"]["key"], "secret/data/hub/rhoaiS3Publisher")

    def test_http_mode_remains_available(self):
        objects = self.render("charts/hub/rhoai-model-publisher", {})
        kinds = {o["kind"] for o in objects}
        self.assertTrue({"Deployment", "Service", "PersistentVolumeClaim"} <= kinds)
        self.assertNotIn("ExternalSecret", kinds)

    def test_odf_uses_stock_operator_objects_and_private_accounts(self):
        objects = self.render("charts/hub/rhoai-object-storage", {})
        storage = next(o for o in objects if o["kind"] == "StorageCluster")
        self.assertEqual(storage["spec"]["multiCloudGateway"]["reconcileStrategy"], "standalone")
        self.assertTrue(storage["spec"]["multiCloudGateway"]["denyHTTP"])
        backing = next(o for o in objects if o["kind"] == "BackingStore")
        resources = backing["spec"]["pvPool"]["resources"]
        self.assertEqual(resources["limits"]["memory"], "2Gi")
        self.assertEqual(resources["requests"]["storage"], "100Gi")
        accounts = [o for o in objects if o["kind"] == "NooBaaAccount"]
        self.assertEqual(len(accounts), 2)
        self.assertTrue(all(not a["spec"]["allow_bucket_creation"] for a in accounts))
        self.assertTrue(all(a["spec"]["default_resource"] == "rhoai-models" for a in accounts))
        job = next(o for o in objects if o["kind"] == "Job")
        env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        for role in ("PUBLISHER_ACCOUNT", "READER_ACCOUNT"):
            self.assertEqual(env[role]["valueFrom"]["secretKeyRef"]["key"], "ARN")
        self.assertTrue(all(o["metadata"]["annotations"]["argocd.argoproj.io/sync-options"].endswith("Prune=false,Delete=false")
                            for o in objects if o["kind"] in ("StorageCluster", "BackingStore", "BucketClass", "ObjectBucketClaim", "NooBaaAccount")))


if __name__ == "__main__":
    unittest.main()
