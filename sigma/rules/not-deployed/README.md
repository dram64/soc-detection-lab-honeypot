# Not deployed — rules with no data source in this lab

These three rules were written for a multi-source SOC design (network IDS,
network metadata, threat-intel feed) that was scoped but **never built**. This
lab's only telemetry is the Cowrie honeypot + HAProxy connection logs from the
14-day run (May 6–21, 2026), so none of these can fire here. They are kept as
authored detection logic, not as a claimed capability.

| Rule | Required log source | Why it can't run here |
|---|---|---|
| [`known_bad_ip_match.yml`](known_bad_ip_match.yml) | Suricata `flow` events + a MISP IOC feed (`%MISP_BAD_IPS%` placeholder) | No Suricata sensor, no MISP instance |
| [`lateral_movement_smb.yml`](lateral_movement_smb.yml) | Zeek `smb` logs | No Zeek sensor; also no internal network to move laterally in |
| [`unusual_outbound_ports.yml`](unusual_outbound_ports.yml) | Zeek `conn` logs with a `direction` field | No Zeek sensor |

All three are `status: experimental`. They were previously marked `stable`,
which overstated them: they had never been run against any data.

## Known issues (fix before ever deploying)

- `lateral_movement_smb.yml`: the `off_hours` selection requires
  `timestamp_hour >= 22` **and** `timestamp_hour < 6` in the same selection,
  which can never be true, so the rule as written can never match. It needs two
  selections OR-ed together (`hour >= 22` or `hour < 6`). Left unfixed on
  purpose: there is no data here to test a fix against.
- `known_bad_ip_match.yml` depends on a placeholder (`%MISP_BAD_IPS%`) that has
  to be expanded from a real feed at conversion time.

## Related, but not the same rule

The honeypot data does contain 130 `cowrie.direct-tcpip.request` events, where
attackers asked the honeypot to open outbound TCP connections for them. That
is **SSH proxy/tunnel abuse** (ATT&CK T1090), not the Zeek port-anomaly idea
behind `unusual_outbound_ports.yml`. It is detected by its own rule,
[`../cowrie_direct_tcpip_proxy.yml`](../cowrie_direct_tcpip_proxy.yml), with its own ID.
