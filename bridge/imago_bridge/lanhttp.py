"""Plain-HTTP GET helpers for LAN devices: no proxies, no redirects, capped reads and a
wall-clock deadline for the whole exchange.

Per-socket timeouts alone do not bound a request: a hostile device can send one byte
every 2.9 s and hold a worker thread forever (headers included). The connection used
here shrinks the socket timeout before every receive so that connect + headers + body
never exceed ``total_seconds``.
"""
import http.client
import io
import socket
import time
import urllib.request
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit

from .netguard import is_allowed_host

DEFAULT_TOTAL_SECONDS = 5.0


class DeadlineExceeded(socket.timeout):
    """The whole HTTP exchange took longer than its total deadline."""


class _DeadlineRaw(io.RawIOBase):
    """Raw reader over a socket that never blocks past ``deadline`` (monotonic)."""

    def __init__(self, sock: socket.socket, deadline: float, clock: Callable[[], float]) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline
        self._clock = clock

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise DeadlineExceeded("total deadline exceeded")
        self._sock.settimeout(min(remaining, self._sock.gettimeout() or remaining))
        return self._sock.recv_into(buffer)


class _DeadlineSocket:
    """Wraps the connection socket; ``makefile`` returns a deadline-bound reader."""

    def __init__(self, sock: socket.socket, deadline: float, clock: Callable[[], float]) -> None:
        self._sock = sock
        self._deadline = deadline
        self._clock = clock

    def makefile(self, mode: str = "rb", *args, **kwargs):
        if "b" not in mode or "r" not in mode:
            raise ValueError("only binary read mode is supported")
        return io.BufferedReader(_DeadlineRaw(self._sock, self._deadline, self._clock))

    def __getattr__(self, name: str):
        return getattr(self._sock, name)


def _connection_class(total_seconds: float, clock: Callable[[], float]):
    class DeadlineHTTPConnection(http.client.HTTPConnection):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._deadline = clock() + total_seconds

        def connect(self) -> None:
            remaining = self._deadline - clock()
            if remaining <= 0:
                raise DeadlineExceeded("total deadline exceeded")
            if self.timeout is None or self.timeout > remaining:
                self.timeout = remaining
            super().connect()
            self.sock = _DeadlineSocket(self.sock, self._deadline, clock)

    return DeadlineHTTPConnection


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, total_seconds: float, clock: Callable[[], float]) -> None:
        super().__init__()
        self._total_seconds = total_seconds
        self._clock = clock

    def http_open(self, req):
        return self.do_open(_connection_class(self._total_seconds, self._clock), req)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A printer must never be able to send the bridge to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def build_lan_opener(
    total_seconds: float = DEFAULT_TOTAL_SECONDS, clock: Callable[[], float] = time.monotonic
) -> urllib.request.OpenerDirector:
    """Opener that ignores HTTP(S)_PROXY variables and bounds every request in time."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect(), _DeadlineHTTPHandler(total_seconds, clock)
    )


def open_lan_url(opener: urllib.request.OpenerDirector, url: str, host: str, timeout: float):
    """GET ``url`` after re-checking that its host is the allowed printer host."""
    if not is_allowed_host(host) or urlsplit(url).hostname != host or urlsplit(url).scheme != "http":
        raise PermissionError("host not allowed by netguard")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "imago-3dp-bridge"})
    return opener.open(request, timeout=timeout)


def read_capped(
    response,
    max_bytes: int,
    deadline_seconds: float = DEFAULT_TOTAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    chunk_size: int = 16384,
) -> bytes:
    """Read the whole body; ValueError past ``max_bytes``, DeadlineExceeded past the deadline."""
    deadline = clock() + deadline_seconds
    read = getattr(response, "read1", response.read)
    chunks = []
    total = 0
    while True:
        if clock() > deadline:
            raise DeadlineExceeded("body not received within %.0f s" % deadline_seconds)
        chunk = read(min(chunk_size, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("response larger than %d bytes" % max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
