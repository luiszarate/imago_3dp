"""Printer drivers. Each one is read-only and returns the common PrinterStatus."""
from ..remote_config import PrinterConfig
from .base import CommandNotAllowed, Driver, DriverError, ReadTracker
from .creality_box import CrealityBoxDriver
from .flashforge_tcp import FlashforgeTcpDriver

DRIVER_CLASSES = {
    "creality_box": CrealityBoxDriver,
    "flashforge_tcp": FlashforgeTcpDriver,
}


def build_driver(printer: PrinterConfig) -> Driver:
    try:
        driver_class = DRIVER_CLASSES[printer.driver]
    except KeyError:
        raise DriverError("unsupported driver: %r" % (printer.driver,)) from None
    return driver_class(printer)


__all__ = [
    "CommandNotAllowed",
    "CrealityBoxDriver",
    "Driver",
    "DriverError",
    "FlashforgeTcpDriver",
    "ReadTracker",
    "build_driver",
]
