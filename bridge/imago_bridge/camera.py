"""Camera snapshot (D-18): first complete JPEG frame of an MJPEG stream.

MJPG-Streamer on the Adventurer 4 only serves ``?action=stream`` (``snapshot`` does not
answer), so the bridge reads the multipart stream until the first ``FF D8 … FF D9``
frame and closes the connection. Hard limits: 2 MB read and 5 s per snapshot.
"""
import base64
import logging
import time
from typing import Callable, Optional
from urllib.error import URLError
from urllib.parse import urlsplit

from .lanhttp import build_lan_opener, open_lan_url
from .netguard import camera_host

_logger = logging.getLogger(__name__)

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_STREAM_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 5.0
MAX_SNAPSHOT_BYTES = 512 * 1024  # Odoo discards larger photos (SPEC 16.6)
CHUNK_SIZE = 16384


class CameraError(Exception):
    """No valid frame could be read within the limits."""


def extract_jpeg(buffer: bytes) -> Optional[bytes]:
    """The first complete JPEG (SOI … EOI) in ``buffer``, or None if not complete yet."""
    start = buffer.find(SOI)
    if start < 0:
        return None
    end = buffer.find(EOI, start + len(SOI))
    if end < 0:
        return None
    return buffer[start : end + len(EOI)]


def read_first_frame(
    response,
    max_bytes: int = MAX_STREAM_BYTES,
    max_seconds: float = MAX_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    """Read ``response`` until one full JPEG is buffered; enforce the byte and time caps."""
    deadline = clock() + max_seconds
    # read1 returns what is available instead of blocking until a full chunk arrives.
    read = getattr(response, "read1", response.read)
    buffer = b""
    while True:
        if clock() > deadline:
            raise CameraError("no complete frame within %.0f s" % max_seconds)
        chunk = read(min(CHUNK_SIZE, max_bytes - len(buffer) + 1))
        if not chunk:
            raise CameraError("stream ended before a complete frame")
        buffer += chunk
        frame = extract_jpeg(buffer)
        if frame is not None:
            return frame
        if len(buffer) > max_bytes:
            raise CameraError("no complete frame within %d bytes" % max_bytes)


def fetch_snapshot(camera_url: str, printer_host: str, opener=None, timeout: float = MAX_SECONDS) -> bytes:
    """One JPEG from ``camera_url``; only when its host is the printer's allowed host."""
    host = camera_host(camera_url, printer_host)
    if host is None or urlsplit(camera_url).hostname != host:
        raise CameraError("camera host not allowed")
    opener = opener or build_lan_opener(MAX_SECONDS)  # total deadline incl. connect and headers
    try:
        with open_lan_url(opener, camera_url, host, timeout) as response:
            return read_first_frame(response)
    except (URLError, OSError, ValueError) as error:
        raise CameraError("camera read failed: %s" % type(error).__name__) from None


def snapshot_b64(camera_url: str, printer_host: str, fetch=fetch_snapshot) -> Optional[str]:
    """Base64 of one frame for the payload, or None (camera errors never fail the status)."""
    try:
        frame = fetch(camera_url, printer_host)
    except CameraError as error:
        _logger.warning("Cámara de %s sin foto: %s", printer_host, error)
        return None
    if len(frame) > MAX_SNAPSHOT_BYTES:
        _logger.warning("Cámara de %s: foto de %d bytes descartada (máx. 512 KB).", printer_host, len(frame))
        return None
    return base64.b64encode(frame).decode("ascii")


def snapshot_due(last_taken: Optional[float], now: float, interval: float) -> bool:
    return last_taken is None or now - last_taken >= interval
