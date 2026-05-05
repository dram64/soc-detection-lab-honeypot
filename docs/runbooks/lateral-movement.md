# Runbook: Lateral Movement via SMB

**Severity:** Medium-High (escalates fast if real)
**Detection rules:** Sigma `lateral_movement_smb.yml`, Wazuh correlated alerts
**Owning team:** SOC Tier 2 with Tier 3 / IR consultation
**Average response time target:** 20 minutes from alert to network containment

## Trigger

Detected SMB connection to administrative shares (`C$`, `ADMIN$`, `IPC$`) from an unexpected source host or during off-hours (10 PM - 6 AM).

## Why this matters

Lateral movement via SMB admin shares is a hallmark of:
- Ransomware deployment (encrypt files across multiple hosts)
- Credential harvesting (Mimikatz, hash extraction)
- Persistent backdoor installation

The window between initial compromise and full network compromise is small. Fast containment is critical.

## Initial triage (5 minutes)

**1. Identify source and destination hosts.**

```bash
# In Kibana, find the alert:
sigma.title:"Lateral Movement via SMB/Admin Shares"

# Capture:
# - src_ip: the host initiating the connection (likely already compromised)
# - dst_ip: the host being targeted
# - smb.username: which credentials are being used
# - smb.share: which admin share
```

**2. Identify the user account.**

```bash
# Check if the username is:
# - A real human (privileged user account compromised)
# - A service account (compromised credential, often more dangerous)
# - A local admin (explicit privilege escalation marker)

# In Active Directory or LDAP:
ldapsearch -x -h ldap.internal "(sAMAccountName=<username>)"
```

**3. Determine off-hours vs business-hours.**

If the alert fires during business hours, this could be a legitimate admin operation. Check:
- Is there an active maintenance window?
- Is the source host an admin workstation (jump box)?
- Is the user a known sysadmin?

If off-hours: assume malicious until proven otherwise.

## Containment (10 minutes)

**1. Network-isolate the suspected compromised host.**

The source host is likely the entry point. Isolate it from the network immediately:

```bash
# Via firewall (preferred):
# Add deny rule: src_ip = <suspect_host_ip>
# Direction: all
# Effective: immediately

# Via switch port shutdown (if on-prem):
# Identify the switch port via MAC/ARP table
# Shut the port via SSH/console

# Via cloud network ACL (if cloud):
# Cloudflare/AWS NACL deny inbound and outbound
```

**2. Disable the user account being used.**

```bash
# Active Directory:
Disable-ADAccount -Identity "<username>"

# Local accounts (less common):
sudo usermod -L <username>
```

**3. Block SMB at the perimeter for now.**

```bash
# Block external SMB inbound (should already be blocked but verify):
# Port 445/TCP, 139/TCP — deny all

# Block SMB egress to suspicious destinations
```

## Investigation

**1. Search for prior lateral movement attempts from the same source.**

```bash
# Kibana:
src_ip:"<source_host_ip>" AND smb.share:*$
# Time range: last 7 days
# Look for pattern: same source attempting multiple destinations
```

**2. Check the source host for indicators of compromise.**

If you have host visibility (Wazuh agent installed):

```bash
# Wazuh agent reports:
# - Recent process executions from source host
# - File integrity monitoring events
# - Recent logon events

# Look for:
# - Unusual processes (powershell.exe spawning SMB connections)
# - Unusual scheduled tasks
# - Unusual service installs
# - Unusual registry changes
```

**3. Check the destination host(s) for compromise indicators.**

If lateral movement succeeded, the destination is now also compromised:

```bash
# Wazuh agent on destination:
# - New file creations under \windows\system32\
# - New scheduled tasks
# - Suspicious processes (mimikatz, psexec, wmiexec patterns)
```

**4. Pull packet captures if available.**

```bash
# If Suricata or Zeek captured the SMB session:
# In Kibana, find by 5-tuple:
src_ip:"<src>" AND dst_ip:"<dst>" AND dest_port:445
# Inspect the SMB protocol fields for tool fingerprints (psexec markers, etc.)
```

## Recovery

**1. Confirm source host compromise scope.**

Before reconnecting:
- Run full malware scan
- Check for persistence mechanisms (scheduled tasks, services, registry run keys)
- Reimage if compromise confirmed (faster than incremental cleanup)

**2. Confirm destination host(s) compromise scope.**

If lateral movement succeeded:
- Treat destination as also compromised
- Apply same investigation/recovery steps
- Iterate until the spread is contained

**3. Rotate credentials.**

The compromised user account credentials must be rotated. Additionally:
- All accounts that logged into the compromised hosts in the last 30 days
- Service accounts the host had access to
- Domain admin credentials if domain admin was the compromised account

**4. Reconnect compromised host(s) only after full reimaging or forensic confirmation of cleanup.**

## Post-incident requirements

**1. Post-mortem (mandatory for any confirmed lateral movement).**

Use `docs/postmortem-template.md`. Required attendees:
- SOC team
- Security engineering
- IT operations (for the affected systems)
- Management notification depending on scope

**2. Update detection logic.**

- Did Wazuh detect the lateral movement before SOC saw it?
- Was there a delay between the SMB connection and the alert firing?
- Should we add additional Sigma rules for related techniques (PsExec, WMI, scheduled tasks)?

**3. Network segmentation review.**

Lateral movement working successfully usually indicates a flat network. Recommend network segmentation review:
- Are admin workstations on the same VLAN as user workstations?
- Are servers in their own VLAN?
- Are jump boxes used for admin access?

**4. MISP submission.**

Submit IOCs (source IP, attack patterns, tools observed) to MISP for community sharing.

## References

- MITRE ATT&CK T1021.002: https://attack.mitre.org/techniques/T1021/002/
- MITRE ATT&CK T1021: https://attack.mitre.org/techniques/T1021/
- SANS lateral movement detection: https://www.sans.org/white-papers/
- Microsoft on hardening admin shares: https://learn.microsoft.com/en-us/windows-server/storage/file-server/hardening
