"""Bridge cycle: config from Odoo, poll every printer, push one batch (SPEC 16.4, 16.9).

Printers keep being polled while Odoo is unreachable; pushes back off exponentially
(up to 60 s) and only the latest state is sent, never a history queue.
"""
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Event
from typing import Callable, Dict, List, Mapping, Optional

from .camera import snapshot_b64, snapshot_due
from .drivers import Driver, DriverError, ReadTracker, build_driver
from .odoo_client import OdooRpcError, OdooUnavailable
from .remote_config import DEFAULT_POLL_SECONDS, RemoteConfig, RemoteConfigError, parse_remote_config
from .schema import PrinterStatus, build_push_payload, clean_text

_logger = logging.getLogger(__name__)

CONFIG_RELOAD_SECONDS = 300.0
BACKOFF_BASE_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 60.0
READ_DEADLINE_SECONDS = 25.0
MAX_WORKERS = 8
RETRYABLE_ODOO_ERRORS = (OdooUnavailable, OdooRpcError, RemoteConfigError)


@dataclass(frozen=True)
class PollOutcome:
    """Result of one printer read in a worker thread."""

    workcenter_id: int
    status: Optional[PrinterStatus] = None
    error: Optional[str] = None
    snapshot_taken: bool = False
    snapshot: Optional[str] = None


def backoff_delay(failures: int) -> float:
    """5, 10, 20, 40, 60, 60 … seconds after 1, 2, 3 … consecutive Odoo failures."""
    if failures <= 0:
        return 0.0
    return min(MAX_BACKOFF_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (failures - 1))


class BridgeService:
    def __init__(
        self,
        client,
        driver_factory: Callable[..., Driver] = build_driver,
        snapshot: Callable[[str, str], Optional[str]] = snapshot_b64,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._client = client
        self._driver_factory = driver_factory
        self._snapshot = snapshot
        self._clock = clock
        self._wall_clock = wall_clock
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="printer")
        self._remote: Optional[RemoteConfig] = None
        self._config_loaded_at = 0.0
        self._reload_requested = True
        self._drivers: Mapping[int, Driver] = {}
        self._trackers: Mapping[int, ReadTracker] = {}
        self._snapshot_at: Mapping[int, float] = {}
        self._inflight: Mapping[int, Future] = {}
        self._odoo_failures = 0
        self._next_odoo_at = 0.0
        self._skip_pushes = 0
        self.last_payload: Optional[dict] = None

    # ------------------------------------------------------------------ loop
    @property
    def poll_seconds(self) -> int:
        return self._remote.poll_seconds if self._remote else DEFAULT_POLL_SECONDS

    @property
    def odoo_failures(self) -> int:
        return self._odoo_failures

    def run(self, stop: Event) -> None:
        """Cycle until ``stop`` is set. AuthenticationError propagates (fatal)."""
        while not stop.is_set():
            started = self._clock()
            self.cycle()
            stop.wait(max(0.5, self.poll_seconds - (self._clock() - started)))

    def close(self) -> None:
        self._executor.shutdown(wait=False)

    def cycle(self) -> None:
        now = self._clock()
        if self._odoo_due(now) and self._config_stale(now):
            self._reload_config(now)
        if self._remote is None:
            return
        statuses = self._poll(now)
        if self._skip_pushes:
            self._skip_pushes -= 1
        elif self._odoo_due(now):
            self._push(statuses, now)

    # ---------------------------------------------------------------- odoo
    def _odoo_due(self, now: float) -> bool:
        return now >= self._next_odoo_at

    def _odoo_failed(self, now: float, error: Exception) -> None:
        self._odoo_failures += 1
        delay = backoff_delay(self._odoo_failures)
        self._next_odoo_at = now + delay
        _logger.warning("Odoo no disponible (%s: %s); reintento en %.0f s.", type(error).__name__, error, delay)

    def _odoo_ok(self) -> None:
        if self._odoo_failures:
            _logger.info("Conexión con Odoo restablecida.")
        self._odoo_failures = 0
        self._next_odoo_at = 0.0

    def _config_stale(self, now: float) -> bool:
        return self._remote is None or self._reload_requested or now - self._config_loaded_at >= CONFIG_RELOAD_SECONDS

    def _reload_config(self, now: float) -> None:
        try:
            remote = parse_remote_config(self._client.get_config())
        except RETRYABLE_ODOO_ERRORS as error:
            self._odoo_failed(now, error)
            return
        self._odoo_ok()
        if self._remote is None or remote != self._remote:
            _logger.info(
                "Configuración v%d: %d impresora(s), lectura cada %d s.",
                remote.config_version, len(remote.printers), remote.poll_seconds,
            )
        self._apply_config(remote)
        self._config_loaded_at = now
        self._reload_requested = False

    def _apply_config(self, remote: RemoteConfig) -> None:
        drivers: Dict[int, Driver] = {}
        for printer in remote.printers:
            current = self._drivers.get(printer.workcenter_id)
            if current is not None and current.printer == printer:
                drivers[printer.workcenter_id] = current
                continue
            try:
                drivers[printer.workcenter_id] = self._driver_factory(printer)
            except DriverError as error:
                _logger.warning("Impresora %s no se leerá: %s", printer.code, error)
        self._drivers = drivers
        self._trackers = {wc: self._trackers.get(wc, ReadTracker(wc)) for wc in drivers}
        self._snapshot_at = {wc: t for wc, t in self._snapshot_at.items() if wc in drivers}
        self._remote = remote

    def _push(self, statuses: List[PrinterStatus], now: float) -> None:
        payload = build_push_payload(statuses, self._wall_clock())
        self.last_payload = payload
        try:
            reply = self._client.push_telemetry(payload)
        except RETRYABLE_ODOO_ERRORS as error:
            self._odoo_failed(now, error)
            return
        self._odoo_ok()
        self._handle_reply(reply)

    def _handle_reply(self, reply: object) -> None:
        if not isinstance(reply, dict):
            _logger.warning("Respuesta inesperada de push_telemetry.")
            return
        if reply.get("ok") is False:
            if reply.get("error") == "rate_limited":
                _logger.info("Odoo limitó la frecuencia de envío; se omite un ciclo.")
                self._skip_pushes = 1
            else:
                _logger.warning("Odoo rechazó el lote: %s", clean_text(str(reply.get("error")), 200))
        for item in reply.get("errors") or []:
            if isinstance(item, dict):
                _logger.warning(
                    "Odoo rechazó la impresora %s: %s",
                    clean_text(str(item.get("workcenter_id")), 20), clean_text(str(item.get("error")), 200),
                )
        version = reply.get("config_version")
        if isinstance(version, int) and self._remote and version != self._remote.config_version:
            _logger.info("Odoo tiene la configuración v%d; se recarga.", version)
            self._reload_requested = True

    # ------------------------------------------------------------- printers
    def _snapshot_interval(self, state: str) -> int:
        remote = self._remote
        return remote.snapshot_seconds if state == "printing" else remote.idle_snapshot_seconds

    def _read_one(self, driver: Driver, now: float) -> PollOutcome:
        """Worker thread: read one printer and, when due, take its photo."""
        wc = driver.workcenter_id
        try:
            status = driver.read()
        except DriverError as error:
            return PollOutcome(wc, error=str(error))
        except Exception as error:  # a driver bug must not stop the other printers
            _logger.exception("Error inesperado leyendo la impresora %s", driver.printer.code)
            return PollOutcome(wc, error=type(error).__name__)
        camera_url = driver.printer.camera_url
        interval = self._snapshot_interval(status.state)
        if not camera_url or not snapshot_due(self._snapshot_at.get(wc), now, interval):
            return PollOutcome(wc, status=status)
        photo = self._snapshot(camera_url, driver.printer.host)
        return PollOutcome(wc, status=status, snapshot_taken=True, snapshot=photo)

    def _submit_reads(self, now: float) -> Dict[int, Future]:
        futures: Dict[int, Future] = {}
        for wc, driver in self._drivers.items():
            previous = self._inflight.get(wc)
            if previous is not None and not previous.done():
                continue  # still stuck from an earlier cycle: counts as a failure
            futures[wc] = self._executor.submit(self._read_one, driver, now)
        self._inflight = {**{wc: f for wc, f in self._inflight.items() if not f.done()}, **futures}
        return futures

    def _collect(self, futures: Mapping[int, Future]) -> Dict[int, PollOutcome]:
        deadline = time.monotonic() + READ_DEADLINE_SECONDS
        outcomes: Dict[int, PollOutcome] = {}
        for wc in self._drivers:
            future = futures.get(wc)
            if future is None:
                outcomes[wc] = PollOutcome(wc, error="busy")
                continue
            try:
                outcomes[wc] = future.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeout:
                outcomes[wc] = PollOutcome(wc, error="timeout")
        return outcomes

    def _poll(self, now: float) -> List[PrinterStatus]:
        outcomes = self._collect(self._submit_reads(now))
        trackers = {wc: self._track(self._trackers[wc], outcome) for wc, outcome in outcomes.items()}
        self._trackers = trackers
        self._snapshot_at = {
            **self._snapshot_at,
            **{wc: now for wc, outcome in outcomes.items() if outcome.snapshot_taken},
        }
        statuses = []
        for wc, tracker in trackers.items():
            status = tracker.report()
            if status is None:
                continue
            snapshot = outcomes[wc].snapshot if tracker.fresh else None
            statuses.append(replace(status, snapshot_jpeg_b64=snapshot) if snapshot else status)
        return statuses

    def _track(self, tracker: ReadTracker, outcome: PollOutcome) -> ReadTracker:
        code = self._drivers[tracker.workcenter_id].printer.code
        if outcome.status is not None:
            previous = tracker.last_good.state if tracker.last_good and not tracker.is_offline else None
            if previous != outcome.status.state:
                _logger.info("Impresora %s: %s -> %s", code, previous or "sin dato", outcome.status.state)
            return tracker.on_success(outcome.status)
        updated = tracker.on_failure()
        if updated.is_offline and not tracker.is_offline:
            _logger.warning(
                "Impresora %s sin respuesta (%d lecturas fallidas): fuera de línea.", code, updated.failures
            )
        else:
            _logger.debug("Impresora %s: lectura fallida (%s).", code, outcome.error)
        return updated
