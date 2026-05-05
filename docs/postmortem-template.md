# Incident Postmortem: [Incident Title]

**Date of incident:** YYYY-MM-DD
**Date of postmortem:** YYYY-MM-DD
**Severity:** Critical | High | Medium | Low
**Status:** Closed
**Author:** [name]
**Reviewers:** [names]

## Summary

[2-3 sentence executive summary. What happened, what was the impact, what was the resolution.]

## Timeline

All times in UTC.

| Time | Event |
|---|---|
| HH:MM | Initial alert fired in Wazuh (rule ID XXX) |
| HH:MM | SOC Tier 1 acknowledged |
| HH:MM | Triage complete, severity confirmed |
| HH:MM | Containment action: [block IP / disable account / isolate host] |
| HH:MM | Investigation began |
| HH:MM | Root cause identified |
| HH:MM | Recovery completed |
| HH:MM | Incident closed |

## Detection

**How was this detected?**

- [Wazuh rule ID] / [Sigma rule path]
- Detection time from initial event: X minutes
- Detection latency notes: [why was it slow / fast]

**Was detection effective?**

- [ ] Yes, alert fired immediately
- [ ] Partial — alert fired but with delay
- [ ] No — detected by other means (user report, monitoring outage)

If not effective, what gap existed?

## Root cause

[What actually happened, in technical detail. Include the attacker's path through the system, any vulnerabilities exploited, any misconfigurations leveraged.]

## Impact

**Systems affected:**
-

**Data exposed:**
-

**User accounts affected:**
-

**Downtime / availability impact:**
-

**Financial impact (estimated):**
-

## Response

**What went well:**
-

**What didn't go well:**
-

**What was lucky (i.e., we got away with something):**
-

## Action items

| # | Action | Owner | Due date | Status |
|---|---|---|---|---|
| 1 | | | | Open |
| 2 | | | | Open |

## Detection improvements

Based on this incident, the following detection improvements should be made:

- [ ] New Sigma rule for: [specific attack pattern]
- [ ] New Wazuh rule for: [specific log pattern]
- [ ] New Suricata rule for: [specific network pattern]
- [ ] MISP feed update: add [IOC types] from this event
- [ ] Dashboard improvement: add [metric / view]

## Process improvements

- [ ] Runbook update: [which runbook needs revision]
- [ ] Training: [team training needed]
- [ ] Tool gap: [missing capability identified]
- [ ] Communication: [improvement to escalation/notification]

## Architecture improvements

- [ ] Network: [segmentation / firewall / WAF change]
- [ ] Host: [hardening / EDR / patching change]
- [ ] Identity: [auth / MFA / privilege change]
- [ ] Logging: [coverage gap closed]

## Lessons learned

[3-5 bullet points capturing what we learned that should change how we operate.]

## References

- MITRE ATT&CK techniques observed: [T1XXX, T1XXX]
- Related runbooks: [paths]
- External advisories: [CVE, vendor advisories, etc.]
- Source data: [Kibana queries, evidence files, etc.]

---

*This postmortem is blameless. Its purpose is to identify systemic improvements, not assign individual fault.*
