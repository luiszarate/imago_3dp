"""Camera snapshots in the cycle: due intervals from Odoo, never repeated on stale statuses."""
from service_fakes import config, item, last_printers, ok, step

from imago_bridge.drivers.base import DriverError


def test_snapshots_only_when_due_and_never_repeated(env):
    camera = "http://192.168.0.61:8080/?action=stream"
    env["client"].remote = config(printers=[item(1, "192.168.0.61", "flashforge_tcp", 8899, camera)])
    env["script"][1] = [ok(1, "printing", progress=10.0)]
    step(env)
    assert last_printers(env)[1]["snapshot_jpeg_b64"] == "/9j/FAKE"
    step(env)  # 10 s later: not due (30 s while printing)
    assert last_printers(env)[1]["snapshot_jpeg_b64"] is None
    step(env)
    step(env)  # 30 s after the first photo
    assert last_printers(env)[1]["snapshot_jpeg_b64"] == "/9j/FAKE"
    assert env["photos"][0] == (camera, "192.168.0.61") and len(env["photos"]) == 2
    env["script"][1] = [DriverError("t")]
    env["clock"].now += 60
    step(env)
    assert last_printers(env)[1]["snapshot_jpeg_b64"] is None  # repeated status carries no photo


def test_idle_snapshot_every_five_minutes(env):
    camera = "http://192.168.0.61:8080/?action=stream"
    env["client"].remote = config(printers=[item(1, "192.168.0.61", "flashforge_tcp", 8899, camera)])
    for _ in range(30):
        step(env)
    assert len(env["photos"]) == 1
    step(env)
    assert len(env["photos"]) == 2


def test_idle_snapshot_interval_comes_from_odoo(env):
    camera = "http://192.168.0.61:8080/?action=stream"
    env["client"].remote = dict(config(printers=[item(1, "192.168.0.61", "flashforge_tcp", 8899, camera)]),
                                idle_snapshot_seconds=60)
    for _ in range(7):
        step(env)
    assert len(env["photos"]) == 2  # t=0 and t=60
