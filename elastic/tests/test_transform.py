from __future__ import annotations

import json
from typing import Any

import pytest

from soc_elastic.correlate import AMBIGUOUS, MATCHED, Attribution
from soc_elastic.geo import GeoLookup
from soc_elastic.transform import MAX_TCPIP_DATA, doc_id, index_name, to_ecs

from .conftest import FakeAsn, FakeCountry

ATTR = Attribution(
    status=MATCHED,
    source_ip="203.0.113.5",
    source_port=51000,
    candidate_ips=("203.0.113.5",),
    haproxy_ts="2026-05-10T12:00:00.750000+00:00",
    delta_ms=250.0,
)
UNATTR = Attribution(status=AMBIGUOUS, candidate_ips=("198.51.100.7", "198.51.100.9"))


def base(eventid: str, **extra: Any) -> dict[str, Any]:
    return {
        "eventid": eventid,
        "timestamp": "2026-05-10T12:00:01.000000Z",
        "src_ip": "127.0.0.1",
        "session": "abc123def456",
        "sensor": "honeypot",
        "protocol": "ssh",
        "uuid": "u",
        "fluent_host": "pi",
        **extra,
    }


@pytest.fixture
def geo() -> GeoLookup:
    return GeoLookup(
        FakeCountry({"203.0.113.5": ("NL", "Netherlands")}),
        FakeAsn({"203.0.113.5": (64500, "Example Hosting BV")}),
    )


def test_non_dictionary_password_is_redacted_and_never_serialized(
    geo: GeoLookup, dictionary: frozenset[str]
) -> None:
    secret = "Tr0ub4dor&3-real-looking"
    raw = base(
        "cowrie.login.success",
        username="root",
        password=secret,
        message=f"login attempt [root/{secret}] succeeded",
    )
    doc = to_ecs(raw, ATTR, geo=geo, dictionary=dictionary)
    assert doc["cowrie"]["password"] == f"<filtered:len={len(secret)}>"
    assert "message" not in doc  # Cowrie repeats the password inside message
    assert secret not in json.dumps(doc)
    assert "original" not in doc["event"]


def test_dictionary_password_is_kept(geo: GeoLookup, dictionary: frozenset[str]) -> None:
    raw = base(
        "cowrie.login.failed",
        username="admin",
        password="123456",
        message="login attempt [admin/123456] failed",
    )
    doc = to_ecs(raw, ATTR, geo=geo, dictionary=dictionary)
    assert doc["cowrie"]["password"] == "123456"
    assert doc["event"]["outcome"] == "failure"
    assert doc["event"]["category"] == ["authentication"]
    assert doc["user"]["name"] == "admin"
    assert doc["related"]["user"] == ["admin"]


def test_publickey_attempt_keeps_message_and_fingerprint(
    geo: GeoLookup, dictionary: frozenset[str]
) -> None:
    raw = base(
        "cowrie.login.failed",
        username="root",
        type="ssh-rsa",
        fingerprint="aa:bb",
        message="public key login attempt for [root] failed",
    )
    doc = to_ecs(raw, ATTR, geo=geo, dictionary=dictionary)
    assert doc["message"].startswith("public key login attempt")
    assert doc["cowrie"]["auth"] == {"type": "ssh-rsa", "key_fingerprint": "aa:bb"}
    assert "password" not in doc["cowrie"]


def test_attributed_event_gets_source_geo_asn_and_correlation(
    geo: GeoLookup, dictionary: frozenset[str]
) -> None:
    raw = base("cowrie.session.connect", src_port=37066, dst_ip="127.0.0.1", dst_port=2223)
    doc = to_ecs(raw, ATTR, geo=geo, dictionary=dictionary)
    src = doc["source"]
    assert src["ip"] == "203.0.113.5"
    assert src["port"] == 51000  # the attacker's port from HAProxy, not the tunnel port
    assert src["geo"] == {"country_iso_code": "NL", "country_name": "Netherlands"}
    assert src["as"] == {"number": 64500, "organization": {"name": "Example Hosting BV"}}
    assert doc["related"]["ip"] == ["203.0.113.5"]
    assert doc["cowrie"]["src_ip"] == "127.0.0.1"
    assert doc["cowrie"]["correlation"]["status"] == MATCHED
    assert doc["cowrie"]["correlation"]["delta_ms"] == 250.0
    assert "destination" not in doc  # honeypot-side 127.0.0.1:2223 is not a destination


def test_unattributed_event_has_no_source_but_keeps_candidates(
    geo: GeoLookup, dictionary: frozenset[str]
) -> None:
    raw = base("cowrie.command.input", input="uname -a")
    doc = to_ecs(raw, UNATTR, geo=geo, dictionary=dictionary)
    assert "source" not in doc
    assert "related" not in doc
    corr = doc["cowrie"]["correlation"]
    assert corr["status"] == AMBIGUOUS
    assert corr["candidate_count"] == 2
    assert doc["process"]["command_line"] == "uname -a"
    assert doc["event"]["category"] == ["process"]


def test_command_failed_outcome_and_no_geo_reader(dictionary: frozenset[str]) -> None:
    raw = base("cowrie.command.failed", input="lockr -ia .ssh")
    doc = to_ecs(raw, ATTR, geo=None, dictionary=dictionary)
    assert doc["event"]["outcome"] == "failure"
    assert doc["process"]["command_line"] == "lockr -ia .ssh"
    assert "geo" not in doc["source"]  # no reader -> fields omitted, never faked


def test_file_upload_maps_hash_and_name(dictionary: frozenset[str]) -> None:
    sha = "3625d068896953595e75df328676a08bc071977ac1ff95d44b745bbcb7018c6f"
    raw = base(
        "cowrie.session.file_upload",
        filename="redtail.arm7",
        shasum=sha,
        outfile=f"var/lib/cowrie/downloads/{sha}",
    )
    doc = to_ecs(raw, ATTR, geo=None, dictionary=dictionary)
    assert doc["file"] == {"name": "redtail.arm7", "hash": {"sha256": sha}}
    assert doc["related"]["hash"] == [sha]
    assert doc["event"]["category"] == ["file"]


def test_file_download_maps_destination_path(dictionary: frozenset[str]) -> None:
    raw = base(
        "cowrie.session.file_download",
        shasum="ab" * 32,
        destfile="/root/.ssh/authorized_keys",
        duplicate=True,
    )
    doc = to_ecs(raw, ATTR, geo=None, dictionary=dictionary)
    assert doc["file"]["path"] == "/root/.ssh/authorized_keys"
    assert doc["cowrie"]["duplicate"] is True


def test_log_closed_hash_goes_to_ttylog_not_file(dictionary: frozenset[str]) -> None:
    raw = base(
        "cowrie.log.closed",
        shasum="cd" * 32,
        ttylog="var/lib/cowrie/tty/x",
        size=512,
        duration=3.5,
        duplicate=False,
    )
    doc = to_ecs(raw, ATTR, geo=None, dictionary=dictionary)
    assert "file" not in doc
    assert "hash" not in doc["related"]
    assert doc["cowrie"]["ttylog"] == {
        "path": "var/lib/cowrie/tty/x",
        "size": 512,
        "sha256": "cd" * 32,
    }
    assert doc["cowrie"]["duplicate"] is False


def test_session_closed_duration_in_nanoseconds(dictionary: frozenset[str]) -> None:
    doc = to_ecs(base("cowrie.session.closed", duration=1.5), ATTR, geo=None, dictionary=dictionary)
    assert doc["event"]["duration"] == 1_500_000_000
    assert doc["cowrie"]["duration_s"] == 1.5
    assert doc["event"]["type"] == ["end"]


def test_direct_tcpip_hostname_vs_ip_and_data_truncation(dictionary: frozenset[str]) -> None:
    host = to_ecs(
        base("cowrie.direct-tcpip.request", dst_ip="ip-who.com", dst_port=80, src_port=0),
        ATTR,
        geo=None,
        dictionary=dictionary,
    )
    assert host["destination"] == {"address": "ip-who.com", "port": 80}
    data = to_ecs(
        base(
            "cowrie.direct-tcpip.data",
            dst_ip="192.0.2.10",
            dst_port=3478,
            data="x" * (MAX_TCPIP_DATA + 10),
        ),
        ATTR,
        geo=None,
        dictionary=dictionary,
    )
    assert data["destination"]["ip"] == "192.0.2.10"
    assert len(data["cowrie"]["direct_tcpip"]["data"]) == MAX_TCPIP_DATA


def test_client_version_kex_and_default_classification(dictionary: frozenset[str]) -> None:
    ver = to_ecs(
        base("cowrie.client.version", version="SSH-2.0-Go"), ATTR, geo=None, dictionary=dictionary
    )
    assert ver["cowrie"]["client"]["version"] == "SSH-2.0-Go"
    assert ver["event"]["category"] == ["network"]
    assert ver["event"]["type"] == ["info"]
    kex = to_ecs(base("cowrie.client.kex", hassh="0a07"), ATTR, geo=None, dictionary=dictionary)
    assert kex["cowrie"]["client"]["hassh"] == "0a07"


def test_list_message_is_dropped(dictionary: frozenset[str]) -> None:
    raw = base("cowrie.session.params", arch="linux-x64-lsb", message=[])
    doc = to_ecs(raw, ATTR, geo=None, dictionary=dictionary)
    assert "message" not in doc
    assert doc["cowrie"]["arch"] == "linux-x64-lsb"


def test_geo_lookup_unknown_and_invalid_ips() -> None:
    g = GeoLookup(FakeCountry({}), FakeAsn({}))
    assert g.lookup("not-an-ip").country_iso_code is None
    miss = g.lookup("192.0.2.1")
    assert (miss.country_iso_code, miss.asn) == (None, None)


def test_doc_id_matches_production_scheme_and_index_name() -> None:
    raw = base("cowrie.session.connect")
    assert doc_id(raw) == doc_id(dict(raw))
    assert len(doc_id(raw)) == 40
    assert doc_id(raw) != doc_id(base("cowrie.session.closed"))
    assert index_name("cowrie", "2026-05-21T23:59:59.000000Z") == "cowrie-2026.05"
