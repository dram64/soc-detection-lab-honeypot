# INV-03: Cryptomining: RedTail kit uploads and miner reconnaissance

| | |
|---|---|
| **Data** | Phase 2 offline replay of the archived Cowrie run, May 6–21, 2026. The detection ran in Sept 2026, not live. |
| **Rules** | `[Sigma] Crypto-Miner Payload Uploaded to Honeypot (RedTail)` ([rule](../../sigma/rules/cowrie_miner_payload_upload.yml)), **high**: 188 alerts, 2 attributed IPs · `[Sigma] Crypto-Mining Host Reconnaissance Commands` ([rule](../../sigma/rules/cowrie_miner_recon.yml)), **medium**: 46 alerts, 13 IPs |
| **ATT&CK** (v19.2) | T1105 Ingress Tool Transfer (C2) · T1496.001 Compute Hijacking (Impact) · T1057 Process Discovery · T1082 System Information Discovery (Discovery). Observed but not detected by a dedicated rule: T1098.004 (a second SSH key), T1222.002 (`chattr +ai`) |
| **Verdict** | True positive. Two **separate** activity clusters: (a) a low-volume, persistent RedTail miner operator; (b) miner-oriented recon run by the `mdrfckr` implant toolkit. Severity **high** for (a); on a production host (a) is **critical** (a miner deployed). |

## Cluster A: RedTail kit delivery (the payload rule)

**Who:** effectively two hosts.

| Source IP | ASN | GeoLite2 country | Sessions with the kit | Active |
|---|---|---|---|---|
| 130.12.180.51 | AS202412 Omegatech LTD | Netherlands | 22 | May 7 05:41 → May 20 19:08 UTC |
| 213.209.159.158 | AS208137 Feo Prest SRL | Taiwan | 6 | May 7 17:46 → May 17 21:24 UTC |
| (unattributed) | n/a | n/a | 2 | May 14, May 18 |

GeoLite2 country for hosting ranges reflects registration data. Treat "Taiwan" for a
Feo Prest SRL range as a lookup result, not a physical location.

**What:** 32 sessions uploaded kit files over SCP/SFTP, 30 of them the complete kit. The per-file
hashes held steady across two weeks. Only the SHA-256 is recorded; no binaries were kept (ADR-009).

| File | SHA-256 | Uploads |
|---|---|---|
| `clean.sh` | `d46555af1173d22f07c37ef9c1e0e74fd68db022f2b6fb3ab5388d2c5bc6a98e` | 32 |
| `setup.sh` | `783adb7ad6b16fe9818f3e6d48b937c3ca1994ef24e50865282eeedeab7e0d59` | 30 |
| `redtail.arm7` | `3625d068896953595e75df328676a08bc071977ac1ff95d44b745bbcb7018c6f` | 32 |
| `redtail.arm8` | `dbb7ebb960dc0d5a480f97ddde3a227a2d83fcaca7d37ae672e6a0a6785631e9` | 32 |
| `redtail.i686` | `048e374baac36d8cf68dd32e48313ef8eb517d647548b1bf5f26d2d0e2e3cdc7` | 30 (+2 one-off variants) |
| `redtail.x86_64` | `59c29436755b0778e968d49feeae20ed65f5fa5e35f9f7965b8ed93420db91e5` | 30 |

### Representative session (`446af9f83595`, 2026-05-07, UTC): first sighting

| Time | Event | Detail |
|---|---|---|
| 05:40:47.148 | session.connect | 130.12.180.51 (AS202412 Omegatech LTD); HAProxy correlation *matched*, Δ 15.4 ms |
| 05:40:47.165 | client.version | `SSH-2.0-Go` |
| 05:40:47.858 | login.success | `root` / `<filtered:len=1>` (a 1-character password, redacted per ADR-005) |
| 05:41:38.682 | command.input | `chmod +x clean.sh; sh clean.sh; rm -rf clean.sh; chmod +x setup.sh; sh setup.sh; rm -rf setup.sh; mkdir -p ~/.ssh; chattr -ia ~/.ssh/authorized_keys; echo "ssh-rsa AAAA…rsa-key-20230629" > ~/.ssh/authorized_keys; chattr +ai ~/.ssh/authorized_keys; uname -a; echo -e "\x61\x75\x74\x68\x5F\x6F\x6B\x0A"` |
| 05:41:38.855 | session.file_download | `/root/.ssh/authorized_keys` written (SHA-256 `8a68d1c0…`) |
| 05:41:38.917–.932 | session.file_upload ×6 | `clean.sh`, `redtail.arm7`, `redtail.arm8`, `redtail.i686`, `redtail.x86_64`, `setup.sh` |

Reading the chain:
- **Multi-architecture drop:** four builds, so `setup.sh` can pick whichever runs on the host.
- **Competitor cleanup** (`clean.sh`) runs first, then the installer, and both scripts delete themselves.
- **Persistence with lock-in:** it plants its *own* key (`rsa-key-20230629`), replacing the file with
  `>`, then sets `chattr +ai` so nobody else (other bots included) can modify it. This is the second key in
  [INV-02](02-ssh-authorized-keys-implant.md). That rule caught it too (30 alerts).
- `echo -e "\x61…\x0A"` decodes to `auth_ok`: a success beacon for the operator's tooling.
- **Ordering caveat:** Cowrie logs SCP/SFTP uploads when the transfer channel closes, so the uploads
  show up after the command that uses them. The upload most likely happened first.

**Attribution:** the `redtail.<arch>` naming plus `setup.sh`/`clean.sh` match public reporting
on the RedTail cryptominer. The binaries weren't analysed here (ADR-009) and no hash lookups were done
in this offline pass, so the mining payload itself is **inferred from the file names and install
chain, not confirmed**.

**Pivot worth noting:** 213.209.159.158's ASN (AS208137 Feo Prest SRL) also hosts
213.209.159.56, one of the top brute-force sources (213 sessions; see
[INV-04](04-automated-scanners.md)). Same provider, not necessarily the same operator.

## Cluster B: miner reconnaissance (the recon rule)

46 commands from 13 attributed IPs in 23 sessions:

| Command | Count | Purpose |
|---|---|---|
| `cat /proc/cpuinfo \| grep name \| wc -l` | 16 | count CPU cores, i.e. how much hash rate |
| `cat /proc/cpuinfo \| grep model \| grep name \| wc -l` | 16 | same |
| `ps \| grep '[Mm]iner'` | 7 | is a rival miner already running? |
| `ps -ef \| grep '[Mm]iner'` | 7 | same |

- **6 of the 13** recon IPs also planted the `mdrfckr` key (INV-02). Their sessions run the implant, then
  a long fingerprinting script. Example session `0a25cbecc891`, 172.191.132.202 (AS8075 Microsoft
  Corporation, US), in order:
  - implant chain
  - `cat /proc/cpuinfo | grep name | wc -l`
  - `echo "root:<redacted>"|chpasswd|bash`: **changes the root password**, locking out the owner
    and rival bots. The value is redacted in this write-up; see the note below.
  - `rm -rf /tmp/secure.sh; rm -rf /tmp/auth.sh; pkill -9 secure.sh; pkill -9 auth.sh; echo > /etc/hosts.deny; pkill -9 sleep;`:
    kills known rival scripts and **empties `/etc/hosts.deny`**, removing host-based blocks
  - then `free -m`, `ls -lh $(which ls)`, `crontab -l`, `w`, `uname -m`, `top`, `lscpu`, `df -h`
- **None of the 13 recon IPs uploaded RedTail.** Recon and delivery are different actors in this
  dataset. No miner delivery was seen from cluster B during the 14 days.
- **Related context (no rule):** crypto-validator-themed usernames were tried from 12 IPs: `sol` 380,
  `solv` 193, `solana` 192, `validator` 64 attempts. That looks like targeting of Solana validator hosts.

> **Data note:** attacker commands are indexed verbatim (the same policy as the live dashboard). Any
> `chpasswd` argument is a password the *attacker* set on the decoy. It's still redacted in the
> write-ups to stay consistent with ADR-005's intent.

## Severity call

- **Cluster A: high** in the lab (a full miner kit plus a locked-in persistence key). On a production
  host it is **critical**: expect CPU exhaustion, cloud cost impact, and a backdoor key made immutable.
- **Cluster B: medium** on its own (discovery only). Raise it to high when paired with the INV-02 implant
  from the same IP, which is true for 6/13 IPs, and when the root password was changed (`chpasswd`).

## Tier-1 next steps / escalation

1. **Hash sweep:** search EDR/file-integrity data across the fleet for the six SHA-256s above and for
   files named `redtail.*`. Any hit → **escalate to IR** (the host is compromised and running a miner).
2. **Persistence check** on any matching host: `lsattr ~/.ssh/authorized_keys`, where an `a`/`i` flag set by
   someone other than the admins is a red flag. Look for the `rsa-key-20230629` / `mdrfckr` key comments, and at
   `/etc/hosts.deny` contents and recent `chpasswd` activity in auditd.
3. **Behavioral follow-up:** sustained high CPU on Linux hosts, and outbound connections to mining pools
   (stratum ports). No network telemetry exists in this lab, so this is advice, not something checked here.
4. **Block** 130.12.180.51 and 213.209.159.158. Both were stable for two weeks, so IP blocking is
   meaningful here, unlike INV-02. Consider a watch on AS208137 given the brute-force overlap.
5. **Enrich** (not done here): hash reputation (VirusTotal/MalwareBazaar) for the six hashes; ASN
   reputation for AS202412/AS208137.

## Detection notes and tuning

- The payload rule keys on **file names**, which are trivial to change. A hash-based companion rule (the
  6 SHA-256s) and a behavioral one (`chattr +ai` on `authorized_keys`) would survive renaming.
- The recon rule fires on legitimate admin checks too (`nproc`-style core counting). On real servers,
  pair it with an unusual source or a new login before alerting.
