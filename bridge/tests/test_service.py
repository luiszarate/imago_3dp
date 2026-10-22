"""B-05: main loop resilience (Odoo down, failing printers, 3-failure rule) and B-06 at runtime."""
import threading

import pytest
from conftest import load_json
from service_fakes import config, item, last_printers, ok, step

from imago_bridge.drivers.base import DriverError
from imago_bridge.drivers.creality_box import parse_info
from imago_bridge.odoo_client import AuthenticationError
from imago_bridge.service import backoff_delay


# ----------------------------------------------------------------- normal cycle
def test_normal_cycle_pushes_one_batch(env):
    step(env)
    assert env["client"].get_config_calls == 1
    assert len(env["client"].pushes) == 1
    payload = env["client"].pushes[0]
    assert payload["sent_at"] == "2026-10-21T16:00:00Z"
    assert set(last_printers(env)) == {1, 2}


def test_backoff_delays():
    assert [backoff_delay(n) for n in range(0, 7)] == [0, 5, 10, 20, 40, 60, 60]


# ----------------------------------------------------------------- B-05 Odoo down
def test_odoo_down_at_start_backs_off_without_crashing(env):
    env["client"].down = True
    for _ in range(12):
        step(env, 5.0)
    service = env["service"]
    assert service.odoo_failures >= 3
    assert env["client"].get_config_calls < 12  # backoff skipped attempts
    env["client"].down = False
    env["clock"].now += 60
    step(env)
    assert service.odoo_failures == 0 and len(env["client"].pushes) == 1


def test_odoo_down_keeps_polling_and_sends_only_latest(env):
    step(env)
    env["client"].down = True
    for n in range(8):
        env["script"][1] = [ok(1, "printing", progress=float(n))]
        step(env)
    assert env["drivers"][1].reads == 9  # every cycle read the printer
    attempts_while_down = len(env["client"].pushes) - 1
    assert 0 < attempts_while_down < 8  # backoff limited the push attempts
    env["client"].down = False
    env["clock"].now += 60
    env["script"][1] = [ok(1, "printing", progress=42.0)]
    step(env)
    latest = env["client"].pushes[-1]
    assert len(latest["printers"]) == 2  # one state per printer, no history queue
    assert last_printers(env)[1]["progress"] == 42.0


def test_authentication_error_is_fatal(env):
    def rejected():
        raise AuthenticationError("Odoo rechazó el usuario")

    env["client"].get_config = rejected
    with pytest.raises(AuthenticationError):
        env["service"].cycle()


# ----------------------------------------------------------------- B-05 printers
def test_failing_printer_does_not_block_others(env):
    env["script"][1] = [DriverError("timeout")]
    step(env)
    assert set(last_printers(env)) == {2}  # no good status yet for printer 1: left out
    assert env["drivers"][2].reads == 1


def test_unexpected_driver_bug_is_contained(env):
    env["script"][1] = [RuntimeError("bug")]
    step(env)
    assert set(last_printers(env)) == {2}


def test_three_failures_rule(env):
    good = ok(1, "printing", progress=50.0, file_name="pieza.gcode")
    env["script"][1] = [good, DriverError("t1"), DriverError("t2"), DriverError("t3"), ok(1, "idle")]
    step(env)
    assert last_printers(env)[1]["state"] == "printing"
    step(env)
    step(env)
    # failures 1 and 2: the last good status is repeated
    assert last_printers(env)[1] == good.to_payload()
    step(env)
    third = last_printers(env)[1]
    assert third["reachable"] is False and third["state"] == "offline"
    assert third["progress"] is None and third["file_name"] is None
    step(env)
    assert last_printers(env)[1]["state"] == "idle" and last_printers(env)[1]["reachable"] is True


def test_offline_after_three_failures_without_any_good_read(env):
    env["script"][1] = [DriverError("refused")]
    for _ in range(3):
        step(env)
    assert last_printers(env)[1]["state"] == "offline"


# ----------------------------------------------------------------- Odoo replies
def test_rate_limited_skips_one_cycle(env):
    env["client"].replies = [{"ok": False, "error": "rate_limited", "config_version": 1}]
    step(env)
    step(env)
    assert len(env["client"].pushes) == 1
    step(env)
    assert len(env["client"].pushes) == 2


def test_new_config_version_triggers_reload(env):
    env["client"].replies = [{"ok": True, "config_version": 2, "errors": []}]
    step(env)
    env["client"].remote = config(version=2, printers=[item(1, "192.168.0.248")])
    step(env)
    assert env["client"].get_config_calls == 2
    assert set(last_printers(env)) == {1}


def test_config_reloaded_every_five_minutes(env):
    for _ in range(31):
        step(env)
    assert env["client"].get_config_calls == 2


def test_reply_errors_are_logged(env, caplog):
    env["client"].replies = [{"ok": True, "config_version": 1, "errors": [{"workcenter_id": 2, "error": "state"}]}]
    step(env)
    assert "impresora 2" in caplog.text


# ----------------------------------------------------------------- B-06 at runtime
def test_public_or_dns_hosts_from_odoo_are_never_contacted(env):
    env["client"].remote = config(printers=[
        item(1, "192.168.0.248"), item(2, "8.8.8.8"), item(3, "printer.local"), item(4, "127.0.0.1"),
        item(5, "169.254.3.3"),
    ])
    step(env)
    assert set(env["drivers"]) == {1}
    assert set(last_printers(env)) == {1}


# ----------------------------------------------------------------- shutdown
def test_run_stops_on_event(env):
    stop = threading.Event()
    original = env["client"].push_telemetry

    def push_and_stop(payload):
        stop.set()
        return original(payload)

    env["client"].push_telemetry = push_and_stop
    thread = threading.Thread(target=env["service"].run, args=(stop,))
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(env["client"].pushes) == 1


def test_real_creality_timeout_row_is_absorbed(env):
    """Capture 16:56:56: one timeout between two printing reads is not reported as offline."""
    def replay(name):
        row = load_json(name)
        return DriverError(row["error"]) if "error" in row and isinstance(row["error"], str) else parse_info(row, 1)

    env["script"][1] = [replay(n) for n in ("creality_printing_usb.json", "creality_timeout.json",
                                            "creality_printing_progress1.json")]
    states = []
    for _ in range(3):
        step(env)
        states.append((last_printers(env)[1]["state"], last_printers(env)[1]["progress"]))
    assert states == [("printing", 0.0), ("printing", 0.0), ("printing", 1.0)]


def test_three_failures_rule_applies_to_flashforge(env):
    env["client"].remote = config(printers=[item(1, "192.168.0.61", "flashforge_tcp", 8899)])
    env["script"][1] = [ok(1, "printing", progress=56.0), DriverError("Flashforge read failed: TimeoutError"),
                        ok(1, "printing", progress=57.0), DriverError("t"), DriverError("t"), DriverError("t")]
    seen = []
    for _ in range(6):
        step(env)
        seen.append(last_printers(env)[1]["state"])
    assert seen == ["printing", "printing", "printing", "printing", "printing", "offline"]
