# Stock CoCo base and the RHOAI extension

This is a GitHub fork of [validatedpatterns/coco-pattern](https://github.com/validatedpatterns/coco-pattern).
The branch starts at upstream `9800bf1f200a0b41545926d56908d524b17c2cb2`, also the
upstream main revision checked on 19 October 2026. The shared framework and
normal installer are retained. The extension does not require the previous
lab repositories at runtime.

The added Helm charts provide RHOAI, encrypted model publication, confidential
Qwen/chat, optional ODF standalone object storage, a stock internal-registry configuration and a Trustee configuration
adapter. Embedded scripts handle one-time trusted preparation. There is one
initializer derivative, with its exact Red Hat base and KServe fix recorded in
`build/storage-initializer`. No custom storage controller or model operator is
introduced.

## Generic configuration

Choose `intel-tdx-gpu` or `amd-snp-gpu` through CoCo's
`global.hardware.profile`. The generic RHOAI overlay and the matching profile
configure the dependencies. `global.rhoai.site` selects one directory through
normal global values loaded by Pattern extraValueFiles. Shared defaults select the empty
`sites/example` scaffold; the workload remains disabled until trusted inputs
are prepared.

A site's `install.yaml`, `values-site.yaml`, `values-qwen.yaml` and
`values-trustee.yaml` contain its public configuration. Generated identity,
hostname, disk choice and platform references are never generic defaults.
`testing/cluster-01` holds an optional test deployment, selected only explicitly.
Private credentials and keys remain outside Git. See [the installation
runbook](install.md) and [architecture](end-to-end.md).
For S3 distribution, `values-distribution.yaml` supplies the public endpoint,
release URI and CA. `global.rhoai.storageProvider: odf` adds the optional ODF
dependency; `external` retains HTTP or uses an existing S3 service. See
[S3/ODF installation](s3.md).

## Changes to stock files

- `values-global.yaml` selects the generic GPU demo scaffold and disables
  blanket approval of manual InstallPlans. The framework still owns installation.
- `values-baremetal.yaml` loads the extension, selected hardware overlay and
  selected site with the ordinary `sharedValueFiles` mechanism.
- The GPU ClusterPolicy supplies CC Manager's operator namespace. The extension
  enables optional kubelet/CRI-O timeout configuration in that chart for large
  confidential image pulls, using normal OpenShift node configuration resources.
- The LVMS chart accepts an optional site-provided device selector.
- The Makefile, README and ignore rules expose commands/docs and exclude private
  state. The server-specific firmware guide is replaced with generic prerequisites.

The Trustee adapter is based on published chart 0.10.2; its provenance and three
modified templates are listed in `charts/hub/rhoai-trustee/UPSTREAM.md`. It configures
the stock Trustee operator, including exact TDX/SNP workload bindings. The OSC
and Trustee versions inherit the current upstream pins, 1.13.1 and 1.2.1.

## Verification

Run `make test-rhoai` with Helm 3 and OPA. Policy cases cover positive and negative
TDX/SNP bindings, mandatory GPU attestation, measured guest restrictions and
site isolation. Render both complete ClusterGroup profiles before deployment.
The actual hardware/install evidence belongs in the selected test site's record.

Upstream currently has no `preview-all` Make target. Its standalone topology
schema invocation omits the global hardware profile; validate the actual merged
configuration as well and record this upstream limitation. The local upstream
CLI test has a Typer help-text spelling mismatch. Do not record those checks as
passing merely because the deployment renders.
