"""Payload contract (SPEC 16.6): exact keys, UTC 'Z' timestamp, valid states."""
import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from imago_bridge import __version__
from imago_bridge.schema import (
    PAYLOAD_KEYS,
    STATES,
    PrinterStatus,
    build_push_payload,
    offline_status,
    seconds_to_minutes,
    to_temperature,
    to_text,
    utc_timestamp,
)

SPEC_KEYS = {
    "workcenter_id", "reachable", "state", "progress", "nozzle_temp", "nozzle_target", "bed_temp",
    "bed_target", "layer", "layer_total", "time_left_min", "job_time_min", "file_name", "error_text",
    "snapshot_jpeg_b64",
}


def test_payload_item_has_exactly_spec_keys():
    status = PrinterStatus(workcenter_id=12, reachable=True, state="printing", progress=42.0)
    assert set(status.to_payload()) == SPEC_KEYS
    assert set(PAYLOAD_KEYS) == SPEC_KEYS


def test_push_payload_shape():
    moment = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone(timedelta(hours=-6)))
    payload = build_push_payload([offline_status(12), offline_status(13)], moment)
    assert set(payload) == {"bridge_version", "sent_at", "printers"}
    assert payload["bridge_version"] == __version__ == "0.2.0"
    assert payload["sent_at"] == "2026-10-21T16:00:00Z"
    assert [item["workcenter_id"] for item in payload["printers"]] == [12, 13]
    assert payload["printers"][0] == dict.fromkeys(SPEC_KEYS) | {"workcenter_id": 12, "reachable": False,
                                                                  "state": "offline"}
    json.dumps(payload)  # serialisable


def test_sent_at_defaults_to_now_utc():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", utc_timestamp())
    with pytest.raises(ValueError):
        utc_timestamp(datetime(2026, 10, 21))


def test_states_and_validation():
    assert STATES == ("offline", "idle", "printing", "paused", "finished", "error", "unknown")
    with pytest.raises(ValueError):
        PrinterStatus(workcenter_id=1, reachable=True, state="heating")
    with pytest.raises(ValueError):
        PrinterStatus(workcenter_id=True, reachable=True, state="idle")


def test_status_is_immutable():
    status = offline_status(1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.state = "idle"  # type: ignore[misc]


def test_normalisers():
    assert to_temperature(999) is None and to_temperature(-50) is None and to_temperature("21") == 21.0
    assert to_temperature(True) is None and to_temperature(float("nan")) is None
    assert to_text("  x" * 100, "file_name") == ("  x" * 100).strip()[:128]
    assert to_text("   ", "file_name") is None
    assert seconds_to_minutes(873) == 15 and seconds_to_minutes(0) is None and seconds_to_minutes("x") is None
