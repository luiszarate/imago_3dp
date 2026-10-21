"""Security review fix 1: total wall-clock deadlines for HTTP, camera and Flashforge TCP."""
import io
import socket
import threading
import time
from urllib.error import URLError

import pytest
from conftest import FakeResponse, FakeSocket

import imago_bridge.camera as camera
import imago_bridge.drivers.flashforge_tcp as flashforge
from imago_bridge.drivers.base import DriverError
from imago_bridge.lanhttp import DeadlineExceeded, _DeadlineRaw, build_lan_opener, open_lan_url, read_capped


class TicksClock:
    """Fake monotonic clock that advances ``step`` seconds on every call."""

    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class TrickleSocket:
    """Returns one byte per receive, like a hostile device sending a byte every 2.9 s."""

    def __init__(self):
        self.timeouts = []
        self._timeout = 3.0

    def settimeout(self, value):
        self._timeout = value
        self.timeouts.append(value)

    def gettimeout(self):
        return self._timeout

    def recv_into(self, buffer):
        buffer[0:1] = b"x"
        return 1

    def recv(self, size):
        return b"x"

    def sendall(self, data):
        pass


def test_deadline_reader_stops_a_byte_trickle():
    clock = TicksClock(2.9)
    sock = TrickleSocket()
    reader = io.BufferedReader(_DeadlineRaw(sock, deadline=clock() + 5.0, clock=clock))
    with pytest.raises(DeadlineExceeded):
        reader.readline()  # a header line that never ends
    assert len(sock.timeouts) <= 3
    assert all(value <= 5.0 for value in sock.timeouts)


def test_read_capped_has_total_deadline():
    clock = TicksClock(2.0)
    body = FakeResponse(b"x" * 1000, chunk_size=1)
    with pytest.raises(DeadlineExceeded):
        read_capped(body, 64 * 1024, deadline_seconds=5.0, clock=clock)
    assert body.tell() < 10


def test_deadline_exceeded_is_a_socket_timeout():
    assert issubclass(DeadlineExceeded, OSError)


def test_http_request_with_trickling_headers_is_cut_at_total_deadline(monkeypatch):
    """End to end through urllib + http.client on a local socketpair (no real network)."""
    client_end, device_end = socket.socketpair()
    stop = threading.Event()

    def device():
        device_end.recv(4096)  # the GET request
        for byte in b"HTTP/1.0 200 OK\r\nX-Slow: " + b"a" * 1000:
            if stop.wait(0.1):
                break
            try:
                device_end.sendall(bytes([byte]))
            except OSError:
                break

    def fake_create_connection(address, timeout=None, source_address=None, **kwargs):
        client_end.settimeout(timeout)
        return client_end

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    thread = threading.Thread(target=device, daemon=True)
    thread.start()
    opener = build_lan_opener(total_seconds=0.6)
    started = time.monotonic()
    try:
        with pytest.raises((URLError, OSError)):
            open_lan_url(opener, "http://192.168.0.248:81/protocal.csp", "192.168.0.248", timeout=3.0).read()
    finally:
        stop.set()
        elapsed = time.monotonic() - started
        device_end.close()
        client_end.close()
    assert elapsed < 1.5  # per-read timeout alone (3 s per byte) would never stop it


def test_open_lan_url_refuses_https_and_other_hosts():
    opener = build_lan_opener()
    with pytest.raises(PermissionError):
        open_lan_url(opener, "https://192.168.0.248/", "192.168.0.248", 3.0)
    with pytest.raises(PermissionError):
        open_lan_url(opener, "http://192.168.0.9/", "192.168.0.248", 3.0)


def test_camera_uses_total_deadline_opener(monkeypatch):
    seen = []

    def fake_builder(total_seconds=None):
        seen.append(total_seconds)
        raise OSError("stop here")

    monkeypatch.setattr(camera, "build_lan_opener", fake_builder)
    with pytest.raises(OSError):
        camera.fetch_snapshot("http://192.168.0.61:8080/?action=stream", "192.168.0.61")
    assert seen == [camera.MAX_SECONDS]


def test_camera_frame_read_is_bounded_in_total_time():
    clock = TicksClock(2.9)
    stream = FakeResponse(b"\xff\xd8" + b"\x00" * 10000, chunk_size=1)
    with pytest.raises(camera.CameraError):
        camera.read_first_frame(stream, clock=clock)
    assert stream.tell() <= 3


def test_flashforge_command_has_total_deadline(monkeypatch):
    clock = TicksClock(1.0)
    monkeypatch.setattr(flashforge.time, "monotonic", clock)
    sock = TrickleSocket()
    with pytest.raises(DriverError):
        flashforge.query(sock, "~M119")
    assert sock.timeouts and max(sock.timeouts) <= flashforge.TIMEOUT_SECONDS
    assert len(sock.timeouts) <= 3


def test_flashforge_read_is_failed_read_on_trickle(monkeypatch, idle_replies):
    clock = TicksClock(1.0)
    monkeypatch.setattr(flashforge.time, "monotonic", clock)
    printer_config = flashforge.PrinterConfig(3, "ADV4", "flashforge_tcp", "192.168.0.61", 8899)

    class Trickle(FakeSocket):
        def recv(self, size):
            return b"x"

    driver = flashforge.FlashforgeTcpDriver(printer_config, connect=lambda a, timeout=None: Trickle(idle_replies))
    with pytest.raises(DriverError):
        driver.read()
