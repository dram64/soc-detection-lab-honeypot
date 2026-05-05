# Detection Engineering

How detection rules are designed, written, tested, and deployed in this lab.

## Philosophy

**Detection-as-code.** Every detection rule lives in Git. No clicking around dashboards. Rules are reviewable, testable, deployable.

**Sigma at the top.** Sigma is the platform-agnostic source of truth. Sigma rules convert to Wazuh, Splunk, ELK, and Kibana queries via `sigma-cli`. Write the rule once, deploy everywhere.

**MITRE ATT&CK mapping required.** Every rule references one or more MITRE techniques. Detection coverage is then measurable against the ATT&CK matrix.

**Tune via false-positive review.** New rules start in low-severity / experimental status. After a week of live traffic, review false positives and tune up to stable.

## Rule lifecycle

### 1. Design

Before writing a rule, answer:

1. **What technique does this detect?** (MITRE T-number)
2. **What log source?** (Cowrie, Suricata, Zeek, Wazuh agent on a host)
3. **What's the false-positive risk?** (Per-IP brute force is low; "unusual port outbound" is high)
4. **What's the response action?** (Auto-block, manual review, info-only)
5. **What's the data shape?** (Inspect a real log entry first — never write rules against assumed shapes)

### 2. Write

Sigma format example: `sigma/rules/ssh_brute_force.yml`

```yaml
title: SSH Brute Force Attack
id: <generate UUID>
status: experimental  # promote to stable after tuning
description: |
  ...
references:
  - https://attack.mitre.org/techniques/T1110/
author: dram64
date: YYYY/MM/DD
tags:
  - attack.credential_access
  - attack.t1110
logsource:
  category: authentication
  product: cowrie
detection:
  failed_login:
    eventid: 'cowrie.login.failed'
  count_threshold:
    src_ip|count: '>=5'
  timeframe: 5m
  condition: failed_login | count(src_ip) by src_ip > 5
falsepositives:
  - Legitimate user typo'ing password
level: medium
fields:
  - src_ip
  - username
```

### 3. Test

```bash
# Validate Sigma syntax
sigma check sigma/rules/ssh_brute_force.yml

# Convert to platform-specific
sigma convert -t splunk sigma/rules/ssh_brute_force.yml > splunk/savedsearches/ssh_brute_force.spl
sigma convert -t es-qs sigma/rules/ssh_brute_force.yml
sigma convert -t kibana-ndjson sigma/rules/ssh_brute_force.yml > kibana/detection-rules/ssh_brute_force.ndjson

# Test against sample logs
cat tests/samples/ssh_brute_force_positive.log | sigma run sigma/rules/ssh_brute_force.yml
cat tests/samples/legitimate_login.log | sigma run sigma/rules/ssh_brute_force.yml
# Should match positive samples, NOT match legitimate ones
```

### 4. Deploy

```bash
# Deploy via the lab's startup scripts (run on docker compose up)
./scripts/deploy-rules.sh
```

For Wazuh: rules go in `wazuh/rules/100100-cowrie.xml` etc.
For Splunk: savedsearches conf in `splunk/apps/soc-detection/local/savedsearches.conf`.
For Kibana: NDJSON imported via Kibana Saved Objects API.

### 5. Tune

After 7 days of live traffic:

```bash
# Pull alert volume + true/false positive ratio for each rule
./scripts/rule-stats.sh

# Output:
# Rule 100105 (SSH brute force):     247 fires, 245 TP, 2 FP — TP rate 99.2%   STABLE
# Rule 100106 (Cred stuffing):       18  fires, 18 TP, 0 FP — TP rate 100%     STABLE
# Rule 100210 (Cross-tool correl):   52  fires, 51 TP, 1 FP — TP rate 98.1%    STABLE
# Rule 100204 (Unusual outbound):    312 fires, 41 TP, 271 FP — TP rate 13.1%  REVIEW
```

If a rule has < 70% TP rate, it needs tuning. Options:
- Tighten the threshold (5 attempts → 10 attempts)
- Add exclusions (whitelist known-good service accounts)
- Combine with another signal (only fire if MISP-matched)
- Drop the rule entirely if not actionable

### 6. Promote

Once a rule is stable:

```yaml
# Change in Sigma rule:
status: stable  # was: experimental
```

Document any tuning decisions in the rule's `description` field.

## Coverage matrix

We track ATT&CK coverage to identify gaps. As of current state:

| MITRE Tactic | Technique | Status |
|---|---|---|
| Initial Access | T1110 — Brute Force | Covered (Wazuh 100105, Sigma) |
| Initial Access | T1110.001 — Password Guessing | Covered |
| Initial Access | T1110.004 — Credential Stuffing | Covered (Wazuh 100106) |
| Initial Access | T1078 — Valid Accounts | Partial (only honeypot-side detection) |
| Lateral Movement | T1021.002 — SMB Admin Shares | Covered (Sigma) |
| Lateral Movement | T1021.001 — RDP | NOT YET COVERED |
| Command & Control | T1071 — Application Layer Protocol | Partial (Suricata 100201) |
| Command & Control | T1571 — Non-Standard Port | Covered (Sigma unusual_outbound_ports) |
| Reconnaissance | T1595 — Active Scanning | Covered (Wazuh 100203) |
| Persistence | T1543 — Service Modification | NOT YET COVERED |
| Persistence | T1547.001 — Registry Run Keys | NOT YET COVERED |
| Defense Evasion | T1070 — Indicator Removal | NOT YET COVERED |
| Defense Evasion | T1027 — Obfuscated Files | NOT YET COVERED |

**Gaps prioritized for next iteration:**

1. RDP brute force / lateral movement (T1021.001) — adapt SSH rules pattern
2. Service modification persistence (T1543) — Wazuh agent monitors systemctl events
3. Registry persistence (T1547.001) — Wazuh agent monitors HKLM run keys

## Rule writing tips

### Look at real data first

Never write a rule against assumed log shapes. Always:

1. Generate a positive event in the lab
2. Capture the actual JSON / log line
3. Build the detection logic against that real shape

### Use correlation, not just signal

Single signals have high FP rates. Combine signals:

```
Rule X: failed login from IP
Rule Y: same IP in MISP feed
→ Cross-rule trigger: HIGHER confidence detection
```

### Reduce noise via temporal logic

```
"5 failed logins" — too sensitive
"5 failed logins in 5 minutes" — better
"5 failed logins in 5 minutes from same IP" — even better
"5 failed logins in 5 minutes from same IP, with 3+ unique usernames" — credential stuffing detection
```

### Tag everything

Every rule should tag:
- MITRE tactic + technique
- Severity (low / medium / high / critical)
- Source product (cowrie, suricata, zeek, wazuh-agent)
- TLP marking if shareable (tlp:white, tlp:amber)

### Write the runbook before you ship the rule

If you can't write a runbook for what to do when the rule fires, the rule isn't actionable yet.

## Sigma rule conventions

For this lab:

- **Filename:** `sigma/rules/<lowercase_underscore>.yml`
- **UUID:** Generate via `uuidgen`, never reuse
- **Author:** `dram64`
- **Status:** `experimental` for new rules, `stable` after tuning, `deprecated` for retired rules
- **Tags:** Always include `attack.<tactic>` and `attack.<technique>`
- **Falsepositives:** Always populated. If you can't think of any, the rule isn't well-tested.
- **Level:** `low` (informational), `medium` (worth attention), `high` (act fast), `critical` (page someone)

## Resources

- Sigma project: https://github.com/SigmaHQ/sigma
- Sigma rules collection: https://github.com/SigmaHQ/sigma/tree/master/rules
- MITRE ATT&CK: https://attack.mitre.org/
- Wazuh rules reference: https://documentation.wazuh.com/current/user-manual/ruleset/
- Detection Engineering newsletter: https://www.detectionengineering.io/
