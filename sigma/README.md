# Sigma rules

Detection logic for the Cowrie honeypot data, written once in Sigma and converted to Kibana
detection rules by [`elastic/soc_elastic`](../elastic/). These rules were **deployed in the Phase 2
offline replay** of the archived 14-day run (May 6–21, 2026). They never ran against live traffic.

## Layout

```
sigma/
├── pipelines/cowrie_ecs.yml     # pySigma pipeline: Cowrie field names -> ECS-aligned index fields
└── rules/
    ├── *.yml                    # 8 deployable Cowrie rules (below)
    └── not-deployed/            # 3 network rules with no data source in this lab (see its README)
```

## Deployed rules (Phase 2 replay)

ATT&CK IDs validated against v19.2 (the data bundled with pySigma 1.5). Alert counts are from the
single replay execution, and each matches the rule's own query run directly against the index.

| Rule | Type | Level | Status | ATT&CK | Alerts | Write-up |
|---|---|---|---|---|---|---|
| [`ssh_brute_force.yml`](rules/ssh_brute_force.yml): ≥5 failed logins / source IP / 5 min | correlation (event_count) | medium | test | T1110.001 | 1,054 | [INV-04](../docs/investigations/04-automated-scanners.md) |
| [`credential_stuffing.yml`](rules/credential_stuffing.yml): ≥10 distinct usernames / source IP / 10 min | correlation (value_count) | high | test | T1110.004 | 168 | [INV-04](../docs/investigations/04-automated-scanners.md) |
| [`cowrie_automated_ssh_client.yml`](rules/cowrie_automated_ssh_client.yml): ≥20 library/scanner-banner sessions / source IP / 1 h | correlation (event_count) | low | experimental | T1595 | 219 | [INV-04](../docs/investigations/04-automated-scanners.md) |
| [`cowrie_botnet_credential_marker.yml`](rules/cowrie_botnet_credential_marker.yml): username `345gs5662d34` | event | medium | experimental | T1110.001 | 1,523 | [INV-01](../docs/investigations/01-botnet-credential-marker.md) |
| [`cowrie_ssh_authorized_keys_implant.yml`](rules/cowrie_ssh_authorized_keys_implant.yml): command writes an `ssh-rsa` key to `authorized_keys` | event | high | experimental | T1098.004, T1222.002 | 1,577 | [INV-02](../docs/investigations/02-ssh-authorized-keys-implant.md) |
| [`cowrie_miner_payload_upload.yml`](rules/cowrie_miner_payload_upload.yml): upload of `redtail.*` / `setup.sh` / `clean.sh` | event | high | experimental | T1105, T1496.001 | 188 | [INV-03](../docs/investigations/03-crypto-mining-redtail.md) |
| [`cowrie_miner_recon.yml`](rules/cowrie_miner_recon.yml): rival-miner check / CPU-core counting | event | medium | experimental | T1057, T1082 | 46 | [INV-03](../docs/investigations/03-crypto-mining-redtail.md) |
| [`cowrie_direct_tcpip_proxy.yml`](rules/cowrie_direct_tcpip_proxy.yml): SSH port-forward request | event | medium | experimental | T1090 | 130 | [INV-04](../docs/investigations/04-automated-scanners.md) |

**Status meanings used here:**
- `test`: validated to fire correctly on the real replayed events. That applies only to the two
  original Cowrie rules.
- `experimental`: new, written against events observed in the dataset. It fires, but hasn't been
  tuned or checked for false positives on anything but a honeypot.
- No rule is `stable`. Nothing here has run against production traffic, where false positives would
  show up.

## Not deployed

`known_bad_ip_match`, `lateral_movement_smb` and `unusual_outbound_ports` need Suricata, MISP or Zeek
data, and none of that exists in this lab. They live in [`rules/not-deployed/`](rules/not-deployed/)
with the reasons and one known logic bug. The conversion pipeline refuses any non-Cowrie rule, so they
can't be deployed by accident.

## Validate and convert

```bash
pip install sigma-cli pysigma-backend-elasticsearch
sigma check sigma/rules/*.yml
sigma convert -t esql -p sigma/pipelines/cowrie_ecs.yml sigma/rules/ssh_brute_force.yml
```

CI ([`sigma-validate.yml`](../.github/workflows/sigma-validate.yml)) runs `sigma check` on every rule
and converts the deployable rules through the pipeline. Deployment to Kibana, including the ATT&CK
threat mapping, is `python -m soc_elastic.deploy_rules` (see [`elastic/README.md`](../elastic/README.md)).

## Conventions

- Write rules against **Cowrie's own field names** (`eventid`, `src_ip`, `username`, `input`, …). The
  pipeline is the only place they get mapped to index fields.
- Correlation base rules must exclude unattributed events (`src_ip: null`), otherwise every
  unattributed session collapses into one "null" source.
- Every rule carries `attack.<tactic>` + `attack.<technique>` tags. An unknown technique ID fails deployment.
- Known conversion caveats: ES|QL output is case-sensitive, and correlation windows are tumbling
  buckets. See `elastic/README.md`.
