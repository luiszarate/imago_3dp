"""B-02 (Flashforge parser on real replies) and B-03 (command whitelist)."""
import pytest
from conftest import FakeSocket, load_flashforge, printer

from imago_bridge.drivers.base import CommandNotAllowed, DriverError
from imago_bridge.drivers.flashforge_tcp import (
    ALLOWED_COMMANDS,
    FlashforgeTcpDriver,
    PrintClock,
    estimate_minutes_left,
    parse_replies,
    query,
)


def ff_printer():
    return printer(driver="flashforge_tcp", host="192.168.0.61", port=8899, workcenter_id=14, code="3DP-03")


def make_driver(replies, clock=lambda: 1000.0, split=None):
    sockets = []

    def connect(address, timeout=None):
        assert address == ("192.168.0.61", 8899)
        assert timeout == 3.0
        sockets.append(FakeSocket(replies, split=split))
        return sockets[-1]

    return FlashforgeTcpDriver(ff_printer(), connect=connect, clock=clock), sockets


# ----------------------------------------------------------------- B-02 parser
def test_printing_replies():
    reading = parse_replies(load_flashforge("flashforge_printing.txt"))
    assert reading.state == "printing"
    assert reading.progress == 56.0
    assert (reading.layer, reading.layer_total) == (48, 94)
    assert (reading.nozzle_temp, reading.nozzle_target) == (240.0, 240.0)
    assert (reading.bed_temp, reading.bed_target) == (105.0, 105.0)
    assert reading.file_name == "Cabezal de apriete antenas.gx"


def test_idle_replies():
    reading = parse_replies(load_flashforge("flashforge_idle.txt"))
    assert reading.state == "idle"
    assert reading.progress == 0.0
    assert reading.layer is None and reading.layer_total is None
    assert reading.nozzle_temp == 21.0 and reading.nozzle_target is None
    assert reading.bed_temp == 5.0 and reading.bed_target is None
    assert reading.file_name is None


@pytest.mark.parametrize(
    "machine, state",
    [("PAUSED", "paused"), ("BUILDING_COMPLETED", "finished"), ("BUSY", "unknown"), ("", "unknown")],
)
def test_machine_status_mapping(machine, state):
    replies = load_flashforge("flashforge_printing.txt")
    replies["~M119"] = replies["~M119"].replace("BUILDING_FROM_SD", machine)
    assert parse_replies(replies).state == state


def test_end_of_print_without_building_completed_is_finished():
    reading = parse_replies(load_flashforge("flashforge_finished.txt"))
    assert reading.state == "finished"
    assert reading.progress == 100.0
    assert (reading.layer, reading.layer_total) == (94, 94)
    assert reading.file_name == "Cabezal de apriete antenas.gx"
    assert reading.nozzle_temp == 97.0 and reading.nozzle_target is None


def test_full_progress_with_heaters_on_is_still_printing():
    replies = load_flashforge("flashforge_finished.txt")
    replies["~M105"] = "CMD M105 Received.\nT0:240/240 B:105/105\nok\n"
    assert parse_replies(replies).state == "printing"
    replies["~M105"] = "CMD M105 Received.\nT0:97/0 B:83/60\nok\n"
    assert parse_replies(replies).state == "printing"


def test_ready_after_end_of_print_is_idle():
    replies = load_flashforge("flashforge_idle.txt")
    replies["~M105"] = "CMD M105 Received.\nT0:91/0 B:82/0\nok\n"  # 17:18:42, cooling down
    reading = parse_replies(replies)
    assert reading.state == "idle" and reading.file_name is None and reading.layer_total is None


def test_driver_end_of_print_sequence(idle_replies):
    times = iter([0.0, 600.0, 700.0])
    printing = load_flashforge("flashforge_printing.txt") | {"~M115": idle_replies["~M115"]}
    finished = load_flashforge("flashforge_finished.txt")
    sequence = iter([printing, finished, idle_replies])
    driver = FlashforgeTcpDriver(ff_printer(), connect=lambda a, timeout=None: FakeSocket(next(sequence)),
                                 clock=lambda: next(times))
    assert [driver.read().state for _ in range(3)] == ["printing", "finished", "idle"]


def test_garbage_replies_are_unknown_not_crash():
    reading = parse_replies({"~M119": "nonsense", "~M105": "", "~M27": "SD printing byte 5/0"})
    assert reading.state == "unknown"
    assert reading.progress is None and reading.nozzle_temp is None


def test_driver_read_printing_and_session():
    driver, sockets = make_driver(load_flashforge("flashforge_printing.txt") | {"~M115": "Firmware: v2.3.3\nok\n"})
    status = driver.read()
    assert status.to_payload()["state"] == "printing"
    assert status.workcenter_id == 14 and status.reachable is True
    sent = [data.decode() for data in sockets[0].sent]
    assert sent == ["~M115\r\n", "~M119\r\n", "~M105\r\n", "~M27\r\n"]
    assert sockets[0].closed
    driver.read()
    assert [data.decode() for data in sockets[1].sent] == ["~M119\r\n", "~M105\r\n", "~M27\r\n"]


def test_driver_handles_split_tcp_chunks(idle_replies):
    driver, _ = make_driver(idle_replies, split=7)
    assert driver.read().state == "idle"


def test_driver_never_sends_control_commands(idle_replies):
    driver, sockets = make_driver(idle_replies)
    driver.read()
    sent = b"".join(sockets[0].sent).decode()
    assert "M601" not in sent and "M602" not in sent


def test_connection_errors_become_driver_errors():
    def refuse(address, timeout=None):
        raise ConnectionRefusedError()

    with pytest.raises(DriverError):
        FlashforgeTcpDriver(ff_printer(), connect=refuse).read()


def test_reply_without_ok_times_out(idle_replies):
    broken = dict(idle_replies, **{"~M105": "CMD M105 Received.\nT0:21/0 B:5/0\n"})
    driver, _ = make_driver(broken)
    with pytest.raises(DriverError):
        driver.read()


def test_reply_size_is_capped():
    sock = FakeSocket({"~M119": "x" * (70 * 1024) + "\nok\n"})
    with pytest.raises(DriverError):
        query(sock, "~M119")


# ----------------------------------------------------------------- B-03 whitelist
@pytest.mark.parametrize(
    "command",
    ["~M601 S1", "~M602", "~M26", "~M24", "~M25", "~M140 S0", "~M104 S0", "~M119 ", "M119", "~M119\r\n~M26", ""],
)
def test_whitelist_refuses_other_commands(command):
    sock = FakeSocket({})
    with pytest.raises(CommandNotAllowed):
        query(sock, command)
    assert sock.sent == []


def test_driver_send_goes_through_whitelist(idle_replies):
    driver, _ = make_driver(idle_replies)
    with pytest.raises(CommandNotAllowed):
        driver.send(FakeSocket(idle_replies), "~M602")


def test_whitelist_is_exactly_the_read_queries():
    assert ALLOWED_COMMANDS == ("~M115", "~M119", "~M105", "~M27")


# ----------------------------------------------------------------- time left
def test_time_left_estimate_from_observed_rate():
    clock = PrintClock(started_at=0.0, start_progress=0.0)
    assert estimate_minutes_left(clock, 4.0, 600.0) is None  # < 5 %
    assert estimate_minutes_left(clock, 50.0, 3600.0) == 60
    mid_print = PrintClock(started_at=0.0, start_progress=56.0)
    assert estimate_minutes_left(mid_print, 56.0, 60.0) is None  # no progress seen yet
    assert estimate_minutes_left(mid_print, 58.0, 600.0) == 210  # 2 % in 10 min, 42 % left
    assert estimate_minutes_left(None, 50.0, 10.0) is None


def test_driver_tracks_print_clock(idle_replies):
    times = iter([100.0, 700.0, 800.0])
    printing = load_flashforge("flashforge_printing.txt") | {"~M115": idle_replies["~M115"]}
    driver, _ = make_driver(printing, clock=lambda: next(times))
    first = driver.read()
    assert first.time_left_min is None and first.job_time_min is None
    later = dict(printing, **{"~M27": "CMD M27 Received.\nSD printing byte 66/100\nLayer: 55/94\nok\n"})
    driver._connect = lambda address, timeout=None: FakeSocket(later)
    second = driver.read()
    assert second.progress == 66.0
    assert second.time_left_min == 34  # 10 % in 600 s -> 34 % in 2040 s
    driver._connect = lambda address, timeout=None: FakeSocket(idle_replies)
    assert driver.read().time_left_min is None

