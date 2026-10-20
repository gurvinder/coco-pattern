# Trustee configuration adapter

Based on the published Validated Patterns Trustee chart 0.10.2:
`oci://quay.io/validatedpatterns/trustee:0.10.2`, artifact digest
`sha256:833a2f1175ff6b0671d7577b49361a6572354cdf41d5c1a5ccfee5378b1e2cf7`.
The original license is retained. Unchanged templates are copied directly from
that artifact, with whitespace normalized; packaging-only development files are omitted.

Three templates add configuration: `dynamic-eso.yaml` permits Base64 decoding
for the model's Vault resource; `resource-policy.yaml` renders exact confidential
guest bindings from `files/resource-policy.rego`; `rvps-values-policies.yaml`
enrolls those public initdata and launch references. Values define the binding
maps and the chart version identifies this adapter.

`pull-secret-credential-policy.yaml` targets the local hub, matching the RVPS
placement. A fresh ACM installation can label a bare-metal OpenShift cluster
`vendor: Other`; the upstream `vendor: OpenShift` selector then produces no
placement and leaves Trustee without its required `credential` Secret.

The resource policy requires affirming CPU/GPU appraisals, the selected TEE and exact initdata identity, SNP launch or TDX MRTD/RTMR1/RTMR2, guest debug disabled (and SNP migration disabled), and successful secure GPU
attestation for the model's protected resources. General CPU-only CoCo demos
retain access to their own resources. No old lab model-key bindings are enrolled
by this extension.

This configures the existing stock Trustee operator through the normal Trustee
Argo Application. It adds no Trustee service, operator or derivative image.
