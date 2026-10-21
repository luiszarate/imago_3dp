"""Flashforge Adventurer 4 (fw v2.3.3): text G-code status queries over TCP 8899.

Read-only (B-03): per read the driver opens a socket, sends ``~M119``, ``~M105`` and
``~M27`` and closes it. ``~M115`` is sent once to log model and firmware. It does NOT
send ``~M601 S1``/``~M602``: status queries work without taking control, and taking
control competes with FlashPrint (decision of 21-Oct-2026).
"""
import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional

from ..remote_config import PrinterConfig
from ..schema import PrinterStatus, bounded_count, log_text, to_count, to_progress, to_temperature, to_text
from .base import Driver, DriverError, ensure_allowed

_logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = ("~M115", "~M119", "~M105", "~M27")
READ_SEQUENCE = ("~M119", "~M105", "~M27")
TIMEOUT_SECONDS = 3.0
MAX_REPLY_BYTES = 64 * 1024
MIN_PROGRESS_FOR_ETA = 5.0
MACHINE_STATES = {
    "READY": "idle",
    "BUILDING_FROM_SD": "printing",
    "PAUSED": "paused",
    "BUILDING_COMPLETED": "finished",
}
_OK_END = re.compile(rb"(?:^|\n)ok\s*$")
# Bounded digit counts: hostile replies with thousands of digits must not reach int().
_NUM = r"(-?\d{1,6}(?:\.\d{1,6})?)"
_TEMPS = re.compile(r"T0:\s*" + _NUM + r"\s*/\s*" + _NUM + r"\s+B:\s*" + _NUM + r"\s*/\s*" + _NUM)
_SD = re.compile(r"SD printing byte\s+(\d{1,12})\s*/\s*(\d{1,12})")
_LAYER = re.compile(r"Layer:\s*(\d{1,9})\s*/\s*(\d{1,9})")
_STATUS = re.compile(r"^MachineStatus:\s*(\S+)", re.M)
_FILE = re.compile(r"^CurrentFile:[ \t]*(.*?)\s*$", re.M)


@dataclass(frozen=True)
class FlashforgeReading:
    state: str
    progress: Optional[float]
    nozzle_temp: Optional[float]
    nozzle_target: Optional[float]
    bed_temp: Optional[float]
    bed_target: Optional[float]
    layer: Optional[int]
    layer_total: Optional[int]
    file_name: Optional[str]


@dataclass(frozen=True)
class PrintClock:
    """When (monotonic seconds) and at which progress the driver first saw this print."""

    started_at: float
    start_progress: float


def _search(pattern: "re.Pattern[str]", text: str) -> Optional["re.Match[str]"]:
    return pattern.search(text) if text else None


def _target(value: str) -> Optional[float]:
    target = to_temperature(value)
    return target if target else None  # target 0 means "heater off"


def _progress(match: Optional["re.Match[str]"]) -> Optional[float]:
    if not match:
        return None
    done, total = int(match.group(1)), int(match.group(2))
    if total <= 0:
        return None
    # Firmware v2.3.3 reports a percentage as "x/100"; any other total is scaled.
    return to_progress(float(done) if total == 100 else 100.0 * done / total)


def _print_ended(state: str, progress: Optional[float], temps: Optional["re.Match[str]"]) -> bool:
    """Fw v2.3.3 never reports BUILDING_COMPLETED: at the end of a print it stays in
    BUILDING_FROM_SD with 100/100 and both heater targets at 0, then goes to READY
    (observed 21-Oct-2026, 17:18)."""
    if state != "printing" or progress != 100.0 or temps is None:
        return False
    return to_temperature(temps.group(2)) == 0.0 and to_temperature(temps.group(4)) == 0.0


def parse_replies(replies: Mapping[str, str]) -> FlashforgeReading:
    """Normalise the M119/M105/M27 replies (texts keyed by command)."""
    m119, m105, m27 = (replies.get(command, "") for command in READ_SEQUENCE)
    status = _search(_STATUS, m119)
    temps = _search(_TEMPS, m105)
    layer = _search(_LAYER, m27)
    file_match = _search(_FILE, m119)
    layer_total = (to_count(layer.group(2)) or 0) if layer else 0
    progress = _progress(_search(_SD, m27))
    state = MACHINE_STATES.get(status.group(1), "unknown") if status else "unknown"
    return FlashforgeReading(
        state="finished" if _print_ended(state, progress, temps) else state,
        progress=progress,
        nozzle_temp=to_temperature(temps.group(1)) if temps else None,
        nozzle_target=_target(temps.group(2)) if temps else None,
        bed_temp=to_temperature(temps.group(3)) if temps else None,
        bed_target=_target(temps.group(4)) if temps else None,
        layer=to_count(layer.group(1)) if layer_total else None,
        layer_total=layer_total or None,
        file_name=to_text(file_match.group(1), "file_name") if file_match else None,
    )


def next_clock(clock: Optional[PrintClock], reading: FlashforgeReading, now: float) -> Optional[PrintClock]:
    if reading.state not in ("printing", "paused"):
        return None
    return clock or PrintClock(started_at=now, start_progress=reading.progress or 0.0)


def estimate_minutes_left(clock: Optional[PrintClock], progress: Optional[float], now: float) -> Optional[int]:
    """Remaining minutes from the progress rate observed since the driver saw the print."""
    if clock is None or progress is None or progress < MIN_PROGRESS_FOR_ETA:
        return None
    gained = progress - clock.start_progress
    elapsed = now - clock.started_at
    if gained <= 0 or elapsed <= 0:
        return None
    return bounded_count(elapsed * (100.0 - progress) / gained / 60.0)


def job_minutes(clock: Optional[PrintClock], now: float) -> Optional[int]:
    """Elapsed job time, known only when the driver saw the print start at 0 %."""
    if clock is None or clock.start_progress > 0:
        return None
    return bounded_count((now - clock.started_at) / 60.0)


def to_status(reading: FlashforgeReading, workcenter_id: int, clock: Optional[PrintClock], now: float) -> PrinterStatus:
    return PrinterStatus(
        workcenter_id=workcenter_id,
        reachable=True,
        state=reading.state,
        progress=reading.progress,
        nozzle_temp=reading.nozzle_temp,
        nozzle_target=reading.nozzle_target,
        bed_temp=reading.bed_temp,
        bed_target=reading.bed_target,
        layer=reading.layer,
        layer_total=reading.layer_total,
        time_left_min=estimate_minutes_left(clock, reading.progress, now),
        job_time_min=job_minutes(clock, now),
        file_name=reading.file_name,
    )


def query(sock: socket.socket, command: str) -> str:
    """Send one whitelisted command and read its reply up to the final ``ok`` line."""
    ensure_allowed(command, ALLOWED_COMMANDS)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    sock.sendall((command + "\r\n").encode("ascii"))
    buffer = b""
    while not _OK_END.search(buffer):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DriverError("Flashforge reply timed out")
        sock.settimeout(remaining)
        chunk = sock.recv(4096)
        if not chunk:
            raise DriverError("Flashforge closed the connection")
        buffer += chunk
        if len(buffer) > MAX_REPLY_BYTES:
            raise DriverError("Flashforge reply too large")
    return buffer.decode("utf-8", errors="replace").replace("\r", "")


class FlashforgeTcpDriver(Driver):
    def __init__(
        self,
        printer: PrinterConfig,
        connect: Callable[..., socket.socket] = socket.create_connection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(printer)
        self._connect = connect
        self._clock = clock
        self._print_clock: Optional[PrintClock] = None
        self._identified = False

    def send(self, sock: socket.socket, command: str) -> str:
        return query(sock, command)

    def _log_identity(self, sock: socket.socket) -> None:
        reply = self.send(sock, "~M115")
        machine = re.search(r"Machine Type:\s*(.+)", reply)
        firmware = re.search(r"Firmware:\s*(\S+)", reply)
        _logger.info(
            "Impresora %s: %s, firmware %s", log_text(self.printer.code),
            log_text(machine.group(1)) if machine else "?", log_text(firmware.group(1)) if firmware else "?",
        )
        self._identified = True

    def _read_replies(self) -> Dict[str, str]:
        host = self.check_host()
        try:
            with self._connect((host, self.printer.port), timeout=TIMEOUT_SECONDS) as sock:
                if not self._identified:
                    self._log_identity(sock)
                return {command: self.send(sock, command) for command in READ_SEQUENCE}
        except OSError as error:
            raise DriverError("Flashforge read failed: %s" % type(error).__name__) from None

    def read(self) -> PrinterStatus:
        replies = self._read_replies()
        try:
            reading = parse_replies(replies)
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise DriverError("Flashforge reply not understood: %s" % type(error).__name__) from None
        now = self._clock()
        self._print_clock = next_clock(self._print_clock, reading, now)
        return to_status(reading, self.workcenter_id, self._print_clock, now)

