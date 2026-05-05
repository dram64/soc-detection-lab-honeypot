# Runbook: Credential Stuffing Attack

**Severity:** High
**Detection rules:** Wazuh `100106`, Sigma `credential_stuffing.yml`
**Owning team:** SOC Tier 2
**Average response time target:** 10 minutes from alert to containment

## Trigger

Wazuh alert `100106` fires when 10 or more unique usernames are attempted from a single source IP within 10 minutes. Distinguishes from brute force by username diversity rather than password attempts.

## Why credential stuffing matters

Unlike brute force (one user, many passwords), credential stuffing attempts known username/password pairs from leaked breach databases. The attacker assumes credentials reused across services. Higher success rate than brute force, lower noise.

## Initial triage

**1. Verify username diversity is not internal.**

```bash
# In Wazuh dashboard, list distinct usernames from the source IP:
# Filter: src_ip:"<attacker_ip>" AND rule.id:100101
# Aggregation: by data.username

# Internal misconfigurations rarely produce 10+ distinct usernames
# in 10 minutes. If you see 10+ distinct usernames, it's external.
```

**2. Check the username list against known leaked credentials.**

If usernames match patterns commonly found in haveibeenpwned database (e.g., `admin@example.com`, `support`, `info`, common email addresses), this is credential stuffing from a botnet.

**3. Identify the attacker's source.**

```bash
# Check the source IP's ASN
whois <attacker_ip> | grep -i "OrgName\|netname"

# Common credential stuffing ASNs:
# - DigitalOcean, OVH, Hetzner (cheap VPS, easily abused)
# - Hosting providers in countries with weak abuse response
```

## Containment

**1. Block the source IP at the perimeter immediately.**

This is high severity — block first, investigate second.

```bash
# Cloudflare WAF — add to blocked IPs list
curl -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/rules/lists/$LIST_ID/items" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"items":[{"ip":"<attacker_ip>","comment":"Cred stuffing - 100106"}]}'
```

**2. Block the entire ASN if stuffing is widespread.**

If multiple IPs from the same ASN are attacking simultaneously, block the ASN at the WAF level.

```bash
# Cloudflare expression:
# (ip.geoip.asnum eq <ASN>) and (http.request.uri.path contains "/login")
```

**3. Force MFA enforcement on all accounts.**

If MFA is not already enforced for all users, enable it immediately for any account that may have been targeted:

```bash
# Identify potentially compromised accounts (any username appearing in the attack):
# Wazuh search: rule.id:100101 AND src_ip:"<attacker_ip>"
# Aggregate distinct usernames

# For each:
# - Force password rotation
# - Enable MFA if not already
# - Invalidate all active sessions
# - Notify the user via secure channel (out-of-band, not email if email is the targeted account)
```

**4. Increase login rate limits temporarily.**

```bash
# Web tier rate limit: 5 attempts per IP per 5 min
# (deploy via Cloudflare WAF or your application's rate limiter)
```

## Investigation

**1. Pull the full credential list attempted.**

```bash
# Kibana query:
src_ip:"<attacker_ip>" AND rule.id:100101
# Export all attempted (username, password) pairs as JSON

# Cross-reference passwords against haveibeenpwned API to confirm
# attacker is using a known breach dataset
```

**2. Determine target priority.**

- If usernames match real users on production: HIGH PRIORITY — proceed to lessons-learned and post-mortem
- If usernames are random/generated: medium priority — still note in MISP

**3. Check for similar attacks in last 30 days.**

```bash
# Kibana:
rule.id:100106 AND @timestamp:[now-30d TO now]
# Aggregate by src_ip / ASN
```

## Evidence preservation

**1. Capture the full event window.**

```bash
# Export from Kibana:
src_ip:"<attacker_ip>" AND @timestamp:[<start> TO <end>]
# Save as: evidence/cred-stuffing-<date>-<src_ip>.json
```

**2. Submit comprehensive IOC to MISP.**

```bash
# MISP event:
# - Title: "Credential stuffing campaign from <ASN>"
# - Tags: tlp:amber, attack.t1110.004, mitre.credential-access
# - Attributes:
#   - ip-src: <attacker_ip>
#   - text: "Username pattern: <patterns observed>"
#   - text: "Password source: likely breach <name>"
# - Distribution: Sharing community (other SOC teams benefit)
```

## Post-incident

**1. Audit affected accounts for actual compromise.**

For any account where credential stuffing succeeded (rare on a hardened system):
- Review login history (geographic, IP patterns)
- Check for data exfiltration in last 24 hours
- Force password reset
- Notify user

**2. Update detection logic if needed.**

Did the rule fire fast enough? Should the threshold be 5 unique usernames instead of 10? Update `wazuh/rules/100100-cowrie.xml` and `sigma/rules/credential_stuffing.yml`.

**3. Post-mortem.**

Use `docs/postmortem-template.md`. Required for any credential stuffing event affecting real production accounts.

## Escalation

Always escalate immediately if:
- Real production accounts are targeted
- Successful login to a real account from the attacker IP
- Source IP appears in multiple recent incidents (could indicate persistent campaign)

## References

- MITRE ATT&CK T1110.004: https://attack.mitre.org/techniques/T1110/004/
- OWASP Credential Stuffing: https://owasp.org/www-community/attacks/Credential_stuffing
- haveibeenpwned API: https://haveibeenpwned.com/API/v3
