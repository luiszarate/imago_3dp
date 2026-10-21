"""B-01 (Creality parser, secrets) and B-03 (Creality URL is read-only)."""
import json
import logging
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import FAKE_SECRETS, FakeOpener, load_json, printer

from imago_bridge.drivers.base import CommandNotAllowed, DriverError
from imago_bridge.drivers.creality_box import (
    ALLOWED_QUERIES,
    CREALITY_FIELDS,
    SECRET_KEYS,
    CrealityBoxDriver,
    build_info_url,
    parse_info,
    pick_fields,
)
from imago_bridge.schema import build_push_payload


def parse(row):
    return parse_info(row, 12)


# ----------------------------------------------------------------- B-01 mapping
def test_idle_fixture():
    status = parse(load_json("creality_idle.json"))
    assert status.reachable is True
    assert status.state == "idle"
    assert status.nozzle_temp == 26.0 and status.bed_temp == 25.0
    assert status.nozzle_target is None and status.bed_target is None
    assert status.file_name is None  # "localhost" means no file
    assert status.layer is None and status.layer_total is None
    assert status.time_left_min is None and status.job_time_min is None


def test_preheat_is_idle_not_heating():
    status = parse(load_json("creality_preheat_idle.json"))
    assert status.state == "idle"
    assert status.nozzle_temp == 260.0


def test_printing_from_usb_has_unknown_progress():
    status = parse(load_json("creality_printing_usb.json"))
    assert status.state == "printing"
    assert status.progress is None
    assert status.file_name == "BASESE~1.GCO"
    assert status.job_time_min == 15  # printJobTime 873 s
    assert status.time_left_min is None  # printLeftTime is unreliable here


def test_printing_with_low_progress_keeps_value_but_no_eta():
    status = parse(load_json("creality_printing_progress1.json"))
    assert status.state == "printing"
    assert status.progress == 1.0
    assert status.time_left_min is None


def test_progress_over_five_gives_eta_and_layers():
    row = dict(load_json("creality_printing_usb.json"), printProgress=40, printLeftTime=3600, layer=12, TotalLayer=300)
    status = parse(row)
    assert status.progress == 40.0
    assert status.time_left_min == 60
    assert (status.layer, status.layer_total) == (12, 300)


def test_mcu_is_print_alone_means_printing():
    row = dict(load_json("creality_printing_usb.json"), state=0, mcu_is_print=1)
    assert parse(row).state == "printing"


@pytest.mark.parametrize(
    "changes, state",
    [
        ({"connect": 0}, "offline"),
        ({"err": 3}, "error"),
        ({"error": 7}, "error"),
        ({"pause": 1}, "paused"),
        ({"state": 2, "mcu_is_print": 0}, "finished"),
        ({"state": 9}, "unknown"),
        ({"state": "x"}, "unknown"),
    ],
)
def test_state_rules(changes, state):
    row = dict(load_json("creality_printing_usb.json"), **changes)
    assert parse(row).state == state


def test_error_text_carries_code():
    status = parse(dict(load_json("creality_idle.json"), err=3))
    assert status.error_text == "Error de impresora (código 3)"
    assert parse(load_json("creality_idle.json")).error_text is None


def test_connect_zero_is_reachable_box_but_offline_printer():
    status = parse(dict(load_json("creality_idle.json"), connect=0))
    assert (status.reachable, status.state) == (True, "offline")


# ----------------------------------------------------------------- B-01 secrets
def secret_row():
    return dict(load_json("creality_printing_usb.json"), **FAKE_SECRETS)


def test_fixtures_contain_no_secret_keys():
    for name in ("creality_idle.json", "creality_preheat_idle.json", "creality_printing_usb.json",
                 "creality_printing_progress1.json", "creality_timeout.json"):
        assert not set(SECRET_KEYS) & set(load_json(name)), name


def test_whitelist_drops_secrets():
    picked = pick_fields(secret_row())
    assert set(picked) <= set(CREALITY_FIELDS)
    assert not set(SECRET_KEYS) & set(picked)


def test_secrets_never_reach_payload_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    body = json.dumps(secret_row()).encode()
    driver = CrealityBoxDriver(printer(), opener=FakeOpener(body))
    status = driver.read()
    payload_text = json.dumps(build_push_payload([status]))
    for key, value in FAKE_SECRETS.items():
        assert value not in payload_text
        assert value not in caplog.text
        assert key not in status.to_payload()


# ----------------------------------------------------------------- driver I/O
def test_driver_reads_with_get_and_timeout():
    opener = FakeOpener(json.dumps(load_json("creality_idle.json")).encode())
    status = CrealityBoxDriver(printer(), opener=opener).read()
    request, timeout = opener.requests[0]
    assert status.state == "idle"
    assert request.get_method() == "GET"
    assert timeout == 3.0
    assert request.full_url == "http://192.168.0.248:81/protocal.csp?fname=Info&opt=main&function=get"


@pytest.mark.parametrize("failure", [URLError("timed out"), TimeoutError("timed out"), ConnectionRefusedError()])
def test_driver_wraps_network_errors(failure):
    with pytest.raises(DriverError):
        CrealityBoxDriver(printer(), opener=FakeOpener(failure)).read()


@pytest.mark.parametrize("body", [b"<html>", b"[1, 2]", b"x" * (64 * 1024 + 10)])
def test_driver_rejects_bad_bodies(body):
    with pytest.raises(DriverError):
        CrealityBoxDriver(printer(), opener=FakeOpener(body)).read()


def test_error_message_has_no_body(caplog):
    body = json.dumps(FAKE_SECRETS).encode()[:-1]  # truncated JSON containing fake secrets
    with pytest.raises(DriverError) as info:
        CrealityBoxDriver(printer(), opener=FakeOpener(body)).read()
    assert FAKE_SECRETS["wifipasswd"] not in str(info.value)


# ----------------------------------------------------------------- B-03 read-only URL
@pytest.mark.parametrize("host, port", [("192.168.0.248", 81), ("192.168.0.249", 81), ("10.0.0.5", 8081)])
def test_url_builder_only_uses_function_get(host, port):
    url = build_info_url(host, port)
    query = parse_qs(urlsplit(url).query)
    assert query["function"] == ["get"]
    assert "set" not in url
    assert urlsplit(url).query in ALLOWED_QUERIES


def test_url_builder_refuses_tampered_whitelist(monkeypatch):
    import imago_bridge.drivers.creality_box as module

    tampered = (("fname", "net"), ("opt", "iot_conf"), ("function", "set"), ("pause", "1"))
    monkeypatch.setattr(module, "INFO_QUERY", tampered)
    with pytest.raises(CommandNotAllowed):
        module.build_info_url("192.168.0.248", 81)


def test_driver_refuses_public_host():
    with pytest.raises(DriverError):
        CrealityBoxDriver(printer(host="8.8.8.8"))
