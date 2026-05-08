# Homelab — supplementary infrastructure

This directory holds in-progress homelab buildouts that supplement the AWS-native SOC pipeline in [../dashboard/](../dashboard/). The AWS pipeline is the primary system; everything here is additive.

## Status (current)

| Component | Status | Notes |
|---|---|---|
| `wazuh/` | 🟡 in-progress | Single-node Wazuh SIEM on Pi 5; Phase 1A. See [wazuh/PHASE_1A_LOG.md](wazuh/PHASE_1A_LOG.md). |
| `suricata/` | ⏸ deferred | Network IDS; depends on Wazuh shipping first. |
| `k3s/` | ⏸ deferred | Container orchestration on Pi; Phase 1D. |
| `sigma-rules/` | ⏸ deferred | Rule deployment + tuning; depends on Wazuh shipping first. |
| `elk-stack/` | ⏸ deferred | Alternative SIEM target if the Wazuh path proves unworkable. |

## Resume-claims policy

**Do not add SIEM / detection-engineering / threat-detection keyword claims to the top-level repo README, resume, or portfolio site until the underlying component is shipped.** The 2026-05-07 README rewrite (SHA `6fe9d28`) explicitly excluded these claims as aspirational. Each component here is the work that backs them up.
