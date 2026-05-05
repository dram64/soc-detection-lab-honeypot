# Runbook: SSH Brute Force Attack

**Severity:** Medium
**Detection rules:** Wazuh `100105`, Sigma `ssh_brute_force.yml`
**Owning team:** SOC Tier 1 → Tier 2 if escalated
**Average response time target:** 15 minutes from alert to containment

## Trigger

Wazuh alert `100105` fires when 5 or more failed SSH authentication attempts originate from a single source IP within 5 minutes.

## Initial triage (Tier 1, 5 minutes)

**1. Confirm the alert is real (not internal misconfiguration).**

```bash
# In Wazuh dashboard, filter by alert ID 100105
# Verify src_ip is external (not in 10.x, 172.16-31.x, 192.168.x)
# Confirm targeted user — root, admin, ubuntu, common attack targets
```

**2. Check whether the source IP is on the MISP feed.**

```bash
# In Kibana, search the misp-iocs index:
src_ip:"<attacker_ip>"
```

If matched: escalate to Tier 2 immediately. This is a known threat actor.

**3. Check whether the attempted username is a real user on real production systems.**

If the attempted username matches a real account on production: escalate to Tier 2 and proceed to containment regardless of MISP status.

**4. Confirm honeypot vs production target.**

Cowrie honeypot logs originate from the lab IP range. Real attacks against production come from different log sources. Check:

```bash
# In Cowrie source: cowrie.json events have system="cowrie"
# In production: real /var/log/auth.log entries via rsyslog
```

## Containment (Tier 1 → Tier 2 if real production target)

**Honeypot target:**
- No containment needed — the attacker is in the trap. Continue to evidence collection.

**Production target:**

**1. Block the source IP at the perimeter firewall.**

```bash
# Cloudflare WAF rule (managed via Terraform):
# Add rule: cf.client.ip eq "<attacker_ip>" then block
# Or via Cloudflare API:
curl -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/rules/lists/$LIST_ID/items" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"items":[{"ip":"<attacker_ip>"}]}'
```

**2. Force password rotation on the targeted account.**

If the username matches a real production user:
- Disable the account (`usermod -L <username>`)
- Notify the user via secure side channel
- Generate new credentials
- Re-enable account after credential rotation

**3. Enable rate limiting on SSH if not already in place.**

```bash
# /etc/ssh/sshd_config
MaxAuthTries 3
LoginGraceTime 30
```

**4. Validate that fail2ban or equivalent is active.**

```bash
sudo fail2ban-client status sshd
```

## Evidence collection

**1. Capture the full Cowrie session log if honeypot.**

```bash
# Cowrie session captures full TTY:
docker exec cowrie cat /home/cowrie/cowrie/var/lib/cowrie/tty/<session>.log > evidence/sessions/<session>.log
```

**2. Capture the corresponding Suricata flow record.**

```bash
# In Kibana:
src_ip:"<attacker_ip>" AND event_type:"flow"
# Export as JSON for the case file
```

**3. Submit IOC to MISP if novel.**

```bash
# Via MISP UI or API:
# Create event: "SSH Brute Force from <ASN>"
# Add attribute: ip-src = <attacker_ip>
# Tag: tlp:white, attack.t1110, mitre.brute-force
# Publish to internal feed
```

## Escalation criteria (escalate to Tier 2)

- Source IP matched in MISP threat feed
- Source IP attempted credential stuffing (10+ unique usernames in 10 minutes — alert 100106)
- Successful login to honeypot detected (alert 100102) — analyze attacker behavior
- Source IP also triggering Suricata alerts (rule 100210 — high-confidence cross-SIEM correlation)
- Production target with real user account

## Lessons learned

After incident closure, update:
- `docs/runbooks/ssh-brute-force.md` (this file) with any procedural improvements
- `wazuh/rules/100100-cowrie.xml` if rule tuning is needed
- `sigma/rules/ssh_brute_force.yml` if detection logic should be refined
- Post-mortem in `docs/postmortems/<date>-ssh-brute-force.md`

## References

- MITRE ATT&CK T1110: https://attack.mitre.org/techniques/T1110/
- MITRE ATT&CK T1110.001: https://attack.mitre.org/techniques/T1110/001/
- Cowrie documentation: https://cowrie.readthedocs.io/
- Wazuh ruleset reference: https://documentation.wazuh.com/current/user-manual/ruleset/
