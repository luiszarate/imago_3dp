"""Printer configuration downloaded from Odoo (``get_config``), re-validated locally.

Odoo already validates hosts, but the bridge never trusts that (B-06): a printer whose
host is not a literal private IPv4 is dropped here and never contacted.
"""
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from .netguard import camera_host, is_allowed_host
from .schema import clean_text

_logger = logging.getLogger(__name__)

DRIVERS = ("creality_box", "flashforge_tcp")
MIN_POLL_SECONDS = 5
DEFAULT_POLL_SECONDS = 10
DEFAULT_SNAPSHOT_SECONDS = 30
IDLE_SNAPSHOT_SECONDS = 300
CODE_LIMIT = 64


class RemoteConfigError(ValueError):
    """``get_config`` returned something that does not follow the contract."""


@dataclass(frozen=True)
class PrinterConfig:
    workcenter_id: int
    code: str
    driver: str
    host: str
    port: int
    camera_url: Optional[str] = None


@dataclass(frozen=True)
class RemoteConfig:
    config_version: int
    poll_seconds: int
    snapshot_seconds: int
    idle_snapshot_seconds: int
    printers: Tuple[PrinterConfig, ...]


def _positive_int(value: Any, default: int, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, value)


def parse_printer(item: Any) -> PrinterConfig:
    """One printers[] entry; raise RemoteConfigError when it must not be polled."""
    if not isinstance(item, Mapping):
        raise RemoteConfigError("entrada de impresora sin formato de objeto")
    workcenter_id = item.get("workcenter_id")
    if isinstance(workcenter_id, bool) or not isinstance(workcenter_id, int):
        raise RemoteConfigError("workcenter_id inválido")
    driver = item.get("driver")
    if driver not in DRIVERS:
        raise RemoteConfigError("driver no soportado: %r" % (driver,))
    host = item.get("host")
    if not is_allowed_host(host):
        raise RemoteConfigError("host no permitido (solo IPv4 privada literal): %r" % (host,))
    port = item.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise RemoteConfigError("puerto inválido: %r" % (port,))
    raw_camera = item.get("camera_url") or None
    camera_url = raw_camera if camera_host(raw_camera, host) else None
    if raw_camera and camera_url is None:
        _logger.warning("Impresora %s: cámara ignorada (debe ser http en la IP de la impresora).", workcenter_id)
    code = clean_text(item.get("code"), CODE_LIMIT)  # used in log lines
    return PrinterConfig(
        workcenter_id=workcenter_id,
        code=code or str(workcenter_id),
        driver=driver,
        host=host,
        port=port,
        camera_url=camera_url,
    )


def parse_remote_config(data: Any) -> RemoteConfig:
    """Validate the whole ``get_config`` reply; invalid printers are skipped and logged."""
    if not isinstance(data, Mapping):
        raise RemoteConfigError("get_config no devolvió un objeto")
    version = data.get("config_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RemoteConfigError("config_version inválido")
    items = data.get("printers")
    if not isinstance(items, list):
        raise RemoteConfigError("printers debe ser una lista")
    printers = []
    for item in items:
        try:
            printer = parse_printer(item)
            if any(known.workcenter_id == printer.workcenter_id for known in printers):
                raise RemoteConfigError("workcenter_id repetido")
            printers.append(printer)
        except RemoteConfigError as error:
            ident = item.get("workcenter_id") if isinstance(item, Mapping) else None
            _logger.warning("Impresora %s descartada de la configuración: %s", ident, error)
    return RemoteConfig(
        config_version=version,
        poll_seconds=_positive_int(data.get("poll_seconds"), DEFAULT_POLL_SECONDS, MIN_POLL_SECONDS),
        snapshot_seconds=_positive_int(data.get("snapshot_seconds"), DEFAULT_SNAPSHOT_SECONDS, MIN_POLL_SECONDS),
        idle_snapshot_seconds=_positive_int(
            data.get("idle_snapshot_seconds"), IDLE_SNAPSHOT_SECONDS, MIN_POLL_SECONDS
        ),
        printers=tuple(printers),
    )
