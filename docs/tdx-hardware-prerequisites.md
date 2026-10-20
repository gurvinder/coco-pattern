# Intel TDX GPU prerequisites

Use a server and firmware combination supported by the selected OpenShift/OSC
release. Follow the hardware manufacturer's procedure for enabling Intel TDX,
its required memory encryption configuration, virtualization and IOMMU. Menu
names and memory population requirements are server-specific; do not apply one
server's BIOS checklist to another platform.

Enable GPU confidential computing and passthrough for the H100 deployment, and
complete Intel platform registration and quote-generation prerequisites. The
CoCo `intel-tdx-gpu` profile installs the corresponding OpenShift components;
it cannot substitute for firmware setup or credentials.

See [Red Hat confidential workload requirements](https://docs.redhat.com/en/documentation/openshift_sandboxed_containers/1.13/html/deploying_confidential_containers_on_bare-metal_servers/confidential-workload-environment_metal-cc)
and the stock CoCo connected/offline attestation workflow. Keep server-specific
instructions and qualification records under your optional testing/site directory.
