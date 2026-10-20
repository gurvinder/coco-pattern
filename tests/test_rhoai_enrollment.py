"""Exercise real enrollment file handling with a local stub for cluster access."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnrollmentStateTests(unittest.TestCase):
    def test_enrollment_preserves_operation_logs_directory_access_and_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            operation_logs = state / "operation-logs"
            operation_logs.mkdir(parents=True, mode=0o700)
            checkpoint = operation_logs / "run.json"
            checkpoint.write_text('{"stage":"enrollment"}\n')
            checkpoint.chmod(0o644)
            registry = root / "registry.json"
            registry.write_text(json.dumps({"auths": {
                "registry.redhat.io": {"auth": "dGVzdDp0ZXN0"}}}))
            token = root / "vault-token"
            token.write_text("unit-test-token")
            bindir = root / "bin"
            bindir.mkdir()
            oc = bindir / "oc"
            oc.write_text("""#!/usr/bin/env python3
import base64, json, sys
args = sys.argv[1:]
if args[:3] == ["get", "secret", "guest-image-puller-token"]:
    print(json.dumps({"data": {"token": base64.b64encode(b"unit-test-pull-token").decode()}}))
elif args and args[0] == "exec":
    sys.stdin.read()
    if "vault kv get" in args[-1]:
        print("No value found at secret/hub/rhoaiQwen", file=sys.stderr)
        sys.exit(1)
elif args and args[0] == "apply":
    sys.stdin.read()
else:
    print("{}")
""")
            oc.chmod(0o700)
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       STATE_DIR=str(state), REGISTRY_AUTH_FILE=str(registry),
                       VAULT_ADMIN_TOKEN_FILE=str(token), CHAT_HOST="chat.example.test")
            result = subprocess.run(["bash", str(ROOT / "scripts/rhoai-enroll.sh")],
                                    env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(operation_logs.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((state / "model-key.bin").stat().st_mode), 0o600)
            self.assertEqual(json.loads(checkpoint.read_text())["stage"], "enrollment")
            checkpoint.write_text('{"stage":"next"}\n')
            self.assertEqual(json.loads(checkpoint.read_text())["stage"], "next")


if __name__ == "__main__":
    unittest.main()
