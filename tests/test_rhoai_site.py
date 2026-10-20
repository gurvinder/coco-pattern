"""Site isolation and TEE selection are part of the deployment boundary."""
import base64
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class SitePreparation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'fork'
        (self.root / 'scripts').mkdir(parents=True)
        self.site = self.root / 'sites/example'
        self.site.mkdir(parents=True)
        self.state = Path(self.tmp.name) / 'private'
        self.state.mkdir()
        for name in ['rhoai-config.sh', 'rhoai-configure-owner.sh']:
            shutil.copy2(ROOT / 'scripts' / name, self.root / 'scripts')
        shutil.copy2(ROOT / 'values-global.yaml', self.root)
        shutil.copy2(ROOT / 'sites/example/install.yaml', self.site)
        self.env = {**os.environ, 'STATE_DIR': str(self.state), 'COCO_CHECKOUT': str(self.root), 'RHOAI_INSTALL_VALUES': str(self.site / 'install.yaml')}
        self.secret = self.state / 'model-key.json'
        self.secret.write_text('PRIVATE-TEST-CANARY')

    def run_stage(self, stage):
        return subprocess.run([str(self.root / 'scripts/rhoai-configure-owner.sh'), stage], env=self.env, capture_output=True, text=True)

    def apps(self):
        return yaml.safe_load((self.site / 'values-site.yaml').read_text())['clusterGroup']['applications']

    def prepared(self, tee='tdx'):
        raw = b'measured guest'
        initdata = base64.b64encode(gzip.compress(raw)).decode()
        (self.state / 'site.yaml').write_text(yaml.safe_dump({'guest': {'initdata': initdata}}))
        binding = {'tee': tee, 'initData': hashlib.sha256(raw).hexdigest()}
        (self.state / 'trustee-binding.yaml').write_text(yaml.safe_dump({'kbs': {'resourcePolicy': {'confidentialGuestBindings': {'rhoai-qwen-secrets': binding}}}}))

    def test_fresh_site_bootstrap_disables_prepared_workload(self):
        before = (self.root / 'values-global.yaml').read_bytes()
        result = self.run_stage('bootstrap')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.apps()['rhoai-platform']['disabled'])
        self.assertTrue(self.apps()['rhoai-model-publisher']['disabled'])
        self.assertTrue(self.apps()['rhoai-confidential-qwen']['disabled'])
        self.assertEqual(self.secret.read_text(), 'PRIVATE-TEST-CANARY')
        self.assertEqual((self.root / 'values-global.yaml').read_bytes(), before)
        self.assertFalse(any('PRIVATE-TEST-CANARY' in p.read_text() for p in self.site.glob('*.yaml')))

    def test_ready_requires_this_sites_measured_inputs(self):
        self.assertNotEqual(self.run_stage('ready').returncode, 0)
        self.assertFalse((self.site / 'values-qwen.yaml').exists())

    def test_ready_then_bootstrap_preserves_existing_workload(self):
        self.prepared()
        for stage in ['ready', 'bootstrap']:
            result = self.run_stage(stage)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.apps()['rhoai-confidential-qwen']['disabled'])
        self.assertEqual(self.secret.read_text(), 'PRIVATE-TEST-CANARY')

    def test_wrong_tee_binding_rejected(self):
        self.prepared('snp')
        self.assertNotEqual(self.run_stage('ready').returncode, 0)
        self.assertFalse((self.site / 'values-qwen.yaml').exists())

    def test_modified_binding_rejected(self):
        self.prepared()
        p = self.state / 'trustee-binding.yaml'
        p.write_text(p.read_text().replace(hashlib.sha256(b'measured guest').hexdigest(), '0' * 64))
        self.assertNotEqual(self.run_stage('ready').returncode, 0)

    def test_unsupported_profile_rejected(self):
        p = self.site / 'install.yaml'
        p.write_text(p.read_text().replace('intel-tdx-gpu', 'intel-tdx'))
        self.assertNotEqual(self.run_stage('bootstrap').returncode, 0)

    def test_parameter_only_selection_rejected(self):
        p = self.site / 'install.yaml'
        config = yaml.safe_load(p.read_text())
        config.setdefault('main', {})['extraParameters'] = [{'name': 'global.hardware.profile', 'value': 'amd-snp-gpu'}]
        p.write_text(yaml.safe_dump(config))
        self.assertNotEqual(self.run_stage('bootstrap').returncode, 0)

    def test_install_file_must_be_loaded_before_shared_paths(self):
        p = self.site / 'install.yaml'
        config = yaml.safe_load(p.read_text())
        config['global']['extraValueFiles'] = []
        p.write_text(yaml.safe_dump(config))
        self.assertNotEqual(self.run_stage('bootstrap').returncode, 0)

    def test_external_owner_is_rejected(self):
        self.env['COCO_CHECKOUT'] = str(Path(self.tmp.name))
        self.assertNotEqual(self.run_stage('bootstrap').returncode, 0)
        self.assertFalse((self.site / 'values-site.yaml').exists())

if __name__ == '__main__':
    unittest.main()
