"""Driver interface, read-only command whitelist (D-15, B-03) and failure tolerance."""
import abc
from dataclasses import dataclass, replace
from typing import Iterable, Optional

from ..netguard import is_allowed_host
from ..remote_config import PrinterConfig
from ..schema import PrinterStatus, offline_status

MAX_CONSECUTIVE_FAILURES = 3


class DriverError(Exception):
    """A read failed (timeout, refused, malformed reply). Never carries raw printer data."""


class CommandNotAllowed(DriverError):
    """A driver tried to emit something outside its read-only whitelist."""


def ensure_allowed(command: str, allowed: Iterable[str]) -> str:
    """Return ``command`` if it is exactly one of ``allowed``; raise otherwise."""
    if command not in tuple(allowed):
        raise CommandNotAllowed("command refused by the read-only whitelist")
    return command


class Driver(abc.ABC):
    """Reads one printer. ``read`` raises DriverError on any failure."""

    def __init__(self, printer: PrinterConfig) -> None:
        if not is_allowed_host(printer.host):
            raise DriverError("host not allowed by netguard")
        self.printer = printer

    @property
    def workcenter_id(self) -> int:
        return self.printer.workcenter_id

    def check_host(self) -> str:
        """Re-validate the host right before every connection (defence in depth)."""
        if not is_allowed_host(self.printer.host):
            raise DriverError("host not allowed by netguard")
        return self.printer.host

    @abc.abstractmethod
    def read(self) -> PrinterStatus:
        """One read-only poll of the printer, normalised to the common schema."""


@dataclass(frozen=True)
class ReadTracker:
    """Failure tolerance for one printer (immutable; each read returns a new tracker).

    The Creality WiFi box drops single requests now and then, so a printer is reported
    unreachable only after ``MAX_CONSECUTIVE_FAILURES`` failed reads in a row. Until then
    the last good status is repeated (without its photo). With no good status yet,
    nothing is reported for that printer.
    """

    workcenter_id: int
    failures: int = 0
    last_good: Optional[PrinterStatus] = None
    fresh: bool = False

    def on_success(self, status: PrinterStatus) -> "ReadTracker":
        return replace(self, failures=0, last_good=status, fresh=True)

    def on_failure(self) -> "ReadTracker":
        return replace(self, failures=self.failures + 1, fresh=False)

    @property
    def is_offline(self) -> bool:
        return self.failures >= MAX_CONSECUTIVE_FAILURES

    def report(self) -> Optional[PrinterStatus]:
        """The status to push this cycle, or None to leave the printer out."""
        if self.is_offline:
            return offline_status(self.workcenter_id)
        if self.last_good is None:
            return None
        return self.last_good if self.fresh else self.last_good.without_snapshot()
