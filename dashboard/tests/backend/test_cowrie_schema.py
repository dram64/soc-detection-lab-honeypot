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


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        CowrieEvent(
            eventid="cowrie.session.connect",
            timestamp="2026-04-27T23:19:26.097161Z",
            src_ip="192.0.2.5",
            session="abcd1234",
            sensor="honeypot",
            unknown_field="should fail",  # type: ignore[call-arg]
        )


def test_unknown_eventid_rejected() -> None:
    with pytest.raises(ValidationError):
        CowrieEvent(
            eventid="cowrie.unknown.bogus",  # type: ignore[arg-type]
            timestamp="2026-04-27T23:19:26.097161Z",
            src_ip="192.0.2.5",
            session="abcd1234",
            sensor="honeypot",
        )
