"""Creality WiFi Box (V3.04b06, CR-M4 / Marlin 2.0.9.1): HTTP GET status on port 81.

Read-only: the only URL ever built is ``protocal.csp?fname=Info&opt=main&function=get``
(B-03). The box JSON includes the WiFi password and other secrets (16.2); they are
never copied out of the raw reply: only ``CREALITY_FIELDS`` are read (whitelist, B-01).
"""
import json
import logging
from typing import Any, Dict, Mapping, Optional
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode

from ..lanhttp import build_lan_opener, open_lan_url, read_capped
from ..remote_config import PrinterConfig
from ..schema import (
    PrinterStatus,
    seconds_to_minutes,
    to_count,
    to_number,
    to_progress,
    to_temperature,
    to_text,
)
from .base import CommandNotAllowed, Driver, DriverError, ensure_allowed

_logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 3.0  # per socket operation
TOTAL_SECONDS = 5.0  # whole request: connect + headers + body
MAX_REPLY_BYTES = 64 * 1024
INFO_QUERY = (("fname", "Info"), ("opt", "main"), ("function", "get"))
ALLOWED_QUERIES = (urlencode(INFO_QUERY),)
# Keys known to carry secrets; listed for documentation and tests. They are never read.
SECRET_KEYS = ("wifipasswd", "ssid", "apclissid", "apclimac", "ownerId", "DIDString", "APILicense", "InitString")
CREALITY_FIELDS = (
    "connect", "state", "pause", "err", "error", "mcu_is_print", "print", "printProgress",
    "nozzleTemp", "bedTemp", "layer", "TotalLayer", "printJobTime", "printLeftTime",
)
IDLE_FILE_NAMES = ("", "localhost")
MIN_PROGRESS_FOR_ETA = 5.0
MAX_FLAG = 1_000_000  # status/error codes beyond this are garbage


def build_info_url(host: str, port: int) -> str:
    """The single status URL this driver may request; refuses anything but function=get."""
    query = ensure_allowed(urlencode(INFO_QUERY), ALLOWED_QUERIES)
    if dict(parse_qsl(query)).get("function") != "get":
        raise CommandNotAllowed("Creality URL must use function=get")
    return "http://%s:%d/protocal.csp?%s" % (host, int(port), query)


def pick_fields(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy only the whitelisted keys; secrets and unknown keys stay behind."""
    return {key: raw[key] for key in CREALITY_FIELDS if key in raw}


def _flag(fields: Mapping[str, Any], key: str) -> Optional[int]:
    number = to_number(fields.get(key))
    if number is None or abs(number) > MAX_FLAG:
        return None
    return int(number)


def map_state(fields: Mapping[str, Any]) -> str:
    """Box/printer flags to the common state (observed 21-Oct-2026, see SPEC V-02)."""
    if _flag(fields, "connect") == 0:
        return "offline"
    if _error_code(fields):
        return "error"
    if _flag(fields, "pause") == 1:
        return "paused"
    state = _flag(fields, "state")
    if state == 1:
        return "printing"
    if state == 2:
        return "finished"
    if state == 0:
        # Pre-heat before a print also reports state 0 (nozzle at 260 °C): idle, not "heating".
        return "printing" if _flag(fields, "mcu_is_print") == 1 else "idle"
    return "unknown"


def _error_code(fields: Mapping[str, Any]) -> int:
    for key in ("err", "error"):
        code = _flag(fields, key)
        if code:
            return code
    return 0


def _progress(fields: Mapping[str, Any], state: str) -> Optional[float]:
    progress = to_progress(fields.get("printProgress"))
    no_layers = not to_count(fields.get("layer")) and not to_count(fields.get("TotalLayer"))
    if state == "printing" and progress == 0.0 and no_layers:
        # Prints launched from USB keep printProgress at 0: unknown, not 0 %.
        return None
    return progress


def parse_info(raw: Mapping[str, Any], workcenter_id: int) -> PrinterStatus:
    """Normalise the box JSON (already a mapping) to PrinterStatus."""
    fields = pick_fields(raw)
    state = map_state(fields)
    progress = _progress(fields, state)
    layer_total = to_count(fields.get("TotalLayer")) or None
    eta_known = progress is not None and progress > MIN_PROGRESS_FOR_ETA
    file_name = fields.get("print")
    code = _error_code(fields)
    return PrinterStatus(
        workcenter_id=workcenter_id,
        reachable=True,
        state=state,
        progress=progress,
        nozzle_temp=to_temperature(fields.get("nozzleTemp")),
        bed_temp=to_temperature(fields.get("bedTemp")),
        layer=to_count(fields.get("layer")) if layer_total else None,
        layer_total=layer_total,
        # printLeftTime jumps wildly while progress is unknown: only trusted past 5 %.
        time_left_min=seconds_to_minutes(fields.get("printLeftTime")) if eta_known else None,
        job_time_min=seconds_to_minutes(fields.get("printJobTime")),
        file_name=None if file_name in IDLE_FILE_NAMES else to_text(file_name, "file_name"),
        error_text=to_text("Error de impresora (código %d)" % code, "error_text") if state == "error" else None,
    )


class CrealityBoxDriver(Driver):
    def __init__(self, printer: PrinterConfig, opener=None) -> None:
        super().__init__(printer)
        self._opener = opener or build_lan_opener(TOTAL_SECONDS)
        self._url = build_info_url(printer.host, printer.port)

    def _fetch(self) -> bytes:
        host = self.check_host()
        try:
            with open_lan_url(self._opener, self._url, host, TIMEOUT_SECONDS) as response:
                return read_capped(response, MAX_REPLY_BYTES, TOTAL_SECONDS)
        except (URLError, OSError, ValueError) as error:
            raise DriverError("Creality box read failed: %s" % type(error).__name__) from None

    def read(self) -> PrinterStatus:
        body = self._fetch()
        try:
            raw = json.loads(body.decode("utf-8", errors="replace"))
        except (ValueError, RecursionError):  # RecursionError: hostile deeply nested JSON
            raise DriverError("Creality box reply is not valid JSON") from None
        if not isinstance(raw, dict):
            raise DriverError("Creality box reply is not a JSON object")
        fields = pick_fields(raw)
        del raw, body  # the secret-bearing reply goes no further than this line
        try:
            return parse_info(fields, self.workcenter_id)
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise DriverError("Creality box reply not understood: %s" % type(error).__name__) from None
