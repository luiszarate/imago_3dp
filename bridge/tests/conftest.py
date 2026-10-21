"""Shared fakes: no test ever opens a real socket or HTTP connection."""
import io
import json
import re
import socket
from pathlib import Path

import pytest

from imago_bridge.remote_config import PrinterConfig

FIXTURES = Path(__file__).parent / "fixtures"

# Synthetic secret values (never real ones) to prove the whitelist drops them.
FAKE_SECRETS = {
    "wifipasswd": "FAKE-WIFI-PASSWORD-1234",
    "ssid": "FAKE-SSID-PLANTA",
    "apclissid": "FAKE-APCLI-SSID",
    "apclimac": "FA:KE:00:11:22:33",
    "ownerId": "FAKE-OWNER-ID-9876",
    "DIDString": "FAKE-DID-STRING",
    "APILicense": "FAKE-API-LICENSE",
    "InitString": "FAKE-INIT-STRING",
}


def load_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_flashforge(name):
    """Split a captured TCP transcript into replies keyed by command (~M119, ...)."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    blocks = re.split(r"(?=^CMD M\d+ Received\.)", text, flags=re.M)
    replies = {}
    for block in blocks:
        match = re.match(r"CMD (M\d+) Received\.", block)
        if match:
            replies["~" + match.group(1)] = block
    return replies


def printer(driver="creality_box", host="192.168.0.248", port=81, workcenter_id=12, camera_url=None, code="3DP-01"):
    return PrinterConfig(
        workcenter_id=workcenter_id, code=code, driver=driver, host=host, port=port, camera_url=camera_url
    )


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, chunk_size=None):
        super().__init__(body)
        self.chunk_size = chunk_size

    def read1(self, size=-1):
        if self.chunk_size:
            size = min(size, self.chunk_size) if size and size > 0 else self.chunk_size
        return super().read1(size)

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    """Records requests; returns canned bodies or raises canned errors in order."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, FakeResponse):
            return result
        return FakeResponse(result if isinstance(result, bytes) else json.dumps(result).encode())


class FakeSocket:
    """Answers each whitelisted command with the captured reply."""

    def __init__(self, replies, split=None):
        self.replies = replies
        self.sent = []
        self.pending = b""
        self.split = split
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)
        command = data.decode().strip()
        self.pending += self.replies[command].replace("\n", "\r\n").encode()

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        if not self.pending:
            raise socket.timeout("timed out")
        size = min(size, self.split or size)
        chunk, self.pending = self.pending[:size], self.pending[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real connection attempt fails the test (no printer or Odoo is ever contacted)."""

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def idle_replies():
    replies = load_flashforge("flashforge_idle.txt")
    replies["~M115"] = (
        "CMD M115 Received.\nMachine Type: Flashforge Adventurer 4\nMachine Name: Adventurer4\n"
        "Firmware: v2.3.3\nSN: FAKE-SERIAL\nX: 220 Y: 200 Z: 250\nTool Count: 1\nok\n"
    )
    return replies


@pytest.fixture
def env():
    """BridgeService with fake Odoo client, fake drivers and a manual clock."""
    from service_fakes import make_env

    environment = make_env()
    yield environment
    environment["service"].close()
