# Build the streaming initializer

This is the only derivative image required by this demo. It starts from the
digest-pinned RHOAI 3.6 EA2 storage initializer and replaces one Python module
with the version from merged [KServe PR 6219](https://github.com/kserve/kserve/pull/6219).
[provenance.json](provenance.json) records the source commit, module checksum and
base image. The Dockerfile checks the replacement can be imported, then restores
the original non-root user. This demonstration build is not a supported Red Hat
image and does not change the published feature limits.

After the CoCo platform, internal registry and RHOAI dependency have installed,
run from the repository root with the environment from the
[installation runbook](../../docs/rhoai/install.md):

```bash
scripts/rhoai-demo.sh build
cat "$STATE_DIR/initializer-image"
```

The helper verifies the vendored module's checksum, applies the ImageStream and
binary BuildConfig in [build.yaml](build.yaml), submits this directory, and waits
for the build to complete. OpenShift's build service account needs registry
access to the pinned Red Hat base image. The cluster pull secret supplies this
in the standard installation. The build pushes to the pattern's internal
registry and records the immutable image digest in `STATE_DIR/initializer-image`.
No model keys are part of the build context or image.

The build is an explicit administrator step. Argo CD subsequently deploys the
recorded digest; it does not rebuild an image on each reconciliation. Keep the
build log and digest with the test evidence. `scripts/rhoai-prepare.sh` reads the
built image's actual environment, including OpenShift build metadata, into the
measured guest policy. Rebuilding therefore requires rerunning preparation,
publishing the new Trustee binding and committing the updated site values.

To validate the memory fix on the cluster after building:

```bash
tests/rhoai/streaming_cluster.sh
```

This decrypts synthetic 2 GiB content with a 512 MiB container limit and checks
that an invalid authentication tag does not replace existing files. It leaves
the completed Job and temporary claim as evidence. Delete `job/verify-streaming`
in the demo namespace when that evidence is no longer needed. The encrypted
model still needs space for downloaded ciphertext and decrypted files; streaming
reduces memory use, not those disk requirements.
