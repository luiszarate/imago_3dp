"""Security review fixes 2-4: hostile numbers, control characters and absurd integers."""
import json
import logging
import random

import pytest
from conftest import FakeOpener, FakeSocket, load_flashforge, load_json, printer

from imago_bridge.drivers.base import DriverError
from imago_bridge.drivers.creality_box import CrealityBoxDriver, parse_info
from imago_bridge.drivers.flashforge_tcp import (
    FlashforgeTcpDriver,
    PrintClock,
    estimate_minutes_left,
    job_minutes,
    parse_replies,
)
from imago_bridge.odoo_client import _summarise_error
from imago_bridge.remote_config import parse_printer
from imago_bridge.schema import MAX_COUNT, clean_text, seconds_to_minutes, to_count, to_number, to_text

ANSI_BIDI = "\x1b[31mpieza‮\x00\r\nfalsa⁦.gx\x7f‏"


# ----------------------------------------------------------------- fix 2: numbers
@pytest.mark.parametrize(
    "value",
    [10**400, -(10**400), "1e999", "-1e999", float("nan"), float("inf"), float("-inf"), "nan", "inf",
     "9" * 5000, [], {}, None, True, b"12", object()],
)
def test_to_number_never_raises_and_rejects_non_finite(value):
    assert to_number(value) is None


def test_to_number_still_accepts_normal_values():
    assert to_number(21) == 21.0 and to_number("240.5") == 240.5 and to_number(-3) == -3.0


def test_creality_deeply_nested_json_is_a_failed_read():
    body = b"[" * 200000 + b"]" * 200000
    with pytest.raises(DriverError):
        CrealityBoxDriver(printer(), opener=FakeOpener(body)).read()


def test_creality_huge_and_infinite_numbers_do_not_raise():
    body = ('{"connect": 1, "state": %s, "nozzleTemp": 1e999, "bedTemp": -1e999, "printProgress": %s, '
            '"layer": %s, "TotalLayer": 1e400, "printJobTime": %s, "err": %s}'
            % ("9" * 400, "1" * 300, "7" * 300, "8" * 300, "1e999")).encode()
    status = CrealityBoxDriver(printer(), opener=FakeOpener(body)).read()
    assert status.state == "unknown"
    assert status.nozzle_temp is None and status.bed_temp is None and status.progress is None
    assert status.layer is None and status.layer_total is None and status.job_time_min is None


@pytest.mark.parametrize("value", [[1, 2], {"a": 1}, None, "x" * 10000, True, -1, 1.5e308])
def test_creality_wrong_types_never_raise(value):
    row = dict.fromkeys(("connect", "state", "pause", "err", "error", "mcu_is_print", "print", "printProgress",
                         "nozzleTemp", "bedTemp", "layer", "TotalLayer", "printJobTime", "printLeftTime"), value)
    status = parse_info(row, 1)
    json.dumps(status.to_payload())


def test_random_bytes_never_escape_as_other_errors():
    rng = random.Random(1021)
    for _ in range(300):
        body = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 200)))
        try:
            CrealityBoxDriver(printer(), opener=FakeOpener(body)).read()
        except DriverError:
            pass
        noise = "".join(chr(rng.randrange(1, 0x3000)) for _ in range(rng.randrange(1, 300)))
        parse_replies({"~M119": noise, "~M105": "T0:" + noise, "~M27": "SD printing byte " + noise})


def test_flashforge_huge_digits_are_ignored():
    replies = {
        "~M119": "MachineStatus: BUILDING_FROM_SD\nCurrentFile: a.gx\nok\n",
        "~M105": "T0:%s/%s B:1e999/0\nok\n" % ("9" * 5000, "9" * 5000),
        "~M27": "SD printing byte %s/%s\nLayer: %s/%s\nok\n" % ("9" * 5000, "1" * 5000, "9" * 5000, "9" * 5000),
    }
    reading = parse_replies(replies)
    assert reading.state == "printing"
    assert reading.nozzle_temp is None and reading.progress is None
    assert reading.layer is None and reading.layer_total is None


# ----------------------------------------------------------------- fix 3: text
def test_clean_text_strips_control_and_bidi_characters():
    assert clean_text(ANSI_BIDI, 128) == "[31mpiezafalsa.gx"
    assert clean_text("\x00‪⁩", 128) is None


def test_file_name_and_error_text_are_sanitised_and_capped():
    row = dict(load_json("creality_printing_usb.json"), print=ANSI_BIDI + "x" * 500)
    status = parse_info(row, 1)
    assert len(status.file_name) == 128
    assert not any(ch in status.file_name for ch in "\x1b\x00\r\n‮⁦\x7f‏")
    error = parse_info(dict(row, err=999999), 1)
    assert error.error_text == "Error de impresora (código 999999)" and len(error.error_text) <= 256
    assert len(to_text("e" * 1000, "error_text")) == 256


def test_flashforge_file_name_sanitised():
    replies = load_flashforge("flashforge_printing.txt")
    replies["~M119"] = replies["~M119"].replace("Cabezal de apriete antenas.gx", "a‮b\x1bc" + "z" * 300)
    assert parse_replies(replies).file_name == ("abc" + "z" * 300)[:128]


def test_m115_identity_is_sanitised_and_capped_in_logs(caplog, idle_replies):
    caplog.set_level(logging.INFO)
    hostile = dict(idle_replies, **{"~M115": "Machine Type: EVIL\x1b[2J‮" + "M" * 500
                                     + "\nFirmware: v9\x07" + "F" * 500 + "\nok\n"})
    config = printer(driver="flashforge_tcp", host="192.168.0.61", port=8899, code="3DP\n03")
    FlashforgeTcpDriver(config, connect=lambda a, timeout=None: FakeSocket(hostile)).read()
    line = next(r.getMessage() for r in caplog.records if "firmware" in r.getMessage())
    assert "\x1b" not in line and "‮" not in line and "\x07" not in line
    assert "M" * 81 not in line and "F" * 81 not in line


def test_printer_code_from_odoo_is_sanitised():
    item = {"workcenter_id": 1, "code": "3DP\r\n01‮" + "x" * 200, "driver": "creality_box",
            "host": "192.168.0.248", "port": 81}
    code = parse_printer(item).code
    assert "\r" not in code and "‮" not in code and len(code) <= 64


def test_odoo_error_message_is_sanitised():
    error = _summarise_error({"data": {"message": "bad\x1b[2J\nline‮" + "y" * 900, "name": "x\ny"}}, "")
    assert "\x1b" not in str(error) and "\n" not in str(error) and len(str(error)) <= 300
    assert error.error_name == "xy"


# ----------------------------------------------------------------- fix 4: integers
def test_counts_above_limit_are_none():
    assert to_count(MAX_COUNT) == MAX_COUNT
    assert to_count(MAX_COUNT + 1) is None and to_count(-1) is None
    assert seconds_to_minutes((MAX_COUNT + 1) * 60) is None
    assert seconds_to_minutes(MAX_COUNT * 60) == MAX_COUNT


def test_creality_absurd_integers_are_none():
    row = dict(load_json("creality_printing_usb.json"), printProgress=50, layer=100001, TotalLayer=100001,
               printJobTime=10**9, printLeftTime=10**9)
    status = parse_info(row, 1)
    assert status.layer is None and status.layer_total is None
    assert status.job_time_min is None and status.time_left_min is None


def test_flashforge_absurd_integers_are_none():
    replies = load_flashforge("flashforge_printing.txt")
    replies["~M27"] = "CMD M27 Received.\nSD printing byte 56/100\nLayer: 100001/100002\nok\n"
    reading = parse_replies(replies)
    assert reading.layer is None and reading.layer_total is None
    clock = PrintClock(started_at=0.0, start_progress=0.0)
    assert estimate_minutes_left(clock, 5.0, 10**9) is None
    assert job_minutes(clock, 10**9) is None
