# Investigations: Phase 2 offline detection & analysis

Analyst-style write-ups of the most significant detections from **replaying the archived 14-day
Cowrie run (May 6–21, 2026)** through the repo's Sigma rules in a local Elasticsearch + Kibana
stack ([elastic/](../../elastic/)). The detection engine ran once, in September 2026, over the
archived data. **Nothing here was detected live during collection.**

| # | Investigation | Rules | Alerts | Severity (lab) |
|---|---|---|---|---|
| [INV-01](01-botnet-credential-marker.md) | `345gs5662d34` credential marker: a post-implant check step of INV-02, not an independent (or Mirai) campaign | credential marker | 1,523 | medium |
| [INV-02](02-ssh-authorized-keys-implant.md) | `mdrfckr` SSH `authorized_keys` implant across 445 IPs | authorized_keys implant | 1,577 | high |
| [INV-03](03-crypto-mining-redtail.md) | RedTail miner kit uploads (2 hosts) + miner recon from the implant toolkit | miner payload upload, miner recon | 188 + 46 | high / medium |
| [INV-04](04-automated-scanners.md) | Brute-forcers, credential validators, scanners and SSH proxy abuse | brute force, credential stuffing, high-rate scanner, direct-tcpip | 1,054 + 168 + 219 + 130 | low–medium |

All 8 deployed rules: 4,905 alerts. Per-rule counts and the cross-check against each rule's query
are in [`elastic/evidence/alerts_summary.json`](../../elastic/evidence/alerts_summary.json).

## Ground rules used in every write-up

- **Source IPs are recovered, not observed.** Cowrie saw 127.0.0.1 for everything (reverse SSH
  tunnel). IPs come from an offline re-join against the HAProxy connection log: 95.9% of
  sessions were attributed, and the rest are marked "unattributed" and never guessed. See
  [elastic/README.md](../../elastic/README.md#source-ip-attribution).
- **Geo/ASN** is MaxMind GeoLite2 (country + ASN only). Hosting-range countries reflect registration data.
- **Passwords** are shown only when they're in the ADR-005 attack dictionary; everything else appears
  as `<filtered:len=N>`. Attacker-set passwords inside commands (`chpasswd`) are redacted in these
  write-ups.
- **No binaries** (ADR-009): payloads are identified by SHA-256 and file name only. Malware-family names
  (RedTail, "Outlaw") come from matching public reporting and are **not** confirmed by analysis.
- **No external enrichment** was run in this offline pass (no VirusTotal, AbuseIPDB or GreyNoise). Where
  a write-up recommends it, it says so explicitly.
- **"Success" means Cowrie accepted the login.** The honeypot accepts most root passwords by design; it
  isn't a real account compromise.
