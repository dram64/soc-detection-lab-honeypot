# Sigma Rules

Platform-agnostic detection rules. Source of truth for all detection logic in this lab.

## Layout

```
sigma/
├── README.md                       # You are here
├── rules/
│   ├── ssh_brute_force.yml
│   ├── credential_stuffing.yml
│   ├── lateral_movement_smb.yml
│   ├── known_bad_ip_match.yml
│   └── unusual_outbound_ports.yml
└── tests/
    └── (positive and negative test samples per rule)
```

## How to use

### Validate a rule

```bash
sigma check rules/ssh_brute_force.yml
```

### Convert to platform-specific format

```bash
# Splunk SPL
sigma convert -t splunk rules/ssh_brute_force.yml

# Elasticsearch DSL query
sigma convert -t es-qs rules/ssh_brute_force.yml

# Kibana NDJSON (for Detection Engine import)
sigma convert -t kibana-ndjson rules/ssh_brute_force.yml

# Wazuh local rule XML
# (no native Sigma backend for Wazuh; rules in wazuh/rules/ are hand-written)
```

### Run all rules through CI

CI validates every rule on push to `main`. See `.github/workflows/sigma-validate.yml`.

## Rule writing conventions

- **Filename:** `lowercase_with_underscores.yml`
- **UUID:** Always unique. Generate with `uuidgen`.
- **Status:** Start at `experimental`. Promote to `stable` after tuning. Use `deprecated` for retired rules.
- **MITRE tags:** Always include `attack.<tactic>` and `attack.<technique>`.
- **Severity:** `low` (info), `medium` (worth attention), `high` (act fast), `critical` (page).
- **Falsepositives:** Document realistic FP scenarios. If you can't think of any, the rule isn't well-tested.

## Tuning workflow

1. Ship at `experimental` status with a deliberately conservative threshold
2. Run for 7 days against live data
3. Review TP/FP rate via `scripts/rule-stats.sh`
4. If TP rate < 70%: tune (raise threshold, add exclusions, combine with another signal, or retire)
5. Once stable: change `status: stable` and document tuning history in the rule

## Coverage matrix

See [`../docs/detection-engineering.md`](../docs/detection-engineering.md) for the live ATT&CK coverage matrix.

## Resources

- Sigma project: https://github.com/SigmaHQ/sigma
- Public rules: https://github.com/SigmaHQ/sigma/tree/master/rules
- Sigma specification: https://github.com/SigmaHQ/sigma-specification
