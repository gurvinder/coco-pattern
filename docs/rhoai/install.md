# Install CoCo and confidential Qwen

This branch extends stock CoCo with Red Hat OpenShift AI confidential-model
loading, encrypted persistence and the Qwen chat application. The same charts
serve both hardware profiles. The only TEE selection is the normal CoCo
`global.hardware.profile` value:

| Selection | Intended hardware | Attestation preparation |
|---|---|---|
| `intel-tdx-gpu` | Intel TDX with NVIDIA H100 | Intel platform registration/QGS, MRTD and RTMR references |
| `amd-snp-gpu` | AMD SEV-SNP with NVIDIA H100 | SNP launch reference and AMD collateral; optional VCEK cache |

Selecting a profile configures infrastructure and key-release rules. It does not
replace firmware setup or prove hardware qualification. The [test-site record](../../testing/cluster-01/README.md)
states which hardware was actually exercised. No testing directory is loaded by
default, and no shared default contains a cluster address, disk identifier or
prepared guest identity.

## Prerequisites and versions

Start with healthy bare-metal OpenShift, compatible firmware, virtualization,
TEE support, IOMMU, GPU passthrough and GPU confidential mode. Follow the stock
CoCo hardware setup and [Red Hat compatibility requirements](https://docs.redhat.com/en/documentation/openshift_sandboxed_containers/1.13/html/deploying_confidential_containers_on_bare-metal_servers/confidential-workload-environment_metal-cc).
Plan for node reboots during runtime and IOMMU configuration. The application
requests one GPU, 8 vCPUs, a 64 GiB guest and a 20 GiB raw block volume with
`ReadWriteOncePod` support. Select a suitable storage class and an unused storage
device if using LVMS. Do not install a competing KServe controller.

The current upstream pins are OSC **1.13.1** and Red Hat build of Trustee
**1.2.1**, confirmed against the stable catalog on 19 October 2026. This extension
inherits those pins; it does not downgrade them in a site overlay. The GPU
operator is pinned at 26.3.0. RHOAI is pinned at 3.6.0-ea.2. Recheck the relevant
catalog and compatibility matrix before deliberately changing pins. New
runtime artifacts require new reference calculation and workload validation.

The RHOAI confidential feature is Early Access / Developer Preview. The
initializer derivative is an unsupported demonstration build. Product operator
versions do not make the complete demo a production-supported architecture.
The optional ODF dependency pins 4.22.6 in standalone MCG mode; its topology,
storage inputs and support boundary are described in [S3/ODF installation](s3.md).

Workstation prerequisites: Git, OpenShift CLI, Helm **3**, Podman, Python 3.11+,
curl, OpenSSL and the repository Python dependencies. Reference calculation
requires Linux extraction tools (`rpm2cpio`, `cpio`, `skopeo`); TDX additionally
requires the stock `tdx-measure` prerequisite. Use a Linux workstation or the
normal pattern utility environment. Provide an administrator kubeconfig and
registry authentication entitled to the pinned Red Hat images. Registry, model,
attestation collateral and NVIDIA verifier endpoints must be reachable.

## Select a site and profile

Fork this repository and clone your fork. Argo CD must read the branch you push.
Copy the empty example into your own site directory:

```bash
git switch rhoai-confidential-qwen
cp -R sites/example sites/my-site
python3 -m pip install -r requirements.txt -r requirements-rhoai.txt
export RHOAI_INSTALL_VALUES=sites/my-site/install.yaml
export STATE_DIR="$PWD/.private/my-site"
export KUBECONFIG=/secure/path/cluster.kubeconfig
export REGISTRY_AUTH_FILE=/secure/path/registry-auth.json
export HELM=helm
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
```

Edit `sites/my-site/install.yaml`. Keep the selector in the file loaded by the
normal Pattern `extraValueFiles` mechanism:

```yaml
global:
  hardware:
    profile: intel-tdx-gpu # or amd-snp-gpu
  rhoai:
    site: sites/my-site
    storageProvider: external # use odf to install the optional object gateway
  extraValueFiles:
  - sites/my-site/install.yaml
```

Choose [HTTP, existing S3 or pattern-installed ODF](s3.md) before bootstrap.
The HTTP mode is the default. S3 credentials and the release URI are enrolled
later, before publishing; selecting ODF here installs its platform dependency.

Set site storage inputs in `values-site.yaml`; for example an LVMS
`lvmCluster.deviceSelector.paths` list. The optional generated `values-qwen.yaml`
and `values-trustee.yaml` belong to this site. Keys and credentials belong in
`STATE_DIR`/Vault, never in these files. For another storage class, configure
`registryStorage.storageClass`, publisher storage and application storage
consistently. Set `STORAGE_CLASS` for the preparation commands.

## Dependencies and GitOps ownership

The standard CoCo installation owns OSC, Trustee, the GPU operator, Vault/ESO,
storage and runtime configuration. The same ClusterGroup installs RHOAI through
`rhoai-platform`. Its hooks approve only the pinned RHOAI InstallPlan, wait for
the operator API, configure DataScienceCluster, then wait for serving readiness.
There is one owner for each Subscription and configuration object. CoCo is the
base pattern, not a separately nested dependency.
The Trustee credential policy selects the local hub, as the reference-value
policy does. It does not depend on ACM assigning `vendor: OpenShift`; a freshly
registered bare-metal hub can have `vendor: Other`.

During bootstrap, Trustee loads only the normal CoCo secrets. Enabling the
prepared Qwen application also enables its Vault resource mapping. This avoids
waiting for model keys before the platform and initializer build are ready.
The extension sets the stock `kbs.workerCount` option to four. This avoids
starting one HTTP worker for every host CPU on large machines and exhausting
the container's open-file limit. A site can tune that ordinary Trustee setting.

The GPU chart also configures a ten-minute kubelet runtime request timeout and
CRI-O container creation timeout for the selected TEE. Large images pulled
inside the guest can exceed the two-minute default. These are ordinary
`KubeletConfig` and `MachineConfig` resources, including a separate CRI-O drop-in
that survives reboot. This uses the settings described in
[Red Hat's GPU timeout procedure](https://docs.redhat.com/en/documentation/openshift_sandboxed_containers/1.13/html/deploying_confidential_containers_on_bare-metal_servers/configure-cc-overview_metal-cc).
The demo applies them to the stock master and worker pools. For custom pools,
set `runtimeTimeouts.pools` in site values to the appropriate `{name, role}`
entries; inspect existing KubeletConfig resources before selecting overlapping
pools. `runtimeTimeouts.seconds` controls both host timeouts. Wait for this node
configuration to complete before starting the workload.
The GPU application enables Argo self-healing so ownership metadata lost during
initial node-controller processing is restored automatically.
CRI-O replaces a runtime table when reading a later drop-in, so the timeout
file includes the complete stock OSC 1.13.1 GPU handler stanza. Review it against
the operator-provided stanza when upgrading OSC; a timeout-only table would
erase required runtime fields.

| Automatic reconciliation | Explicit administrator work |
|---|---|
| CoCo operators and runtime configuration | Firmware/platform setup, storage choice and initial operator plan review |
| RHOAI operator, guarded initial approval, serving controllers | Registry access and building/supplying the derivative image |
| Trustee, application, publisher and Route manifests | Keys, model publication, trusted reference values and measured binding |
| Application restarts and desired-state repair | Browser certificate trust and the final demo walkthrough |

## Ordered installation

1. **Prepare trusted CoCo inputs.** Use stock `make gen-secrets`, signing-key
   caching and the platform collateral workflow. Review `values-secret` and
   set `VALUES_SECRET` to its private path. For connected TDX, provision the
   Intel PCS registration credential as documented by stock CoCo; for offline
   TDX, collect collateral. For SNP offline caching, collect VCEKs through the
   stock scripts and place the public selectors under `kbs.snp.vcekSecrets` in
   your site's `values-site.yaml`.

2. **Calculate GPU references.** Review the release version, VM dimensions and
   exact GPU kernel command line from the trusted Kata release/configuration.
   Save them as `STATE_DIR/reference-inputs.yaml` (format below), then run
   `scripts/rhoai-reference.sh`. This uses stock veritas against release
   artifacts and selects only the confidential GPU initrd. Its explicit command
   line avoids the older calculator's CPU/GPU command-line defaults. It writes
   `firmware-reference-values.json`, `tee-reference.yaml` and provenance. Point
   the normal CoCo `firmwareReferenceValues` secret input at that JSON file.
   Never populate the allowlist from an observed guest quote.

3. **Bootstrap the site.** Run `scripts/rhoai-configure-owner.sh bootstrap`.
   A fresh site's model and chat stay disabled until preparation completes.
   Commit and push the public site files. Install using the standard command:

   ```bash
   export EXTRA_HELM_OPTS="-f $RHOAI_INSTALL_VALUES"
   ./pattern.sh make install
   ```

   The utility loads the selected site's install file before expanding shared
   value-file paths. Do not move these selectors into extraParameters: Patterns
   0.0.81 expands the paths with file values taking precedence. Verify the
   Pattern and root Argo Application contain the requested profile and site
   path. Do not change a root application manually to select a profile.

4. **Approve the initial CoCo plans.** The OSC, Trustee and GPU Subscriptions
   use manual approval. Inspect each proposed InstallPlan and approve only the
   expected complete CSV list for the pinned version. The installer waits for
   application health, so perform these approvals in a second terminal while
   `make install` continues. For example, after
   selecting its actual name and namespace:

   ```bash
   oc get installplan PLAN -n NAMESPACE -o yaml
   oc patch installplan PLAN -n NAMESPACE --type=merge -p '{"spec":{"approved":true}}'
   ```

   RHOAI's bounded hook handles its own pinned plan. Later upgrades remain
   explicit. When ODF is selected, **defer its approval until CoCo is ready**.
   First wait for the `baremetal`, `sandbox` and `nvidia-gpu` applications to be
   Synced/Healthy and for `scripts/rhoai-demo.sh preflight` to pass. This check
   does not require ODF. Then review and approve the pinned
   `odf-operator.v4.22.6-rhodf` plan and wait for the object-storage application
   and policy Job as described in the S3 runbook. Starting ODF during runtime
   reboots can race its webhook certificate setup and leave its dependency
   InstallPlan in terminal `Failed`, even after the main ODF CSV recovers.
   A failed dependency plan is an installation failure; do not treat Healthy
   Argo applications alone as success or silently repair a recorded attempt.
   Wait for runtime/node changes, Vault unseal and secret loading,
   GPU capacity and all platform applications to become healthy. Run
   `scripts/rhoai-demo.sh preflight` and `scripts/rhoai-demo.sh platform`.
   Argo health can briefly reflect pre-reboot state after the API returns;
   preflight also requires a ready, schedulable GPU node with its machine
   configuration complete, plus available Trustee and admission controllers.
   If the node check fails during recovery, wait and rerun it before proceeding.

5. **Build the initializer.** Run `scripts/rhoai-demo.sh build`. The standard
   OpenShift build uses [the pinned Dockerfile and provenance](../../build/storage-initializer/README.md)
   to replace one decryptor module with merged KServe PR 6219. The immutable
   result is saved in `STATE_DIR/initializer-image`. This fixes full-file JWE
   memory consumption; it does not change Red Hat's published support limits.

6. **Enroll keys.** Optionally set `CHAT_HOST`; otherwise the Route hostname
   derives from the cluster ingress domain. Run `scripts/rhoai-enroll.sh` to
   create model/LUKS keys and a demo CA, and enroll them with the normal Vault
   owner. It also enrolls a namespace-scoped internal-registry pull credential.
   Reruns preserve keys and reject an accidental replacement of existing Vault
   encryption keys. Retain the state directory for the life of the volume.
   The helper explicitly sets CA constraints, key usage and key identifiers,
   then verifies the chain with strict X.509 server-certificate checks. It does
   not rely on the workstation's OpenSSL configuration.

7. **Publish and measure the workload.** Set
   up [S3 distribution and optional ODF](s3.md) first if selected; HTTP remains
   the default. For ODF, select the dependency before bootstrap and approve its
   pinned plan in step 4. Then set
   `MODEL_KEY_FILE="$STATE_DIR/model-key.json"` and run
   `scripts/rhoai-demo.sh publish`. The trusted preparation job downloads the
   pinned Qwen revision, checks its inventory and serves only JWE ciphertext.
   For site-specific inference or storage choices, create
   `STATE_DIR/site-overrides.yaml` now. Run `scripts/rhoai-prepare.sh`; it checks
   the selected TEE references against the CoCo reference store and generates
   the exact guest policy, initdata and key binding.

8. **Activate GitOps.** Run `scripts/rhoai-configure-owner.sh ready`, commit and
   push the site files. Wait for Trustee references/key resources and both
   model applications to converge. When replacing an existing identity, restart
   Trustee after its configuration has reconciled so its new RVPS is loaded.
   The initializer must complete, and inference and chat must share one ready
   `kata-cc-nvidia-gpu` pod.

9. **Verify the demo.** Set `CHAT_CA_FILE="$STATE_DIR/chat-ca.crt"` and run
   `scripts/rhoai-demo.sh verify`. It checks the confidential pod and sends a
   real certificate-verified HTTPS chat request. Open the reported URL, trust
   the demo CA (or use an organization-issued certificate), and send a browser
   message. Replace the entire pod and repeat chat to verify encrypted-volume
   reuse. Run the guest-denial and streaming regression scripts in
   `tests/rhoai` for the acceptance record.

### Renew chat certificates and reload Trustee resources

To renew the demo certificates, back up `chat-ca.crt` and `chat.crt`, remove only
those two public certificate files from `STATE_DIR`, and rerun
`scripts/rhoai-enroll.sh`. Existing CA/TLS private keys and model/LUKS keys are
preserved. Confirm that the `tls-cert` field of the `rhoai-qwen-secrets` Secret
in `trustee-operator-system` has the same SHA-256 certificate fingerprint as
`STATE_DIR/chat.crt` after External Secrets reconciliation. Restart Trustee and
wait for it to become ready: its `secret-converter` init container copies the
resources into its memory-backed repository at startup; updating the Secret
alone does not refresh that copy.

```sh
oc -n trustee-operator-system delete pod -l app=kbs
oc -n trustee-operator-system wait --for=condition=Ready pod -l app=kbs --timeout=180s
```

The operator owns its Deployment and can revert a rollout-restart annotation;
replace its pod and verify a new pod UID instead.

Then replace the Qwen pod so its HTTPS process fetches the reissued certificate.
Verify that the certificate presented at the Route has the expected fingerprint,
repeat verification and give the browser user the current `chat-ca.crt`.
Apply the same Trustee reload ordering when explicitly rotating other resources
served from that repository. Encryption-key rotation additionally requires a
planned model/disk migration; certificate renewal preserves those keys.

## Reference input format

Use values computed/reviewed for your release and runtime, not literal
placeholders. `vcpus` and `memoryMiB` must match the eventual workload.

```yaml
tee: tdx # snp for amd-snp-gpu
ocpVersion: YOUR_EXACT_OCP_RELEASE
vcpus: 8
memoryMiB: 65536
kernelCommandLine: YOUR_REVIEWED_GPU_KERNEL_COMMAND_LINE_WITH_nr_cpus=8
xfam: YOUR_REVIEWED_TDX_XFAM # TDX only
```

For SNP, omit `xfam` and supply all four `platformReferences` arrays:
`snp_bootloader`, `snp_tee_svn`, `snp_snp_svn` and `snp_microcode`. Each contains
the approved integer SVN values from independently verified AMD collateral
and the platform firmware inventory. These hardware TCB values cannot be
calculated from OpenShift images alone. The helper rejects missing arrays.
The [test reference input](../../testing/cluster-01/reference-inputs.yaml)
illustrates the format; its values are specific to that test host.

Review the GPU kernel command line against the trusted Kata release's defaults
and GPU configuration, including `nr_cpus`, before calculating references.
Changing the runtime, kernel parameters, guest size or approved platform firmware
requires reviewing these inputs and regenerating the reference file.

The result for SNP binds `tee`, `launchMeasurement` and `initData`. The TDX
binding contains `tee`, `mrTd`, `rtmr1`, `rtmr2` and `initData`. Both require
Affirming CPU/GPU appraisals, disabled guest/GPU debug, GPU secure boot and
successful GPU measurements. SNP additionally forbids migration. TDX requires
all three exact firmware/runtime digests. Missing or cross-TEE claims fail
closed. Runtime, image, command, environment or namespace changes require
regenerating the policy and binding.

## Reset and validation boundaries

The normal `./pattern.sh make uninstall` removes the pattern and its child
applications. It intentionally leaves the shared Patterns/GitOps operators.
Persistent data and some operator-managed resources can survive uninstall;
inspect them before calling the next run a clean installation. For a disposable
rehearsal, remove retained demo namespaces/volumes only after their workloads
and dependent custom resources have terminated. Remove custom resources while
their controllers still exist; then remove leftover CSVs/Subscriptions. Record
any stuck cleanup and its remedy. Do not generalize a forced-finalizer workaround
into a normal installation step.
The optional ODF chart deliberately retains its storage cluster, bucket,
backing store and accounts across Argo deletion. A full reset must explicitly
remove those resources and their data while the ODF controllers are present,
then remove the ODF operators and APIs. Ordinary upgrades must retain them.
Keep LVMS node controllers until every retained block volume has been reclaimed;
an absent PVC alone does not prove that its host LV or device metadata is gone.
Do not strip storage finalizers to make the baseline appear clean. If a controller
was removed too early, audit ownership, mounts and the exact dedicated device,
resolve that specific orphan, and record the repair before running the gate.

For a full pattern/operator rehearsal, also remove the shared Patterns/GitOps
operators, retained Vault and registry storage, extension namespaces and CRDs,
and the pattern's host configuration. Keep the existing OpenShift installation,
its core controllers and the site's prerequisite host networking/IOMMU settings.
After teardown and node recovery, run the read-only baseline gate:

```bash
python3 tests/rhoai/check_clean_baseline.py --output "$STATE_DIR/clean-baseline.json"
```

It refuses a baseline with leftover operators, serving/runtime and legacy ACM
provisioning APIs, extension permissions, persistent volumes, pattern namespaces
or host settings, retained extension console plugins, RHOAI-injected CA ConfigMaps
in surviving namespaces, paused machine-configuration pools, or unhealthy
nodes/core operators.
Old NFD/NVIDIA discovery/readiness labels must also be cleared after those
controllers stop, so fresh hardware discovery is exercised. Core node-role,
network and prerequisite host settings remain in place.
Also inspect the dedicated storage device and confirm no old confidential VM
or Kata runtime remains on the host. Use a fresh private state directory for
the new run. This is a destructive rehearsal on a disposable cluster; it is
not a prerequisite for installing on an already empty OpenShift cluster.

Stop reconciliation before removing its resources. Disabling Argo automated
sync does not cancel an operation already in progress; inspect and terminate
the root application's active operation as well. Scaling the Patterns
operator Deployment to zero is not a durable stop under OLM. For this complete
operator reset, remove its exact Subscription and primary CSV after inventorying
the owned applications, but retain the Argo controller until child pruning
finishes. Scope removals to the inventoried pattern resources.

For ACM hub teardown, set the owning `MultiClusterHub`'s
`spec.disableHubSelfManagement: true` before removing its `local-cluster`
registration. A change only to the child `MultiClusterEngine` can be overwritten
by the hub. Keep the ACM controllers and conversion webhooks until their custom
resources have finished cleanup.

For RHOAI 3.6 EA2, checking only `DataScienceCluster` and `DSCInitialization`
is insufficient. Also inspect internal `Platform` (`config.opendatahub.io`),
`KServe`/`Kueue` (`components.platform.opendatahub.io`), platform service
resources (`services.platform.opendatahub.io`), and all
`LLMInferenceServiceConfig` templates, including the controller's system templates.
An already-deleting internal resource is
still present and can block the next installation. Let its responsible
controller finish while that controller exists. If cleanup is stuck, record
and resolve the specific condition before declaring the reset complete.

The test record must distinguish a fresh pattern/operator installation on an
existing OpenShift cluster, an OpenShift rebuild, a fresh model volume, a VM
restart and a configuration migration. Hardware qualification requires real
runs on each TEE/GPU combination; rendering and policy tests alone do not
establish H100 or TDX runtime qualification.
