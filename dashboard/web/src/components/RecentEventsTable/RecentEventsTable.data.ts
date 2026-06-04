import type { PublicEvent } from '../../api/types';

/**
 * Final 30 events from the completed 14-day collection run (May 6-21, 2026),
 * pulled from the raw S3 Cowrie + HAProxy archives with session-level
 * correlation re-applied so each event carries its true source IP + GeoIP.
 * Non-dictionary passwords are masked to `<filtered:len=N>` per ADR-005 (the
 * <PasswordCell> renders these as bullet characters); top-20 safe-list
 * dictionary strings — the high-frequency botnet/spray credentials — render
 * verbatim.
 *
 * Captured-in-the-wild signals visible here:
 *   - `345gs5662d34` / `3245gs5662d34` as username AND password (Mirai-class
 *     bot's signature credential pair)
 *   - `mdrfckr` SSH-key implant command (a known Mirai persistence marker)
 *   - SHA `a8460f44…` file download (one of the 20 captured malware payloads
 *     archived to s3://…/captured-samples/)
 */
const DEFAULTS = {
  sensor: 'pi-cowrie',
  src_port: null,
  dst_ip: null,
  dst_port: null,
  protocol: 'ssh',
  message: null,
  username: null,
  password: null,
  input: null,
  url: null,
  shasum: null,
  duration: null,
  country: null,
  asn: null,
  asn_org: null,
} as const;

type Required_ = Pick<PublicEvent, 'eventid' | 'session' | 'src_ip' | 'ts'>;
function ev(p: Required_ & Partial<PublicEvent>): PublicEvent {
  return { ...DEFAULTS, ...p } as PublicEvent;
}

// Geo shorthands (every event in the sample resolved to one of three ASNs)
const KR = { country: 'South Korea', asn: 4766, asn_org: 'Korea Telecom' };
const KZ = { country: 'Kazakhstan', asn: 50482, asn_org: 'JSC Kazakhtelecom' };
const BR = { country: 'Brazil', asn: 7738, asn_org: 'V tal' };

const SHA_MIRAI = 'a8460f446be540410004b1a8db4083773fa46f7fe76fa84219c93daa1669f8f2';
const CMD_IMPLANT =
  'cd ~ && rm -rf .ssh && mkdir .ssh && echo "ssh-rsa AAAA…== mdrfckr">>.ssh/authorized_keys && chmod -R go= ~/.ssh && cd ~';
const CMD_CHATTR = 'cd ~; chattr -ia .ssh; lockr -ia .ssh';

export const RUN_EVENTS: PublicEvent[] = [
  ev({ eventid: 'cowrie.login.failed', session: '6a7e1b20e99f', src_ip: '118.34.22.227', ts: '2026-05-21T12:19:14.975528Z', username: 'hu', password: '<filtered:len=5>', ...KR }),
  ev({ eventid: 'cowrie.session.connect', session: '6a7e1b20e99f', src_ip: '118.34.22.227', ts: '2026-05-21T12:19:14.214146Z', src_port: 37548, dst_ip: '127.0.0.1', dst_port: 2223, ...KR }),
  ev({ eventid: 'cowrie.login.success', session: '47eeb08835eb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:55.075425Z', username: 'root', password: '3245gs5662d34', ...KZ }),
  ev({ eventid: 'cowrie.session.connect', session: '47eeb08835eb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:53.755706Z', src_port: 36494, dst_ip: '127.0.0.1', dst_port: 2223, ...KZ }),
  ev({ eventid: 'cowrie.login.failed', session: '9ab97b247f18', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:52.254435Z', username: '345gs5662d34', password: '345gs5662d34', ...KZ }),
  ev({ eventid: 'cowrie.session.connect', session: '9ab97b247f18', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:50.987794Z', src_port: 36488, dst_ip: '127.0.0.1', dst_port: 2223, ...KZ }),
  ev({ eventid: 'cowrie.session.file_download', session: '69672a5086bb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:50.729141Z', shasum: SHA_MIRAI, ...KZ }),
  ev({ eventid: 'cowrie.command.input', session: '69672a5086bb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:50.466021Z', input: CMD_IMPLANT, ...KZ }),
  ev({ eventid: 'cowrie.command.input', session: '69672a5086bb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:49.655087Z', input: CMD_CHATTR, ...KZ }),
  ev({ eventid: 'cowrie.login.success', session: '69672a5086bb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:49.087302Z', username: 'root', password: '<filtered:len=8>', ...KZ }),
  ev({ eventid: 'cowrie.session.connect', session: '69672a5086bb', src_ip: '212.154.234.9', ts: '2026-05-21T12:18:47.793476Z', src_port: 56174, dst_ip: '127.0.0.1', dst_port: 2223, ...KZ }),
  ev({ eventid: 'cowrie.login.success', session: 'ac74203eeed2', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:38.057040Z', username: 'root', password: '3245gs5662d34', ...BR }),
  ev({ eventid: 'cowrie.session.connect', session: 'ac74203eeed2', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:37.153712Z', src_port: 45732, dst_ip: '127.0.0.1', dst_port: 2223, ...BR }),
  ev({ eventid: 'cowrie.login.failed', session: '566a472d2625', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:35.816899Z', username: '345gs5662d34', password: '345gs5662d34', ...BR }),
  ev({ eventid: 'cowrie.session.connect', session: '566a472d2625', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:34.821457Z', src_port: 45716, dst_ip: '127.0.0.1', dst_port: 2223, ...BR }),
  ev({ eventid: 'cowrie.session.file_download', session: '6988dae7bb15', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:34.636965Z', shasum: SHA_MIRAI, ...BR }),
  ev({ eventid: 'cowrie.command.input', session: '6988dae7bb15', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:34.453871Z', input: CMD_IMPLANT, ...BR }),
  ev({ eventid: 'cowrie.command.input', session: '6988dae7bb15', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:33.826450Z', input: CMD_CHATTR, ...BR }),
  ev({ eventid: 'cowrie.login.success', session: '6988dae7bb15', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:33.418112Z', username: 'root', password: '<filtered:len=8>', ...BR }),
  ev({ eventid: 'cowrie.session.connect', session: '6988dae7bb15', src_ip: '200.141.47.232', ts: '2026-05-21T12:18:32.434795Z', src_port: 45710, dst_ip: '127.0.0.1', dst_port: 2223, ...BR }),
  ev({ eventid: 'cowrie.login.success', session: 'b3ca360b6184', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:59.428473Z', username: 'root', password: '3245gs5662d34', ...KR }),
  ev({ eventid: 'cowrie.session.connect', session: 'b3ca360b6184', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:58.656451Z', src_port: 51260, dst_ip: '127.0.0.1', dst_port: 2223, ...KR }),
  ev({ eventid: 'cowrie.login.failed', session: '27d3bd15659c', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:57.374088Z', username: '345gs5662d34', password: '345gs5662d34', ...KR }),
  ev({ eventid: 'cowrie.session.connect', session: '27d3bd15659c', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:56.593223Z', src_port: 51250, dst_ip: '127.0.0.1', dst_port: 2223, ...KR }),
  ev({ eventid: 'cowrie.session.file_download', session: 'ead1d7e83eb8', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:56.466030Z', shasum: SHA_MIRAI, ...KR }),
  ev({ eventid: 'cowrie.command.input', session: 'ead1d7e83eb8', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:56.301825Z', input: CMD_IMPLANT, ...KR }),
  ev({ eventid: 'cowrie.command.input', session: 'ead1d7e83eb8', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:55.788039Z', input: CMD_CHATTR, ...KR }),
  ev({ eventid: 'cowrie.login.success', session: 'ead1d7e83eb8', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:55.124043Z', username: 'root', password: '12345', ...KR }),
  ev({ eventid: 'cowrie.session.connect', session: 'ead1d7e83eb8', src_ip: '118.34.22.227', ts: '2026-05-21T12:17:54.342140Z', src_port: 51244, dst_ip: '127.0.0.1', dst_port: 2223, ...KR }),
  ev({ eventid: 'cowrie.login.failed', session: 'bea0a83d4ef2', src_ip: '212.154.234.9', ts: '2026-05-21T12:17:28.005279Z', username: 'socks', password: '<filtered:len=5>', ...KZ }),
];
