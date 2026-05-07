from __future__ import annotations

import pytest
from pydantic import ValidationError

from functions.shared.cowrie_schema import CowrieEvent


def _base_kwargs(eventid: str) -> dict[str, str]:
    return {
        "eventid": eventid,
        "timestamp": "2026-04-27T23:19:26.097161Z",
        "src_ip": "192.0.2.5",
        "session": "abcd1234",
        "sensor": "honeypot",
    }


def test_session_connect_valid() -> None:
    event = CowrieEvent(
        **_base_kwargs("cowrie.session.connect"),
        src_port=3592,
        dst_ip="192.168.1.253",
        dst_port=2222,
        protocol="ssh",
    )
    event.check_fields()


def test_session_connect_requires_ports() -> None:
    event = CowrieEvent(
        **_base_kwargs("cowrie.session.connect"),
        protocol="ssh",
    )
    with pytest.raises(ValueError, match="src_port"):
        event.check_fields()


def test_login_failed_requires_credentials() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.login.failed"))
    with pytest.raises(ValueError, match="username"):
        event.check_fields()


def test_command_input_requires_input() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.command.input"))
    with pytest.raises(ValueError, match="input"):
        event.check_fields()


def test_file_download_requires_url_and_shasum() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.session.file_download"))
    with pytest.raises(ValueError, match="url"):
        event.check_fields()


def test_session_closed_requires_duration() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.session.closed"))
    with pytest.raises(ValueError, match="duration"):
        event.check_fields()


def test_client_version_requires_version() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.client.version"))
    with pytest.raises(ValueError, match="version"):
        event.check_fields()


def test_client_kex_requires_hassh() -> None:
    event = CowrieEvent(**_base_kwargs("cowrie.client.kex"))
    with pytest.raises(ValueError, match="hassh"):
        event.check_fields()


def test_timestamp_must_be_z() -> None:
    with pytest.raises(ValidationError):
        CowrieEvent(
            eventid="cowrie.session.connect",
            timestamp="2026-04-27T23:19:26.097161+00:00",
            src_ip="192.0.2.5",
            session="abcd1234",
            sensor="honeypot",
        )


def test_invalid_ip_rejected() -> None:
    with pytest.raises(ValidationError):
        CowrieEvent(
            eventid="cowrie.session.connect",
            timestamp="2026-04-27T23:19:26.097161Z",
            src_ip="not-an-ip",
            session="abcd1234",
            sensor="honeypot",
        )


def test_extra_fields_silently_dropped() -> None:
    """Phase 11A: switched extra='forbid' to 'ignore' so Cowrie 2.x's
    per-version field churn (hasshAlgorithms, langCS, ttylog, arch, ...)
    doesn't drop entire batches at the parser. The schema's safety net
    moved from `extra` to the field-level validators below (timestamp
    format, IP format, port range, eventid pattern). Unknown fields
    drop silently — the parser only surfaces what downstream consumers
    declared as model attributes.
    """
    event = CowrieEvent(
        eventid="cowrie.session.connect",
        timestamp="2026-04-27T23:19:26.097161Z",
        src_ip="192.0.2.5",
        src_port=12345,
        dst_port=2222,
        session="abcd1234",
        sensor="honeypot",
        unknown_field="should be silently dropped",  # type: ignore[call-arg]
    )
    assert not hasattr(event, "unknown_field")


def test_unknown_eventid_under_cowrie_namespace_accepted() -> None:
    # Phase 10: EventId loosened from a closed Literal to a `cowrie.*`
    # pattern so new Cowrie point-release event types (e.g.
    # cowrie.session.params, cowrie.log.closed) flow through the ingest
    # without manual schema bumps. Downstream rollups still only count
    # the known subset.
    ev = CowrieEvent(
        eventid="cowrie.unknown.bogus",
        timestamp="2026-04-27T23:19:26.097161Z",
        src_ip="192.0.2.5",
        session="abcd1234",
        sensor="honeypot",
    )
    assert ev.eventid == "cowrie.unknown.bogus"


def test_eventid_outside_cowrie_namespace_rejected() -> None:
    with pytest.raises(ValidationError):
        CowrieEvent(
            eventid="apache.access",  # not under cowrie.* — fail
            timestamp="2026-04-27T23:19:26.097161Z",
            src_ip="192.0.2.5",
            session="abcd1234",
            sensor="honeypot",
        )
