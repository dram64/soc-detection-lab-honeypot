# INV-01: `345gs5662d34` credential marker (previously labelled "Mirai")

| | |
|---|---|
| **Data** | Phase 2 offline replay of the archived Cowrie run, May 6–21, 2026. The detection ran in Sept 2026, not live. |
| **Rule** | `[Sigma] Known Botnet Credential Marker Used Against SSH (345gs5662d34)` ([rule](../../sigma/rules/cowrie_botnet_credential_marker.yml)), severity **medium** |
| **Alerts** | 1,523 (one per login attempt), 438 distinct source IPs |
| **ATT&CK** (v19.2) | T1110.001 Password Guessing (Credential Access) |
| **Verdict** | True positive, but **not an independent campaign**: it is a post-implant check step of the `mdrfckr` SSH-key campaign ([INV-02](02-ssh-authorized-keys-implant.md)). Severity **medium** on its own. The finding that matters is the link to INV-02. |

## Correction to earlier project text

The Phase 1 README described `345gs5662d34` as a "Mirai credential marker". **Nothing in this
dataset supports that attribution.** Every one of these logins came over SSH from libssh clients
and was tied, IP for IP, to the SSH-key implant campaign. Nothing Mirai-specific appears around
it: no busybox probing, no binary download.

This is *unsupported*, not *disproven*. The ingress only forwarded TCP/22 (every HAProxy record
has `frontend_port=22`), so Telnet-borne Mirai traffic could never have reached this sensor. The
"Mirai" label is withdrawn, and the README now says "botnet credential marker".

## What fired

```
from cowrie-* metadata _id, _index, _version
| where (event.action in ("cowrie.login.failed", "cowrie.login.success")) and user.name=="345gs5662d34"
```

The rule matches on the **username** only. The attempted password is outside the ADR-005 dictionary, so it
was indexed as `<filtered:len=12>` and the raw value never reached Elasticsearch. The rule doesn't need it.

## Evidence

| Fact | Value |
|---|---|
| Attempts | 1,523, **all failed** (`event.outcome: failure`); Cowrie rejected the credential every time |
| Sessions | 1,523: exactly one attempt per session; nothing else happens in these sessions |
| Session event mix | connect → client.version → kex → login.failed → closed (1,523 each) |
| First / last seen | 2026-05-14 14:25 UTC → 2026-05-21 12:18 UTC (end of run) |
| Per day | 90 (May 14), 256, 285, 232, 138, 140, 193, 189 (May 21) |
| Source IPs | 438 attributed; 49 attempts unattributed (no source IP recovered) |
| Client banners | `SSH-2.0-libssh_0.9.6` 1,360 · `libssh_0.12.0` 113 · `libssh_0.11.1` 50 |

| Top source ASNs | Attempts | IPs |
|---|---|---|
| AS132203 Tencent Building, Kejizhongyi Avenue | 337 | 106 |
| AS8075 Microsoft Corporation | 125 | 18 |
| AS4766 Korea Telecom | 57 | 13 |
| AS135377 UCLOUD Information Technology HK | 55 | 20 |
| AS7552 Viettel Group | 43 | 3 |

Top countries: United States 335 attempts / 90 IPs, Singapore 166 / 63, South Korea 90 / 20,
Hong Kong 74 / 26, India 71 / 19.

## The pivot: same IPs, same tooling as the key implant

- **430 of the 438** marker IPs also ran the `mdrfckr` implant command (INV-02).
- For **391 of 452** IPs seen in either activity, the number of marker attempts **equals** the
  number of `authorized_keys` writes, 1:1.
- Same client banners (libssh 0.9.6 / 0.12.0 / 0.11.1), same ASN mix (Tencent, Microsoft, Korea
  Telecom, UCLOUD, Viettel).
- The timing puts the marker **after** the implant. Example: 20.203.42.204 (AS8075 Microsoft), all times UTC:

| Time | Session | Event |
|---|---|---|
| 00:44:35.347 | `47ba31bada94` | login.success `root` |
| 00:44:37.337 | `47ba31bada94` | `authorized_keys` written (implant) |
| 00:44:38.850 | `8991cef52e4b` | login.failed `345gs5662d34` ← marker, ~1.5 s later, new session |
| 00:44:41.645 | `8ec954d2a6ba` | login.success `root`, next cycle |
| 00:47:17.049 | `59f6b3766cfb` | login.success `root` |
| 00:47:19.245 | `59f6b3766cfb` | `authorized_keys` written |
| 00:47:20.757 | `52c31f0c0bcf` | login.failed `345gs5662d34` |

**Interpretation (inference):** after planting its key, the bot opens a new session with a fixed
credential that no real host should accept. That could be a honeypot check (a host that accepts
nonsense credentials is a trap) or a campaign marker. The data shows *what* happens and in what
order; the *why* is my reading, not a confirmed fact.

## Severity call

- **On its own: medium.** Every attempt failed, and there was no session activity.
- **In context: escalate as part of INV-02 (high).** The marker is a cheap, very high-fidelity
  **leading indicator** for the implant campaign: no legitimate user will ever type this username.

## Tier-1 next steps / escalation

1. **Pivot on the source IP** to the implant detection (INV-02) for the same IP within ±5 minutes.
   Here, 430/438 IPs have one. On a production host, a match means assume compromise and escalate
   to Tier 2/IR.
2. **Check whether any login attempt succeeded** for that IP (`event.outcome: success`). This
   credential never succeeded, but the IP's *other* logins (root + password) did.
3. **Blocklist** the source IPs at the SSH edge for the campaign window. Treat it as short-lived: the
   IP set is a botnet of compromised cloud and ISP hosts, and many of them are victims too.
4. **Enrich** (not done in this offline pass): AbuseIPDB/GreyNoise for the top IPs; abuse
   reports to Tencent Cloud and Microsoft for the top ASNs.

## Detection notes and tuning

- This is the highest-fidelity rule in the set: zero false-positive risk, and it detects the campaign
  even when the implant command is obfuscated.
- **Better as a correlation:** a Sigma `temporal` correlation of "marker login + authorized_keys write
  from the same `source.ip` within 5 minutes" would raise one high-confidence alert per compromised
  host instead of two separate alert streams.
