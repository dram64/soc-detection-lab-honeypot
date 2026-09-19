# INV-02: SSH `authorized_keys` implant campaign ("mdrfckr" key)

| | |
|---|---|
| **Data** | Phase 2 offline replay of the archived Cowrie run, May 6–21, 2026. The detection ran in Sept 2026, not live. |
| **Rule** | `[Sigma] SSH Authorized Keys Implant via Shell Command` ([rule](../../sigma/rules/cowrie_ssh_authorized_keys_implant.yml)), severity **high** |
| **Alerts** | 1,577 (one per matching command), 445 distinct source IPs |
| **ATT&CK** (v19.2) | T1098.004 SSH Authorized Keys (Persistence); T1222.002 Linux and Mac File and Directory Permissions Modification (Defense Impairment) |
| **Verdict** | True positive: automated, botnet-scale persistence attempt. Severity **high**; it would be **critical** on a production host. |

## What fired

The rule matches `cowrie.command.input` events whose command line contains both
`authorized_keys` and `ssh-rsa`. ES|QL deployed:

```
from cowrie-* metadata _id, _index, _version
| where event.action=="cowrie.command.input"
  and process.command_line like "*authorized_keys*" and process.command_line like "*ssh-rsa*"
```

## Evidence

**Two distinct keys** were planted:

| Key (truncated) | Key comment | Commands | Notes |
|---|---|---|---|
| `AAAAB3NzaC1yc2EAAAABJQAAAQEArDp4cun2lhr4…` | `mdrfckr` | 1,547 | The main campaign (this write-up) |
| `AAAAB3NzaC1yc2EAAAADAQABAAABAQCqHrvnL6l7…` | `rsa-key-20230629` | 30 | Planted by the RedTail miner sessions, see [INV-03](03-crypto-mining-redtail.md) |

Cowrie hashes what gets written to disk. **1,545 writes to `/root/.ssh/authorized_keys` from 442 source IPs
share one SHA-256** (`a8460f446be540410004b1a8db4083773fa46f7fe76fa84219c93daa1669f8f2`), so the same
key file was written everywhere.

**Scale and spread:** first seen 2026-05-07 05:41 UTC, last seen 2026-05-21 12:18 UTC (the end of
the run). 445 source IPs, and no single IP accounts for more than 24 implant commands.

| Top source ASNs (implant commands) | Commands |
|---|---|
| AS132203 Tencent Building, Kejizhongyi Avenue | 338 |
| AS8075 Microsoft Corporation | 132 |
| AS4766 Korea Telecom | 59 |
| AS135377 UCLOUD Information Technology HK | 55 |
| AS7552 Viettel Group | 43 |
| (unattributed: no source IP recovered) | 45 |

Top countries: United States 336, Singapore 170, South Korea 92, Hong Kong 75, Vietnam 71, Brazil 71.
The spread across cloud providers and residential ISPs looks like a botnet of already-compromised
hosts, not one operator's infrastructure.

**Client fingerprint:** implant sessions announce `SSH-2.0-libssh_0.9.6` (1,385), `libssh_0.12.0`
(113) and `libssh_0.11.1` (49). The same banners appear in [INV-01](01-botnet-credential-marker.md).

### Representative session (`00e8e903862a`, 2026-05-17, all times UTC)

| Time | Event | Detail |
|---|---|---|
| 17:48:41.516 | session.connect | 86.180.86.34, AS2856 British Telecommunications PLC, United Kingdom (correlation: matched) |
| 17:48:41.536 | client.version | `SSH-2.0-libssh_0.12.0` |
| 17:48:42.312 | login.success | `root` / `test123456789` (dictionary password) |
| 17:48:42.677 | command.input | `cd ~; chattr -ia .ssh; lockr -ia .ssh` |
| 17:48:42.678 | command.failed | `lockr -ia .ssh`: not a real binary on the honeypot |
| 17:48:43.187 | command.input | `cd ~ && rm -rf .ssh && mkdir .ssh && echo "ssh-rsa AAAA…mdrfckr">>.ssh/authorized_keys && chmod -R go= ~/.ssh && cd ~` (identical in all 1,547) |
| 17:48:43.356 | session.file_download | `/root/.ssh/authorized_keys`, SHA-256 `a8460f44…` |
| 17:48:46.650 | session.closed | ~5 s end to end |

The whole chain runs in about 1 second after login with no interactive typing, which points to scripted tooling.

## Analysis

1. **Persistence:** the key gives the operator password-less re-entry that survives a root
   password change.
2. **Defense impairment:** `chattr -ia` strips the immutable and append-only attributes a defender (or a rival
   bot) may have set on `.ssh`. `lockr -ia` takes the same flags as `chattr`, so it is
   probably a renamed copy the bot expects to find. That's an inference, not verified. It failed here
   because no such binary exists on the honeypot.
3. **Competitor removal:** `rm -rf .ssh` wipes every existing key, including other botnets'.
4. **Attribution:** the `mdrfckr` key comment and this exact command chain match what public honeypot
   write-ups attribute to the "Outlaw" botnet. **Not independently verified here.** No binaries
   were retrieved or analysed (ADR-009), and I did no threat-intel lookups in this offline pass.

## Severity call

- **In this lab: high.** It is a real, successful-looking persistence attempt against the decoy, but
  there is no real asset and the honeypot filesystem is emulated.
- **On a production server: critical.** An unknown key in root's `authorized_keys` means the host is
  compromised, and the operator can come back even after the password is rotated.

## Tier-1 next steps / escalation

1. **Scope the IOC, not the IP.** 445 IPs make IP blocking whack-a-mole. The durable indicators are
   the public key (and its fingerprint), the key comment `mdrfckr`, and the written-file SHA-256.
   Hunt for them in `authorized_keys` across the fleet, with EDR/osquery `file` tables or a config-management
   audit.
2. **Hunt the sequence:** search real SSH/auth logs for `chattr -ia .ssh` or `lockr` in shell
   history or auditd `execve` records.
3. **If found on a real host → escalate to Tier 2/IR immediately:** isolate the host, remove the key,
   restore `.ssh` attributes, rotate every credential used on the host, and review what the key was used for
   afterwards (auth logs for publickey logins).
4. **Enrich** (not done in this offline pass): AbuseIPDB/GreyNoise on the top source IPs, and a
   VirusTotal/threat-intel search on the key fingerprint.
5. **Preventive recommendation:** disable root SSH login and password auth (`PermitRootLogin no`,
   `PasswordAuthentication no`). Every implant here started with a password login as root.

## Detection notes and tuning

- **Alert volume:** 1,577 alerts for one campaign is noise in a real queue. With a licence tier that
  supports it, turn on alert suppression grouped by `source.ip` over 24h. Or add a Sigma correlation on the
  key comment, which would have produced **one** alert for the whole campaign.
- **Evasion gap:** the rule needs the literal `ssh-rsa`. Keys of type `ssh-ed25519` or
  `ecdsa-sha2-*`, or a key fetched with `curl … >> authorized_keys`, would miss it. A broader,
  file-centric variant: `cowrie.session.file_download` where `file.path` ends with
  `/.ssh/authorized_keys` (1,575 events here).
- **Case sensitivity:** pySigma's ES|QL output is case-sensitive (`like` on a keyword field), unlike
  Sigma's default. That's fine here; it would matter for mixed-case evasion.
