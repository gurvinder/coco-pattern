"""Both CoCo selectors must render exact, mutually exclusive guest bindings."""
import json
import base64
import tomllib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get('HELM', 'helm')

class Profiles(unittest.TestCase):
    def test_registry_credential_reaches_fresh_local_hub_only(self):
        rendered = subprocess.check_output([
            HELM, 'template', 'trustee', str(ROOT / 'charts/hub/rhoai-trustee'),
            '-f', str(ROOT / 'values-global.yaml'),
            '--set', 'global.coco.secured=true',
            '--set', 'global.clusterPlatform=None'], text=True)
        rule = next(o for o in yaml.safe_load_all(rendered) if o and
                    o['kind'] == 'PlacementRule' and
                    o['metadata']['name'] == 'pull-secret-credential-placement-rule')
        selector = rule['spec']['clusterSelector']
        def matches(labels):
            return (all(labels.get(k) == v for k, v in selector.get('matchLabels', {}).items())
                    and all(e['operator'] == 'In' and labels.get(e['key']) in e['values']
                            for e in selector.get('matchExpressions', [])))
        for vendor in ('Other', 'OpenShift'):
            self.assertTrue(matches({'local-cluster': 'true', 'vendor': vendor}))
            self.assertFalse(matches({'local-cluster': 'false', 'vendor': vendor}))
        self.assertFalse(matches({'vendor': 'OpenShift'}))

    def test_gpu_timeouts_preserve_the_selected_stock_runtime(self):
        for profile, tee in [('intel-tdx-gpu', 'tdx'), ('amd-snp-gpu', 'snp')]:
            with self.subTest(profile=profile):
                rendered = subprocess.check_output([HELM, 'template', 'gpu', str(ROOT / 'charts/all/nvidia-gpu'), '-f', str(ROOT / 'values-global.yaml'), '-f', str(ROOT / 'overrides/values-rhoai.yaml'), '--set', 'global.hardware.profile=' + profile], text=True)
                objects = [x for x in yaml.safe_load_all(rendered) if x]
                kubelets = [x for x in objects if x['kind'] == 'KubeletConfig']
                self.assertEqual(len(kubelets), 2)
                self.assertTrue(all(x['spec']['kubeletConfig']['runtimeRequestTimeout'] == '600s' for x in kubelets))
                configs = [x for x in objects if x['kind'] == 'MachineConfig' and 'timeout' in x['metadata']['name']]
                self.assertEqual(len(configs), 2)
                for config in configs:
                    source = config['spec']['config']['storage']['files'][0]['contents']['source']
                    handlers = tomllib.loads(base64.b64decode(source.split(',')[1]).decode())['crio']['runtime']['runtimes']
                    name = 'kata-' + tee + '-nvidia-gpu'
                    self.assertEqual(set(handlers), {name})
                    handler = handlers[name]
                    self.assertEqual(handler['runtime_path'], '/usr/bin/containerd-shim-kata-v2')
                    self.assertEqual(handler['runtime_type'], 'vm')
                    self.assertEqual(handler['runtime_config_path'], '/etc/kata-containers/' + name + '/configuration.toml')
                    self.assertTrue(handler['runtime_pull_image'])
                    self.assertTrue(handler['privileged_without_host_devices'])
                    self.assertIn('io.kubernetes.cri-o.Devices', handler['allowed_annotations'])
                    self.assertEqual(handler['container_create_timeout'], 600)

    def test_operator_expands_shared_paths_from_selected_install_file(self):
        # Patterns 0.0.81 gives file values precedence during path expansion.
        # The selector must therefore be in extraValueFiles, not only --set.
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory)
            (chart / 'templates').mkdir()
            (chart / 'Chart.yaml').write_text('apiVersion: v2\nname: selection\nversion: 0.1.0\n')
            (chart / 'templates/selection.yaml').write_text('apiVersion: v1\nkind: ConfigMap\nmetadata: {name: selection}\ndata:\n  files: {{ tpl (toJson .Values.clusterGroup.sharedValueFiles) . | quote }}\n')
            for site, profile in [('sites/example', 'intel-tdx-gpu'), ('testing/cluster-01', 'amd-snp-gpu')]:
                install = ROOT / site / 'install.yaml'
                config = yaml.safe_load(install.read_text())
                self.assertEqual(config['global']['extraValueFiles'], [f'{site}/install.yaml'])
                result = subprocess.check_output([HELM, 'template', 'selection', str(chart), '-f', str(ROOT / 'values-global.yaml'), '-f', str(ROOT / 'values-baremetal.yaml'), '-f', str(install), '--set', 'global.clusterPlatform=None'], text=True)
                files = json.loads(yaml.safe_load(result)['data']['files'])
                self.assertIn(f'/overrides/values-hw-{profile}.yaml', files)
                self.assertIn(f'/overrides/values-rhoai-{profile}.yaml', files)
                self.assertIn(f'/{site}/values-site.yaml', files)
                self.assertIn(f'/{site}/install.yaml', files)

    def test_profile_services_and_keys_follow_the_same_choice(self):
        for profile, tee in [('intel-tdx-gpu', 'tdx'), ('amd-snp-gpu', 'snp')]:
            with self.subTest(profile=profile):
                config = yaml.safe_load((ROOT / 'overrides' / f'values-rhoai-{profile}.yaml').read_text())['clusterGroup']
                params = {x['name']: x['value'] for x in config['applications']['trustee']['overrides']}
                self.assertEqual(params['kbs.tdx.enabled'], str(tee == 'tdx').lower())
                self.assertEqual(params['kbs.snp.enabled'], str(tee == 'snp').lower())
                self.assertEqual(config['applications']['baremetal']['overrides'][0]['value'], str(tee == 'tdx').lower())
                self.assertEqual(config.get('subscriptions', {}).get('intel-tdx-dcap', {}).get('disabled', False), tee == 'snp')

    def test_shared_defaults_do_not_activate_test_site(self):
        global_values = yaml.safe_load((ROOT / 'values-global.yaml').read_text())
        self.assertEqual(global_values['global']['rhoai']['site'], 'sites/example')
        apps = yaml.safe_load((ROOT / 'overrides/values-rhoai.yaml').read_text())['clusterGroup']['applications']
        for name in ['rhoai-confidential-qwen', 'rhoai-model-publisher']:
            self.assertTrue(apps[name]['disabled'])
        for path in [ROOT / 'values-global.yaml', ROOT / 'values-baremetal.yaml', *list((ROOT / 'overrides').glob('values-rhoai*.yaml'))]:
            text = path.read_text()
            self.assertNotIn('testing/', text)
            self.assertNotRegex(text, r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        self.assertFalse(yaml.safe_load((ROOT / 'overrides/values-rhoai-qwen-trustee.yaml').read_text())['kbs']['resourcePolicy']['confidentialGuestBindings'])

    def render_binding(self, binding):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as f:
            yaml.safe_dump({'kbs': {'resourcePolicy': {'confidentialGuestBindings': {'rhoai-qwen-secrets': binding}}}}, f)
            f.flush()
            return subprocess.run([HELM, 'template', 'trustee', str(ROOT / 'charts/hub/rhoai-trustee'), '-f', str(ROOT / 'values-global.yaml'), '-f', f.name], capture_output=True, text=True)

    def test_both_tee_bindings_render(self):
        for binding in [dict(tee='snp', initData='a' * 64, launchMeasurement='b' * 96), dict(tee='tdx', initData='a' * 64, mrTd='b' * 96, rtmr1='c' * 96, rtmr2='d' * 96)]:
            result = self.render_binding(binding)
            self.assertEqual(result.returncode, 0, result.stderr)
            configs = [o for o in yaml.safe_load_all(result.stdout) if o and o.get('kind') == 'ConfigMap']
            policy = next(o['data']['resource-policy.rego'] for o in configs if o['metadata']['name'] == 'resource-policy')
            self.assertIn('"tee": "' + binding['tee'] + '"', policy)

    def test_incomplete_or_ambiguous_bindings_rejected(self):
        for binding in [dict(tee='tdx', initData='a' * 64, mrTd='b' * 96), dict(tee='snp', initData='a' * 64, launchMeasurement='b' * 96, mrTd='c' * 96), dict(initData='a' * 64, launchMeasurement='b' * 96)]:
            self.assertNotEqual(self.render_binding(binding).returncode, 0)

if __name__ == '__main__':
    unittest.main()
