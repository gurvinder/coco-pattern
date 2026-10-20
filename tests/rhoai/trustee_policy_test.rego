package policy
import rego.v1

fixture_vector := {"hardware":2,"executables":2,"configuration":2}
fixture_cpu := {"ear.status":"affirming","ear.trustworthiness-vector":fixture_vector,"ear.veraison.annotated-evidence":{"init_data":"approved-init","snp":{"measurement":"approved-launch","policy_debug_allowed":false,"policy_migrate_ma":false}}}
fixture_gpu := {"ear.status":"affirming","ear.trustworthiness-vector":fixture_vector,"ear.veraison.annotated-evidence":{"nvidia":{"x-nvidia-overall-att-result":true,"secboot":true,"dbgstat":"disabled","measres":"success"}}}
fixture_ear := {"submods":{"cpu0":fixture_cpu,"gpu0":fixture_gpu}}
fixture_bindings := {"rhoai-qwen-secrets":{"tee":"snp","initData":"approved-init","launchMeasurement":"approved-launch"}}

test_reserved_class_denied_before_enrollment if {
    not allow with input as fixture_ear with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"]
}
test_exact_guest_gets_each_demo_resource if {
    every resource in ["model-key","luks-passphrase","registry","tls-cert","tls-key"] {
        allow with input as fixture_ear with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets",resource] with data.policy.confidential_guest_bindings as fixture_bindings
    }
}
test_modified_guest_denied if {
    bad := json.patch(fixture_ear,[{"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/init_data","value":"changed"}])
    not allow with input as bad with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_bindings
}
test_cpu_only_denied_demo_but_keeps_existing_demo if {
    cpu_only := {"submods":{"cpu0":fixture_cpu}}
    not allow with input as cpu_only with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_bindings
    allow with input as cpu_only with data.plugin as "resource" with data["resource-path"] as ["default","kbsres1","key3"]
}

fixture_tdx_bindings := {"rhoai-qwen-secrets":{"tee":"tdx","initData":"approved-init","mrTd":"approved-td","rtmr1":"approved-kernel","rtmr2":"approved-command"}}
fixture_tdx_cpu := {"ear.status":"affirming","ear.trustworthiness-vector":fixture_vector,"ear.veraison.annotated-evidence":{"init_data":"approved-init","tdx":{"td_attributes":{"debug":false},"quote":{"body":{"mr_config_id":"approved-init00000000000000000000000000000000","mr_td":"approved-td","rtmr_1":"approved-kernel","rtmr_2":"approved-command"}}}}}
fixture_tdx_ear := {"submods":{"cpu0":fixture_tdx_cpu,"gpu0":fixture_gpu}}

test_tdx_exact_guest_allowed if {
    allow with input as fixture_tdx_ear with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
}
test_tdx_changed_measurement_or_debug_denied if {
    every patch in [
        {"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/tdx/quote/body/mr_td","value":"different"},
        {"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/tdx/quote/body/rtmr_1","value":"different"},
        {"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/tdx/quote/body/rtmr_2","value":"different"},
        {"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/tdx/td_attributes/debug","value":true},
        {"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/init_data","value":"different"}
    ] {
        bad := json.patch(fixture_tdx_ear,[patch])
        not allow with input as bad with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
    }
}
test_cross_tee_denied if {
    not allow with input as fixture_ear with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
    not allow with input as fixture_tdx_ear with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_bindings
}
test_tdx_requires_gpu_and_affirming_status if {
    every patch in [
        {"op":"remove","path":"/submods/gpu0"},
        {"op":"replace","path":"/submods/gpu0/ear.veraison.annotated-evidence/nvidia/secboot","value":false},
        {"op":"replace","path":"/submods/cpu0/ear.status","value":"warning"}
    ] {
        bad := json.patch(fixture_tdx_ear,[patch])
        not allow with input as bad with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
    }
}

test_tdx_padded_initdata_allowed if {
    padded := json.patch(fixture_tdx_ear,[{"op":"replace","path":"/submods/cpu0/ear.veraison.annotated-evidence/init_data","value":"approved-init00000000000000000000000000000000"}])
    allow with input as padded with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
}
test_tdx_wrong_mrconfigid_or_padding_denied if {
    every path in ["/submods/cpu0/ear.veraison.annotated-evidence/init_data","/submods/cpu0/ear.veraison.annotated-evidence/tdx/quote/body/mr_config_id"] {
        bad := json.patch(fixture_tdx_ear,[{"op":"replace","path":path,"value":"approved-init00000000000000000000000000000001"}])
        not allow with input as bad with data.plugin as "resource" with data["resource-path"] as ["default","rhoai-qwen-secrets","model-key"] with data.policy.confidential_guest_bindings as fixture_tdx_bindings
    }
}
