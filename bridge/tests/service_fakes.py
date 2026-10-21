"""Fakes and fixture shared by the service tests (no network, injected clock)."""
from datetime import datetime, timezone

from imago_bridge.drivers.base import Driver
from imago_bridge.odoo_client import OdooUnavailable
from imago_bridge.schema import PrinterStatus
from imago_bridge.service import BridgeService

WALL = datetime(2026, 10, 21, 16, 0, 0, tzinfo=timezone.utc)


def item(wc, host, driver="creality_box", port=81, camera_url=False):
    return {"workcenter_id": wc, "code": "3DP-%02d" % wc, "driver": driver, "host": host, "port": port,
            "camera_url": camera_url}


def config(version=1, printers=None):
    printers = printers if printers is not None else [item(1, "192.168.0.248"), item(2, "192.168.0.249")]
    return {"config_version": version, "poll_seconds": 10, "snapshot_seconds": 30, "printers": printers}


def ok(wc, state="idle", **values):
    return PrinterStatus(workcenter_id=wc, reachable=True, state=state, **values)


class FakeClient:
    def __init__(self, remote):
        self.remote = remote
        self.down = False
        self.get_config_calls = 0
        self.pushes = []
        self.replies = []

    def get_config(self):
        self.get_config_calls += 1
        if self.down:
            raise OdooUnavailable("Odoo no responde (URLError)")
        return self.remote

    def push_telemetry(self, payload):
        self.pushes.append(payload)
        if self.down:
            raise OdooUnavailable("Odoo no responde (URLError)")
        if self.replies:
            return self.replies.pop(0)
        return {"ok": True, "config_version": self.remote["config_version"], "errors": []}


class FakeDriver(Driver):
    def __init__(self, printer, script):
        super().__init__(printer)
        self.script = script
        self.reads = 0

    def read(self):
        self.reads += 1
        result = self.script[self.workcenter_id].pop(0) if len(self.script[self.workcenter_id]) > 1 \
            else self.script[self.workcenter_id][0]
        if isinstance(result, BaseException):
            raise result
        return result


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_env():
    """Service wired to fakes; ``env`` fixture in conftest closes it after each test."""
    clock = Clock()
    client = FakeClient(config())
    script = {1: [ok(1)], 2: [ok(2)]}
    drivers = {}
    photos = []

    def factory(printer):
        drivers[printer.workcenter_id] = FakeDriver(printer, script)
        return drivers[printer.workcenter_id]

    def snapshot(url, host):
        photos.append((url, host))
        return "/9j/FAKE"

    service = BridgeService(client, driver_factory=factory, snapshot=snapshot, clock=clock, wall_clock=lambda: WALL)
    return {"service": service, "client": client, "clock": clock, "script": script, "drivers": drivers,
            "photos": photos}


def step(env, seconds=10.0):
    env["service"].cycle()
    env["clock"].now += seconds


def last_printers(env):
    return {p["workcenter_id"]: p for p in env["client"].pushes[-1]["printers"]}


