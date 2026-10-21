"""Common printer status schema and the push payload (SPEC 16.6).

Every driver converts its raw reply into :class:`PrinterStatus`; nothing else ever
leaves the bridge. Odoo rejects unknown keys per printer, so ``to_payload`` emits
exactly ``PAYLOAD_KEYS``.
"""
import math
import re
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from . import __version__

STATES = ("offline", "idle", "printing", "paused", "finished", "error", "unknown")
TEMP_RANGE = (-20.0, 400.0)
TEXT_LIMITS = {"file_name": 128, "error_text": 256}
LOG_TEXT_LIMIT = 80
MAX_COUNT = 100000  # layers / minutes above this are garbage, not data
# C0/C1 control characters and Unicode bidi/direction marks (log and display spoofing).
_UNSAFE_CHARS = re.compile("[\x00-\x1f\x7f-\x9f\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")


@dataclass(frozen=True)
class PrinterStatus:
    workcenter_id: int
    reachable: bool
    state: str
    progress: Optional[float] = None
    nozzle_temp: Optional[float] = None
    nozzle_target: Optional[float] = None
    bed_temp: Optional[float] = None
    bed_target: Optional[float] = None
    layer: Optional[int] = None
    layer_total: Optional[int] = None
    time_left_min: Optional[int] = None
    job_time_min: Optional[int] = None
    file_name: Optional[str] = None
    error_text: Optional[str] = None
    snapshot_jpeg_b64: Optional[str] = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError("invalid printer state: %r" % (self.state,))
        if isinstance(self.workcenter_id, bool) or not isinstance(self.workcenter_id, int):
            raise ValueError("workcenter_id must be an int")

    def to_payload(self) -> Dict[str, Any]:
        """The printers[] item of SPEC 16.6: exactly these keys, None allowed."""
        return {name: getattr(self, name) for name in PAYLOAD_KEYS}

    def without_snapshot(self) -> "PrinterStatus":
        return replace(self, snapshot_jpeg_b64=None)


PAYLOAD_KEYS = tuple(field.name for field in fields(PrinterStatus))


def offline_status(workcenter_id: int) -> PrinterStatus:
    """Status reported when the bridge cannot reach the printer at all."""
    return PrinterStatus(workcenter_id=workcenter_id, reachable=False, state="offline")


def utc_timestamp(moment: Optional[datetime] = None) -> str:
    """UTC ISO-8601 with a trailing ``Z`` and second precision, e.g. 2026-10-21T16:00:00Z."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_push_payload(statuses: Iterable[PrinterStatus], moment: Optional[datetime] = None) -> Dict[str, Any]:
    return {
        "bridge_version": __version__,
        "sent_at": utc_timestamp(moment),
        "printers": [status.to_payload() for status in statuses],
    }


# ---------------------------------------------------------------------------
# Normalisation helpers shared by the drivers
# ---------------------------------------------------------------------------
def to_number(value: object) -> Optional[float]:
    """A finite float from an int/float/numeric string; None for anything else.

    Never raises: hostile values such as 10**400 (OverflowError), "1e999", NaN or a
    4 000-digit string become None.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and len(value) > 64:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def bounded_count(value: Optional[float]) -> Optional[int]:
    """A non-negative int up to MAX_COUNT; None when missing, negative or absurd."""
    if value is None or not 0 <= value <= MAX_COUNT:
        return None
    return int(round(value))


def to_count(value: object) -> Optional[int]:
    """A non-negative int (layers, minutes); None when missing, invalid or absurd."""
    return bounded_count(to_number(value))


def to_temperature(value: object) -> Optional[float]:
    """A temperature inside the range Odoo accepts; an absurd sensor value becomes None."""
    number = to_number(value)
    if number is None or not TEMP_RANGE[0] <= number <= TEMP_RANGE[1]:
        return None
    return number


def to_progress(value: object) -> Optional[float]:
    number = to_number(value)
    if number is None or not 0.0 <= number <= 100.0:
        return None
    return number


def clean_text(value: object, limit: int) -> Optional[str]:
    """Printer-supplied text without control/bidi characters, stripped and capped."""
    if not isinstance(value, str):
        return None
    text = _UNSAFE_CHARS.sub("", value[: limit * 4]).strip()
    return text[:limit] or None


def to_text(value: object, field_name: str) -> Optional[str]:
    return clean_text(value, TEXT_LIMITS[field_name])


def log_text(value: object) -> str:
    """Safe, short rendering of untrusted text for log lines."""
    return clean_text(value, LOG_TEXT_LIMIT) or "?"


def seconds_to_minutes(value: object) -> Optional[int]:
    seconds = to_number(value)
    if seconds is None or seconds <= 0:
        return None
    return bounded_count(seconds / 60.0)
