"""B-04: JPEG extraction from an MJPEG multipart stream, with byte and time caps."""
import base64
import itertools

import pytest
from conftest import FakeOpener, FakeResponse

from imago_bridge.camera import (
    CameraError,
    extract_jpeg,
    fetch_snapshot,
    read_first_frame,
    snapshot_b64,
    snapshot_due,
)

FRAME_1 = b"\xff\xd8\xff\xe0" + b"JFIF-frame-one" + b"\x00" * 200 + b"\xff\xd9"
FRAME_2 = b"\xff\xd8\xff\xe0" + b"JFIF-frame-two" + b"\x11" * 300 + b"\xff\xd9"
CAMERA_URL = "http://192.168.0.61:8080/?action=stream"


def mjpeg_stream(*frames, boundary=b"boundarydonotcross"):
    parts = [b"HTTP-ish preamble\r\n"]
    for frame in frames:
        parts.append(
            b"--" + boundary + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
        )
    return b"".join(parts)


def test_extracts_first_complete_frame():
    stream = FakeResponse(mjpeg_stream(FRAME_1, FRAME_2), chunk_size=37)
    frame = read_first_frame(stream)
    assert frame == FRAME_1
    assert frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")


def test_extract_needs_both_markers():
    assert extract_jpeg(b"--b\r\n\xff\xd8 partial") is None
    assert extract_jpeg(b"no jpeg here") is None
    assert extract_jpeg(b"\xff\xd9 \xff\xd8abc\xff\xd9") == b"\xff\xd8abc\xff\xd9"


def test_respects_byte_cap():
    huge = b"\xff\xd8" + b"\x00" * 5000  # never ends
    stream = FakeResponse(huge + b"\xff\xd9", chunk_size=512)
    with pytest.raises(CameraError):
        read_first_frame(stream, max_bytes=2048)
    assert stream.tell() <= 2048 + 512  # stopped near the cap, not at the end


def test_never_reads_past_cap_plus_one():
    stream = FakeResponse(b"\x00" * 10000)
    with pytest.raises(CameraError):
        read_first_frame(stream, max_bytes=4096)
    assert stream.tell() <= 4097


def test_respects_time_cap():
    ticks = itertools.count(0.0, 2.0)
    stream = FakeResponse(b"\xff\xd8" + b"\x00" * 10000, chunk_size=10)
    with pytest.raises(CameraError):
        read_first_frame(stream, max_seconds=5.0, clock=lambda: next(ticks))


def test_stream_end_without_frame():
    with pytest.raises(CameraError):
        read_first_frame(FakeResponse(b"\xff\xd8 cut"))


def test_fetch_snapshot_from_same_host():
    opener = FakeOpener(FakeResponse(mjpeg_stream(FRAME_1, FRAME_2)))
    assert fetch_snapshot(CAMERA_URL, "192.168.0.61", opener=opener) == FRAME_1
    assert opener.requests[0][0].full_url == CAMERA_URL


@pytest.mark.parametrize(
    "url, host",
    [
        ("http://192.168.0.62:8080/?action=stream", "192.168.0.61"),  # other host
        ("https://192.168.0.61:8080/?action=stream", "192.168.0.61"),  # not plain http
        ("http://camera.local:8080/", "camera.local"),  # DNS name
        ("http://8.8.8.8:8080/", "8.8.8.8"),  # public
        ("http://user:pw@192.168.0.61:8080/", "192.168.0.61"),  # credentials
        ("http://127.0.0.1:8080/", "127.0.0.1"),  # loopback
    ],
)
def test_fetch_refuses_foreign_or_public_hosts(url, host):
    opener = FakeOpener(FakeResponse(mjpeg_stream(FRAME_1)))
    with pytest.raises(CameraError):
        fetch_snapshot(url, host, opener=opener)
    assert opener.requests == []


def test_snapshot_b64_and_size_limit():
    encoded = snapshot_b64(CAMERA_URL, "192.168.0.61", fetch=lambda url, host: FRAME_1)
    assert base64.b64decode(encoded) == FRAME_1
    big = b"\xff\xd8" + b"\x00" * (513 * 1024) + b"\xff\xd9"
    assert snapshot_b64(CAMERA_URL, "192.168.0.61", fetch=lambda url, host: big) is None


def test_snapshot_b64_swallows_camera_errors():
    def broken(url, host):
        raise CameraError("boom")

    assert snapshot_b64(CAMERA_URL, "192.168.0.61", fetch=broken) is None


def test_snapshot_due():
    assert snapshot_due(None, 10.0, 30)
    assert not snapshot_due(0.0, 29.0, 30)
    assert snapshot_due(0.0, 30.0, 30)
