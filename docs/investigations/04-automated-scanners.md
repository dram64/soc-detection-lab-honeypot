# INV-04: Automated SSH scanners, brute-forcers, credential validators and proxy abuse

| | |
|---|---|
| **Data** | Phase 2 offline replay of the archived Cowrie run, May 6–21, 2026. The detection ran in Sept 2026, not live. |
| **Rules** | `SSH Brute Force Attack` ([rule](../../sigma/rules/ssh_brute_force.yml)), **medium**: 1,054 alerts / 73 IPs · `Credential Stuffing — Multiple Usernames from Single Source` ([rule](../../sigma/rules/credential_stuffing.yml)), **high**: 168 / 30 · `High-Rate Automated SSH Scanner From Single Source` ([rule](../../sigma/rules/cowrie_automated_ssh_client.yml)), **low**: 219 / 130 · `SSH Port-Forward (direct-tcpip) Request Through Honeypot` ([rule](../../sigma/rules/cowrie_direct_tcpip_proxy.yml)), **medium**: 130 / 37 |
| **ATT&CK** (v19.2) | T1110.001 Password Guessing · T1110.004 Credential Stuffing (Credential Access) · T1595 Active Scanning (Reconnaissance) · T1090 Proxy (C2) |
| **Verdict** | True positives, and most of the run's volume. Four distinct behaviours, each with a different right response. Low-to-medium severity individually. |

The three correlation rules are ES|QL `stats` over **tumbling** buckets (`date_trunc(5m|10m|1h)`),
grouped by `source.ip`. Unattributed events (no recovered source IP) are excluded, so they can't
collapse into one fake "null" attacker.

## 1. Brute force / credential stuffing: two very different operators

| Operator (ASN) | IPs | Behaviour | Brute-force alerts |
|---|---|---|---|
| **AS47890 Unmanaged Ltd** (2.57.121.112, 2.57.121.25, …) | 3 | **Low and slow, all two weeks.** 2.57.121.112: 1,151 failures, May 7 → May 21, cycling a *short* username list (`admin` 1,173, `user` 1,046, `sol` 365, `ubuntu` 328, `solv` 189 across the ASN). The banner claims `SSH-2.0-PuTTY_Release_0.83` (~160 sessions per IP) but it alternates with `libssh2_1.9.0`, and PuTTY is an interactive client, so the banner is almost certainly spoofed. | **458** (43% of all) |
| **AS208137 Feo Prest SRL** (213.209.159.56) | 1–2 | Same PuTTY/libssh2 banner pattern as AS47890; 1,056 failures over 210 usernames, May 7 → May 21. | 214 |
| **AS51396 Pfcloud UG** (45.156.87.204, 176.65.132.129, 45.153.34.112, 192.109.200.x, …) | 24 in the ASN (8 trip the rule) | **Bursts.** 10,120 sessions; each IP walks the *same* ~315-username list (`root`, `user`, `admin`, `ubuntu`, `test`, `deploy`, `minecraft`, `postgres`, `steam`, `oracle`, `git`, …) in ~40-minute bursts. GeoLite2 places the IPs in Germany, the Netherlands and Bulgaria: one provider, three countries. | 140 |

- **Credential stuffing** (≥10 distinct usernames from one IP in a 10-minute bucket) is dominated by
  Pfcloud: 45.156.87.204 tripped it in 26 buckets with up to **111 usernames in 10 minutes**, and
  176.65.132.129, 45.153.34.112 and 192.109.200.237 each tripped it 9–13 times with ~105–110 usernames.
- **Why the two rules disagree:** the brute-force rule counts attempts and the stuffing rule counts
  username diversity. AS47890's slow, narrow list trips brute force (≥5 failures per 5 min) hundreds of
  times but barely touches stuffing. Pfcloud's bursts trip both. Running both rules is what separates the
  two operators.
- 2,404 Pfcloud logins "succeeded". That's Cowrie accepting the credential, not a real compromise.
  The follow-up was fingerprinting only: `uname -s -v -n -r -m` 2,387 times from 7 IPs, plus 7×
  `uname -a ; echo 'vT'`. No payload upload or persistence followed. Three Pfcloud IPs each made one
  direct-tcpip request back to **their own IP** on port 80, a relay self-test (§4). The pattern is: find valid
  credentials, fingerprint the OS, and leave exploitation for later (or for someone else).

## 2. Credential validators: two hosts that skew the geography

The replay's #1 and #4 source "countries" by session count are **single hosts**:

| Host | ASN | Window (UTC) | Sessions | What it did |
|---|---|---|---|---|
| 93.188.83.96 | AS8193 Uzbektelekom | May 15 07:19 → 11:06 (3 h 47 m) | **5,937** (all of Uzbekistan's attributed sessions) | 5,927 successful `root` logins with rotating passwords; every session ran exactly one command, `echo -e "\x6F\x6B"` (prints `ok`), then disconnected |
| 102.113.248.95 | AS23889 MauritiusTelecom | May 14 15:14 → 17:18 (2 h 4 m) | **2,432** (of Mauritius's 2,438) | identical: 2,431 root logins, one `echo "ok"` each |

- Both used `SSH-2.0-Go`, and both sent one `GET / HTTP/1.1` to the SSH port first (a protocol probe).
- This is **credential validation**: confirm which root passwords "work" and that a shell runs, then
  move on. A list like that typically gets used or sold later. Cowrie accepts most root passwords by
  design, so every attempt "worked", which also means the honeypot probably ended up on the
  operator's list of valid hosts.
- These two hosts are the largest *by volume* in the high-rate scanner rule, though only 8 of its 219
  alerts: 93.188.83.96 tripped 5 hour-buckets, peaking at **1,654 sessions/hour**.
- **Analyst lesson:** "top countries by volume" on the origin dashboard reads Uzbekistan #1 and
  Mauritius #4. Counted by **distinct IPs**, both nearly disappear. Always check the IP count before
  reporting a country trend.

## 3. Scanners and survey traffic (the low-severity rule)

| Client banner | Events | Source IPs |
|---|---|---|
| `SSH-2.0-Go` | 27,188 | 354 |
| `SSH-2.0-libssh_0.9.6` | 5,328 | 406 |
| `SSH-2.0-PuTTY_Release_0.83` (spoofed, see §1) | 552 | 4 |
| RDP X.224 request, `Cookie: mstshash=hello` | 518 | 11 |
| Nmap / ZGrab survey banners | 135 from **AS396982 Google LLC** (65 IPs) | 65 |

- Top HASSH fingerprints: `0a07365c…` (14,243 kex from 30 IPs), `01ca3558…` (8,723 from 5), and
  `f555226d…` (5,314 from 406 IPs, which lines up with libssh 0.9.6, the INV-01/02 campaign).
- **RDP probes on port 22:** `Cookie: mstshash=hello` is the opening of an RDP connection request, sent
  blind to the SSH port. It came mostly from two DigitalOcean hosts (152.42.212.128: 271, 167.172.81.52:
  172). These are port-agnostic scanners, harmless here.
- **Nmap/ZGrab from Google Cloud** matches commercial internet-survey services. It's low value and a good
  candidate for an allow-list/suppression, since no rule alerts on it at its volume.

## 4. SSH proxy abuse: direct-tcpip (the proxy rule)

130 requests from 37 IPs asked the honeypot to open TCP connections onward. Cowrie logs them and doesn't relay:

| Destination | Requests | Source | Reading |
|---|---|---|---|
| `141.101.90.1:3478` | 60 | 45.148.10.121, AS48090 Techoff Srv Limited (58), May 7 → May 21 | Payload `GET / HTTP/1.1 Host: turn.cloudflare.com:3478`: testing whether the host can reach Cloudflare's TURN/STUN relay, i.e. proxy-capability checks |
| `ip-who.com:80` | 24 | 15 IPs, mostly Viettel | IP-echo service: "what's my egress IP through this host?", standard proxy validation |
| `81.19.77.166:587` | 8 | 193.46.255.86, **AS47890 Unmanaged Ltd** | **SMTP submission port**, a probable test of the host as a spam relay. Same ASN as the §1 brute-forcer. |
| `google.com:80/443` | 14 | several | connectivity checks |

## Severity call

| Behaviour | Lab | Production equivalent |
|---|---|---|
| Brute force / stuffing | medium | **medium**; high if any attempt succeeds against a real account |
| Credential validators | medium | **high** if a validator got a working login: the host is on a valid-credentials list |
| Scanners / survey | low | low (internet background noise) |
| direct-tcpip proxy | medium | **high**: a real host relaying attacker traffic (spam, proxying) is abuse with legal and reputational exposure |

## Tier-1 next steps / escalation

1. **Brute force / stuffing:** confirm there are no *successful* logins from the IP against real accounts
   (on real servers: auth logs, `event.outcome: success`). If there are none, block at the edge (fail2ban/
   firewall) and close. Pfcloud (AS51396) and Unmanaged Ltd (AS47890) are candidates for ASN-level
   rate limits: both are persistent, multi-IP operations. Any success → escalate as a compromised account.
2. **Validators:** treat a *successful* login followed by a one-shot `echo` as a
   compromised-credential event. Rotate the credential and escalate. Here it's expected (Cowrie
   accepts everything).
3. **Proxy abuse:** on a real host, disable forwarding (`AllowTcpForwarding no`, `PermitOpen none`),
   and escalate if any direct-tcpip channel actually connected (network logs), especially to port 587.
4. **Scanners:** suppress known survey sources (Google-hosted Nmap/ZGrab) so they stay out of the queue.
5. **Enrich** (not done in this offline pass): GreyNoise would likely classify most of §3 as known
   scanners, which is the fastest way to deprioritize them.

## Detection notes and tuning

- **Volume vs. value:** 1,054 brute-force alerts, 458 of them from 3 IPs, is the classic reason to add
  alert suppression per `source.ip` or to raise thresholds. The alerts are all *correct*; they just aren't
  individually actionable.
- **Tumbling windows:** a burst straddling a bucket edge can be split and missed (for example, 4 failures
  at 12:04 and 4 at 12:06 never make 5 in one bucket). A sliding-window correlation (EQL sequence, or
  Sigma → a SIEM with sliding windows) would be more faithful to the Sigma `timespan` intent.
- **Spoofed banners:** the PuTTY banner from AS47890/AS208137 shows client-version rules are easy to evade.
  HASSH (key-exchange fingerprint) is harder to fake and would be the better pivot.
