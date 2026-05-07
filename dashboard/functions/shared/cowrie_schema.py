from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Cowrie 2.x emits a long tail of event types beyond the original PROJECT_PLAN
# §4 set (e.g. cowrie.session.params, cowrie.log.closed, cowrie.client.var,
# cowrie.client.fingerprint, cowrie.command.success, etc.). Enumerating them
# all is brittle — every Cowrie point release adds something. Constrain by
# pattern instead: any string under the cowrie.* namespace, no whitespace.
# The downstream aggregator + dashboard only care about a known subset
# (login.success/failed, command.input, session.file_download); unknown
# types still write through and are simply not categorized in rollups.
EventId = Annotated[str, Field(pattern=r"^cowrie\.[A-Za-z0-9_.-]+$", min_length=8)]


class CowrieEvent(BaseModel):
    """Base schema covering every Cowrie event.

    Common-field invariants from ADR-001:
      - eventid, timestamp, src_ip, session, sensor are always present
      - uuid + protocol are present on most events
      - Other fields are event-type-specific; we keep them optional and
        validate the combinations in CowrieEventModel.check_fields.
    """

    # Phase 11A: extra="ignore" instead of "forbid". Cowrie 2.x evolves
    # event shapes per point release (cowrie.client.kex grew hasshAlgorithms
    # and langCS; cowrie.log.closed carries ttylog/size/duplicate;
    # cowrie.session.params carries arch). The schema's real safety net is
    # the field-level validators below (timestamp format, IP format, port
    # range, eventid pattern) — those still reject malformed values.
    # Allowing unknown fields to flow through prevents Cowrie's evolution
    # from silently dropping entire batches at the parser.
    #
    # IMPORTANT for future maintainers: "ignore" means "unknown fields
    # pass through silently" — NOT "no validation." The per-field
    # validators (timestamp format, IP format, port range, eventid
    # pattern) and the post-init `check_fields()` cross-field invariants
    # still apply with full force. If you find yourself wanting to relax
    # one of those, write a separate ADR — don't infer from this policy
    # that loose-extra means loose-everywhere.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)

    eventid: EventId
    timestamp: str
    src_ip: str
    session: Annotated[str, Field(min_length=1, max_length=64)]
    sensor: Annotated[str, Field(min_length=1)]

    uuid: str | None = None
    protocol: Literal["ssh", "telnet"] | None = None
    src_port: int | None = Field(default=None, ge=0, le=65535)
    dst_ip: str | None = None
    dst_port: int | None = Field(default=None, ge=0, le=65535)
    # Phase 11A: cowrie.session.params occasionally ships `message: []`
    # (an empty list rather than the usual human-readable string). Accept
    # both shapes; downstream consumers just render as text.
    message: str | list | None = None

    username: str | None = None
    password: str | None = None

    version: str | None = None
    hassh: str | None = None
    kexAlgs: list[str] | None = None
    keyAlgs: list[str] | None = None
    encCS: list[str] | None = None
    macCS: list[str] | None = None
    compCS: list[str] | None = None

    input: str | None = None

    url: str | None = None
    outfile: str | None = None
    shasum: str | None = None

    duration: float | None = Field(default=None, ge=0.0)

    @field_validator("timestamp")
    @classmethod
    def _iso8601_z(cls, v: str) -> str:
        # Accept Cowrie's ISO 8601 microsecond+Z form and validate parseability.
        # We do not coerce to datetime to preserve the wire format byte-for-byte.
        if not v.endswith("Z"):
            raise ValueError("timestamp must be ISO 8601 UTC with 'Z' suffix")
        # datetime.fromisoformat accepts the form when 'Z' is replaced with +00:00
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    @field_validator("src_ip", "dst_ip")
    @classmethod
    def _ip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        ip_address(v)
        return v

    def check_fields(self) -> None:
        """Cross-field validation: each eventid requires specific extras.

        Raises ValueError on mismatch. Called from the generator's
        post-build verification step and by the ingest pipeline.
        """
        match self.eventid:
            case "cowrie.login.failed" | "cowrie.login.success":
                if self.username is None or self.password is None:
                    raise ValueError(f"{self.eventid} requires username + password")
            case "cowrie.command.input":
                if self.input is None:
                    raise ValueError("cowrie.command.input requires input")
            case "cowrie.session.file_download":
                if self.url is None or self.shasum is None:
                    raise ValueError(
                        "cowrie.session.file_download requires url + shasum"
                    )
            case "cowrie.session.closed":
                if self.duration is None:
                    raise ValueError("cowrie.session.closed requires duration")
            case "cowrie.client.version":
                if self.version is None:
                    raise ValueError("cowrie.client.version requires version")
            case "cowrie.client.kex":
                if self.hassh is None:
                    raise ValueError("cowrie.client.kex requires hassh")
            case "cowrie.session.connect":
                if self.src_port is None or self.dst_port is None:
                    raise ValueError(
                        "cowrie.session.connect requires src_port + dst_port"
                    )


__all__ = ["CowrieEvent", "EventId"]
