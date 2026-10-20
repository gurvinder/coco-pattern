# Optional test installation: cluster-01

This directory contains the public configuration for the tested deployment.
It is never loaded by generic defaults. The host runs OpenShift 4.22.15,
AMD SEV-SNP and NVIDIA RTX PRO 6000 Blackwell Server Edition GPUs. It is a
development test target, not an H100 or Intel TDX qualification result.

## Install using the generic procedure

Follow the [installation runbook](../../docs/rhoai/install.md), selecting this
site instead of copying the example:

```bash
export RHOAI_INSTALL_VALUES=testing/cluster-01/install.yaml
export STATE_DIR="$PWD/.private/cluster-01"
export KUBECONFIG=/secure/path/cluster.kubeconfig
export REGISTRY_AUTH_FILE=/secure/path/registry-auth.json
export CHAT_HOST=qwen.10.14.202.14.sslip.io
```

The committed Qwen/Trustee values describe the tested identity. A new installation
must generate its own keys, derivative image, reference values and measured
binding using the runbook; it must not reuse these public identities as proof
that a different guest is trusted. Retain private state for an existing encrypted
volume. Browser users must trust their installation's CA or personally accept
its certificate warning.

| File | Purpose |
|---|---|
| `install.yaml` | Selects `amd-snp-gpu` and this directory through Pattern `extraValueFiles` |
| `values-site.yaml` | Test disk selection, cached VCEK selector and application activation |
| `reference-inputs.yaml` | Exact release, guest dimensions, reviewed GPU kernel command line and approved platform TCB references |
| `workload-overrides.yaml` | Input for this GPU's attention backend and the fresh S3 test volume |
| `values-distribution.yaml` | Generated ODF S3 release URI, endpoint and public service CA; credentials stay in Vault |
| `values-qwen.yaml` | Generated public workload settings, image digest and measured initdata; includes this GPU's `TRITON_ATTN` backend |
| `values-trustee.yaml` | Generated exact workload/TEE key-release binding |
| [acceptance.json](acceptance.json) | Recorded clean-baseline ODF installation evidence and separate prior security checks |

IOMMU was configured before this pattern installation. Generic H100 profiles use
the inference runtime's default attention backend. Keys, registry credentials,
kubeconfig and Vault recovery material remain outside Git.

Before the runbook's **Publish and measure the workload** step, copy this
test host's input so that fresh preparation retains the required backend:

```bash
cp testing/cluster-01/workload-overrides.yaml "$STATE_DIR/site-overrides.yaml"
```

### macOS utility-container setup

This workstation's Podman machine could not read the macOS Documents directory,
and its default `keep-id` mapping failed. The rehearsal uses a checkout and
private inputs under `/private/tmp`, with an explicit bind mount and per-command
user-namespace override. These are workstation settings; the stock `pattern.sh`
wrapper is unchanged. Use paths without spaces because the wrapper splits
`EXTRA_ARGS` on whitespace.

```bash
git clone --branch rhoai-confidential-qwen https://github.com/pmatouse/coco-pattern.git \
  /private/tmp/coco-rehearsal
cd /private/tmp/coco-rehearsal
export REHEARSAL_PRIVATE=/private/tmp/coco-rehearsal-private
mkdir -p "$REHEARSAL_PRIVATE/rhoai"
chmod 700 "$REHEARSAL_PRIVATE" "$REHEARSAL_PRIVATE/rhoai"
# Copy the administrator kubeconfig, registry authentication and reviewed CoCo
# secret inputs here. Update paths in values-secret.yaml to this private directory.
export KUBECONFIG="$REHEARSAL_PRIVATE/kubeconfig"
export REGISTRY_AUTH_FILE="$REHEARSAL_PRIVATE/registry-auth.json"
export VALUES_SECRET="$REHEARSAL_PRIVATE/values-secret.yaml"
export STATE_DIR="$REHEARSAL_PRIVATE/rhoai"
export RHOAI_INSTALL_VALUES=testing/cluster-01/install.yaml
export EXTRA_HELM_OPTS="-f $RHOAI_INSTALL_VALUES"
export EXTRA_ARGS="--userns=host --user=0:0 -v $REHEARSAL_PRIVATE:$REHEARSAL_PRIVATE -e KUBECONFIG=$KUBECONFIG"
```

The wrapper checks that the host `KUBECONFIG` is under the home directory.
For these explicitly mounted temporary paths, use
`env -u KUBECONFIG ./pattern.sh make install`; `EXTRA_ARGS` passes the correct
path to the utility container. Keep `KUBECONFIG` set for local `oc` and helpers.

The utility image needs the reference extractor's dependencies. Run the
runbook's reference calculation in an isolated environment inside that image:

```bash
cp testing/cluster-01/reference-inputs.yaml "$STATE_DIR/reference-inputs.yaml"
env -u KUBECONFIG ./pattern.sh \
  env STATE_DIR="$STATE_DIR" REGISTRY_AUTH_FILE="$REGISTRY_AUTH_FILE" \
  RHOAI_INSTALL_VALUES="$RHOAI_INSTALL_VALUES" bash -c '
    set -e
    microdnf install -y cpio rpm
    python3 -m venv /tmp/reference-venv
    /tmp/reference-venv/bin/pip install -r requirements.txt -r requirements-rhoai.txt
    export PATH=/tmp/reference-venv/bin:$PATH
    scripts/rhoai-reference.sh
  '
```

Point `firmwareReferenceValues` in the private `values-secret.yaml` at the
newly calculated JSON. Follow the generic ordered procedure from bootstrap
onward. Archive the private state securely before removing temporary files;
the model volume depends on its encryption keys.

## Clean installation acceptance

**PASS, 20 October 2026:** clean baseline → stock CoCo and RHOAI/ODF dependencies
→ encrypted S3 publication → fresh confidential guest → browser conversation.
All stages 00–12 passed. There were **no implementation changes or ad hoc cluster
patches during the successful installation**. The expected administrator inputs,
plan approvals, GitOps handoffs and personal CA handling still apply.

This acceptance run starts from a verified empty pattern/operator baseline on
existing OpenShift. It installs CoCo, RHOAI and ODF together using the
[documented administrator steps](../../docs/rhoai/install.md).
The implementation is frozen during the run; the two normal GitOps handoffs
amend only generated public site configuration. The acceptance record
retains the starting revision, implementation digest, timestamps and actual
observed results.

The reset was completed before installation. It removed old workloads, ODF objects
and data, Vault/registry volumes, extension operators/APIs, runtime configuration,
stale discovery labels and injected CA ConfigMaps. Deleting orphan finalizers
required explicit cleanup after their former controllers were removed; those
reset repairs are separate from installation. The host audit found no old Kata
runtime/VM or LVM metadata on the dedicated device. OpenShift, core networking
and prerequisite IOMMU settings were retained.

### Evidence from this run

| Check | Observed result |
|---|---|
| Clean gate | All 23 categories empty/healthy at 19:28:29 UTC; no old runtime/VM or dedicated-disk LVM metadata in the preceding host audit |
| Source | Start `b10d4de04710f358f20cc2a553498a307a1f7357`; generated workload activation `f9a6c4e74d1a889a5d46c6276f4aa3329450ba85` |
| Frozen implementation | SHA-256 `6c5b368de6aea47ce35a7b783f84fb41a6c7dae99b5de1e8d2c152be8c4a2a13`, unchanged through browser acceptance |
| Products | OSC 1.13.1, Trustee 1.2.1, RHOAI 3.6 EA2, ODF 4.22.6, NVIDIA GPU Operator 26.3.0 |
| ODF | Fresh standalone MCG, Bound bucket and separate Ready publisher/reader accounts; verified service-CA HTTPS |
| Publication | 2,025,615,360 ciphertext bytes; full S3 readback SHA-256 `88e48db9d3981e1e83202d3899ebb92cf530138a0165cb8a8b8f3a2f4e64c154` |
| Guest | Fresh block PVC `66bfbfd5-9bf2-4480-a4fd-020835a96cd3`; pod `3a3e0566-8c12-4a1a-bf9c-89f51d768ac7`; `kata-cc-nvidia-gpu` |
| Attestation | CPU and GPU Affirming; exact initdata `04559aa6ac22c9aa067a73ea85c0d73b21da705eccf440d3fee1e609ff1091b9`; correlated model, LUKS and TLS resource release |
| Model | Fresh S3 download, eight decrypted files, all pinned plaintext hashes verified |
| Serving | Red Hat vLLM `main` and UBI-based custom HTTPS `chat` in the same confidential VM; stock OSC helper opens guest LUKS |
| HTTPS | Certificate and hostname checks passed; passthrough Route → guest port 8443 → vLLM loopback port 8000 |
| Chrome | Actual visible response `READY.` at 21:46:46 UTC, verified in the dedicated window; user personally accepted its private-CA warning |
| Final state | All 17 Argo applications Synced/Healthy; serving pod Ready |

The installation ran from 19:28 to 21:39 UTC, followed by browser acceptance.
A workstation VPN outage interrupted access; after access was restored, the
unchanged installation tooling resumed progress. Normal Argo polling and the
stock Vault readiness hook also account for wait time. These timings are not
an installation-duration benchmark. The API's earlier response differs from
the browser prompt; both observations are preserved in the acceptance record.

The source IDs and implementation digest above identify the historical tested
snapshot. Subsequent repository housekeeping does not retroactively change
those measurements or constitute another clean installation.

### Reproduction and manual boundaries

Use a fresh private state directory and follow the generic installation runbook.
Configure the selected site, trusted reference inputs, registry credentials and
CoCo private inputs before starting. Review and approve the pinned initial
operator plans in the documented order. Build the initializer derivative,
enroll fresh model/disk/TLS keys, publish Qwen and commit the measured
configuration through the two documented GitOps handoffs. Browser certificate
trust remains a personal action. No secret bytes belong in Git.

Fresh installations deliberately produce different keys, certificate
fingerprints, release paths and workload identities. Reproducibility means
repeating the documented workflow and checks, not reproducing random values.

### Separate security and persistence qualification

Earlier checks on this branch exercised full confidential-VM replacement with
unchanged block storage, S3 permissions and bad-credential/CA rejection, JWE
authentication failure, unapproved-guest key denial, and a 2 GiB streaming test
under a 512 MiB limit. These are separate observations, not steps silently
inserted into this clean installation. Their compact evidence and
source revision are retained separately in [acceptance.json](acceptance.json).

### Scope limits

This host is AMD SEV-SNP with an NVIDIA RTX PRO 6000 Blackwell Server Edition.
Intel TDX/H100 and AMD SNP/H100 still require real hardware qualification.
ODF is standalone Multicloud Object Gateway on LVMS, without Ceph, on a
single-node lab cluster outside the documented multi-node ODF topology.
Confidential model serving is preview; the streaming initializer is a custom
derivative. Chat tests establish working transport and inference, not answer
accuracy or production support certification.

See the [architecture and execution trace](../../docs/rhoai/end-to-end.md),
[product and glue inventory](../../docs/rhoai/integration-boundary.md), and
[S3/ODF runbook](../../docs/rhoai/s3.md).
