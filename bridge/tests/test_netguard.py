"""B-06: only literal private IPv4 hosts are contacted, even if Odoo's config says otherwise."""
import pytest

from imago_bridge.netguard import camera_host, is_allowed_host
from imago_bridge.remote_config import RemoteConfigError, parse_printer, parse_remote_config


@pytest.mark.parametrize("host", ["192.168.0.248", "192.168.0.61", "10.1.2.3", "172.16.5.4", "172.31.255.254"])
def test_private_ipv4_allowed(host):
    assert is_allowed_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "8.8.8.8", "35.89.115.62", "172.32.0.1",  # public
        "127.0.0.1", "127.1.2.3",  # loopback
        "169.254.1.1",  # link-local
        "224.0.0.1",  # multicast
        "0.0.0.0", "255.255.255.255", "240.0.0.1",  # unspecified / broadcast / reserved
        "printer.local", "localhost", "erp.imago.aero",  # DNS names
        "192.168.0.248:81", " 192.168.0.248", "192.168.000.248", "0xC0A800F8", "3232235768",
        "fd00::1", "::ffff:192.168.0.1",  # IPv6
        "", None, 12, ["192.168.0.1"],
    ],
)
def test_everything_else_refused(host):
    assert not is_allowed_host(host)


def test_camera_must_be_http_on_printer_host():
    assert camera_host("http://192.168.0.61:8080/?action=stream", "192.168.0.61") == "192.168.0.61"
    assert camera_host("http://192.168.0.62:8080/", "192.168.0.61") is None
    assert camera_host("ftp://192.168.0.61/", "192.168.0.61") is None
    assert camera_host("http://192.168.0.61:99999/", "192.168.0.61") is None
    assert camera_host(False, "192.168.0.61") is None


def base_item(**changes):
    item = {"workcenter_id": 12, "code": "3DP-01", "driver": "creality_box", "host": "192.168.0.248",
            "port": 81, "camera_url": False}
    item.update(changes)
    return item


@pytest.mark.parametrize("host", ["8.8.8.8", "127.0.0.1", "169.254.0.9", "printer.lan", ""])
def test_config_printer_with_bad_host_is_rejected(host):
    with pytest.raises(RemoteConfigError):
        parse_printer(base_item(host=host))


def test_get_config_drops_unsafe_printers_keeps_good_ones():
    data = {
        "config_version": 4, "poll_seconds": 10, "snapshot_seconds": 30, "idle_snapshot_seconds": 300,
        "printers": [
            base_item(),
            base_item(workcenter_id=13, host="1.1.1.1"),
            base_item(workcenter_id=14, host="localhost"),
            base_item(workcenter_id=15, driver="octoprint"),
            base_item(workcenter_id=16, port=0),
            base_item(workcenter_id=12, host="192.168.0.249"),  # duplicated id
            base_item(workcenter_id=17, driver="flashforge_tcp", host="192.168.0.61", port=8899,
                      camera_url="http://192.168.0.61:8080/?action=stream"),
            base_item(workcenter_id=18, host="192.168.0.20", camera_url="http://10.0.0.1:8080/"),
        ],
    }
    config = parse_remote_config(data)
    assert [p.workcenter_id for p in config.printers] == [12, 17, 18]
    assert config.printers[1].camera_url == "http://192.168.0.61:8080/?action=stream"
    assert config.printers[2].camera_url is None  # camera on another host is ignored
    assert config.printers[0].camera_url is None


def test_config_defaults_and_minimums():
    config = parse_remote_config({"config_version": 1, "poll_seconds": 1, "printers": []})
    assert config.poll_seconds == 5
    assert config.snapshot_seconds == 30
    assert config.idle_snapshot_seconds == 300


@pytest.mark.parametrize("data", [None, [], {"printers": []}, {"config_version": True, "printers": []},
                                  {"config_version": 1, "printers": {}}])
def test_invalid_config_raises(data):
    with pytest.raises(RemoteConfigError):
        parse_remote_config(data)
