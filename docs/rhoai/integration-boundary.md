# Product features and demo integration

The model download, confidential key resolution, model decryption and inference
use the RHOAI/Red Hat serving components. This demo adds installation,
storage handoff, policy and browser application code around them. Using Red Hat
base images does not make that additional code a Red Hat product feature.
The [end-to-end execution trace](end-to-end.md) follows the actual calls, keys,
filesystem paths, container ordering and browser request, with source line links.

## The confidential serving API

The pattern creates an `LLMInferenceService` (`serving.kserve.io/v1alpha2`),
referencing a reusable `LLMInferenceServiceConfig`. It does not also create a
generic `InferenceService` (`serving.kserve.io/v1beta1`).

```yaml
apiVersion: serving.kserve.io/v1alpha2
kind: LLMInferenceService
metadata:
  name: qwen
spec:
  baseRefs:
    - name: coco-encrypted-storage
  model:
    name: qwen3-0.6b
    uri: <encrypted-model-url>
    confidential:
      enabled: true
      resourceId: <model-key-KBS-URI>
```

The referenced configuration selects `kata-cc-nvidia-gpu`. The syntax is
`confidential.enabled: true`, not a boolean `confidential: true`.

| Feature | Actual execution in this pattern |
|---|---|
| RHOAI KServe workload management | Its controller reconciles the LLM service and configuration into the serving workload. |
| RHOAI model download | The existing `/storage-initializer/scripts/initializer-entrypoint` downloads and extracts the encrypted HTTP or S3 archive. |
| Optional Red Hat ODF MCG | The stock operator provisions the S3 gateway, bucket, backing storage and accounts; our configuration and policy hook scope their access. |
| Confidential key resolution | `CONFIDENTIAL_ENABLED=true` and `CONFIDENTIAL_RESOURCE_ID` activate the initializer's `CDHSecretResolver`, which requests the model key through guest CDH. |
| Confidential model decryption | KServe's `JWEDecryptor` decrypts the JWE model files. One module is replaced with the pinned upstream streaming fix. |
| Red Hat AI Inference Server | The unchanged Red Hat vLLM image loads the decrypted Qwen files onto the GPU and serves its OpenAI-compatible API. |
| OSC encrypted block storage | The unchanged `osc-storage-helper` opens/formats LUKS and mounts the raw block PVC inside the guest. This is OSC functionality, separate from RHOAI's JWE decryption. |
| CoCo and Trustee attestation | Stock guest attestation/CDH and Trustee perform appraisal and gated key release, using this demo's configured policies and references. |

`storageInitializer.enabled: false` disables **automatic injection** of the
initializer. The pattern explicitly supplies that same initializer so it runs
after `format-disk` and `check-ready`. The confidential environment settings are
therefore supplied explicitly as well; the model-level declaration alone is
not responsible for setting them in this configuration. Yuval's reference uses
this same explicit ordering.

Our wrapper checks the volume and then invokes the product entrypoint. It
does not implement another model downloader or decryption algorithm. On a
subsequent VM start, it verifies the persisted model's hashes and skips the
download/decryption if the files are already complete.

The RHOAI inference gateway, its API authentication and distributed serving
features are not used in this single-GPU demo. vLLM listens on guest loopback.
The separate chat container calls that API and provides the browser endpoint.
The OpenShift Route uses TLS passthrough to its Python HTTPS server on port
8443, so the TLS session ends inside the same confidential VM.

## What came from the reference

[Yuval's pinned example](https://github.com/aicatalyst-team/confidential-model-serving/blob/ed79cc4e7fae49d6d50ea26b454c204ced2d69f7/README.md)
already contains raw block storage, the OSC helper, shared process namespace,
a shell storage-link helper, explicit initializer ordering, confidential model
configuration, and vLLM startup settings. Those are the foundation of this
integration, not capabilities invented by this pattern.

That reference uses `quay.io/aicatalyst/storage-initializer:latest`, describes it
as a custom workaround, and demonstrates Gemma through Hugging Face/S3 and an
inference gateway. This pattern instead uses a pinned RHOAI initializer base,
Qwen, an HTTP or S3 ciphertext archive and a browser chat endpoint inside the VM.
Its reference preparation also supports selecting AMD SNP as well as Intel TDX.

The archive choice exposed Python path-resolution problems with the reference's
cross-container storage symlink. Our `link.sh` mounts the helper's already-open
device mapper in each consuming container's mount namespace. This is an
adaptation for the chosen archive path and published images, not evidence that
the reference lacked encrypted storage.

The reference explicitly uses a permissive development guest policy. Its
example format wrapper also wipes an existing LUKS header after a passphrase
mismatch. This pattern adds stricter measured policies and refuses that
reformatting behavior. These are demo design additions, not requirements for
every deployment of RHOAI confidential serving.

## Added and reused code inventory

Paths below are relative to the repository root. YAML/Helm resources are also
part of the extension; this list identifies executable or policy logic.

| Path | Provenance and purpose |
|---|---|
| `build/storage-initializer/jwe_decryptor.py` | Vendored upstream KServe PR 6219 module; streaming JWE decryption. Source commit and checksum are in `provenance.json`. |
| `build/storage-initializer/Dockerfile` | Demo-created five-line derivative definition replacing that one module in the pinned RHOAI image. |
| `charts/hub/rhoai-model-publisher/files/encrypt_model.py` | Vendored encryption utility from Yuval's pinned reference. |
| `charts/hub/rhoai-model-publisher/files/publish.sh` | Demo-created preparation wrapper: fetch pinned Qwen, verify inventory, call the upstream encryptor and package ciphertext. |
| `charts/hub/rhoai-model-publisher/files/upload_s3.py` | Demo-created S3 upload, release-collision guard and streamed readback checksum verification, using the stock image's AWS SDK. |
| `charts/hub/rhoai-object-storage/files/bucket_policy.py` | Demo-created ODF policy hook granting separate publisher-write and inference-read identities access to ciphertext. |
| `scripts/rhoai-s3.sh` | Demo-created one-time ODF/external S3 credential enrollment in Vault and public site-value generation. |
| `charts/coco-supported/rhoai-confidential-qwen/files/format.sh` | Adaptation of the reference helper sequence, with checks that refuse an unknown disk or incorrect existing LUKS key. Calls the stock OSC helper. |
| `charts/coco-supported/rhoai-confidential-qwen/files/link.sh` | Demo-created adaptation of the reference storage handoff; includes an embedded Python call to Linux `mount(2)`. |
| `charts/coco-supported/rhoai-confidential-qwen/files/initialize.sh` | Demo-created mount/hash/reuse wrapper around the product initializer entrypoint, plus restart diagnostics. |
| `charts/coco-supported/rhoai-confidential-qwen/files/vllm.sh` | Demo-created mount/hash wrapper and arguments for the stock vLLM server. |
| `charts/coco-supported/rhoai-confidential-qwen/files/server.py` and `index.html` | Reused and adapted from our earlier confidential inference demo; browser chat and proxy logic. |
| `charts/coco-supported/rhoai-confidential-qwen/files/chat.sh` | Demo-created CDH certificate/key retrieval and Python HTTPS startup wrapper. |
| `charts/coco-supported/rhoai-confidential-qwen/templates/_helpers.tpl` | Demo-created measured startup commands that copy scripts into guest memory and verify their hashes before execution. |
| `charts/hub/rhoai-platform/files/bootstrap.py` | Demo-created bounded installation hook: inspect/approve the pinned initial RHOAI plan and wait for product APIs/readiness. |
| `scripts/rhoai-config.sh`, `rhoai-configure-owner.sh` | Demo-created site selection and generation of public GitOps values. |
| `scripts/rhoai-reference.sh` | Demo-created adapter around stock veritas for the selected TEE, GPU artifacts and reviewed reference inputs. |
| `scripts/rhoai-enroll.sh`, `rhoai-prepare.sh` | Demo-created key/certificate enrollment and measured workload/policy preparation. |
| `scripts/rhoai-demo.sh` | Demo-created administrator helpers for checks, build, publication and HTTPS verification. |
| `policies/rhoai-guest.rego.in` | Demo-created guest policy restricting operations and binding the approved workload. |
| `charts/hub/rhoai-trustee/files/resource-policy.rego` | Demo-created exact workload/TEE key-release policy. |
| `charts/hub/rhoai-trustee/templates/` | Mostly vendored stock Trustee chart 0.10.2; the adaptations are listed in its `UPSTREAM.md`. |
| `tests/rhoai/` and `tests/test_rhoai*.py` | Demo-created clean-baseline gate, regression, rendering, policy, streaming and negative-attestation checks. The baseline gate is read-only; it does not uninstall resources. |

The sole application-image derivative is the initializer. Embedded shell,
Python, JavaScript and Rego remain custom integration/application code even
when they are delivered as ConfigMaps into otherwise unchanged images.
See [the architecture](end-to-end.md), [source lock](source-lock.json) and
[initializer build instructions](../../build/storage-initializer/README.md).
