# -*- coding: utf-8 -*-
"""Validation of the bridge → Odoo payload (SPEC 16.6). Pure functions, no ORM."""
import base64
import binascii
import io
import math
import re
from datetime import datetime, timedelta

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow ships with Odoo 14
    Image = None

PRINTER_STATES = ('offline', 'idle', 'printing', 'paused', 'finished', 'error', 'unknown')
PAYLOAD_KEYS = {'bridge_version', 'sent_at', 'printers'}
PRINTER_KEYS = {
    'workcenter_id', 'reachable', 'state', 'progress', 'nozzle_temp', 'nozzle_target', 'bed_temp',
    'bed_target', 'layer', 'layer_total', 'time_left_min', 'job_time_min', 'file_name', 'error_text',
    'snapshot_jpeg_b64',
}
TEMP_RANGE = (-20.0, 400.0)
MAX_COUNT = 100000
MAX_SNAPSHOT_BYTES = 512 * 1024
# base64 of MAX_SNAPSHOT_BYTES plus slack: checked before decoding anything.
MAX_SNAPSHOT_B64 = MAX_SNAPSHOT_BYTES * 4 // 3 + 16
MAX_SNAPSHOT_PIXELS = 4000 * 4000
SENT_AT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z?$')
CONTROL_CHARS_RE = re.compile('[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]')
MAX_FUTURE = timedelta(minutes=5)
TEXT_LIMITS = {'file_name': 128, 'error_text': 256, 'bridge_version': 32}


class TelemetryError(ValueError):
    """A printer entry (or the whole payload) does not follow the contract."""


def parse_sent_at(value, now):
    """UTC ISO timestamp ('2026-10-21T16:00:00Z'); rejects clocks more than 5 min ahead."""
    if not isinstance(value, str) or not SENT_AT_RE.match(value):
        raise TelemetryError('sent_at')
    try:
        moment = datetime.strptime(value.rstrip('Z')[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        raise TelemetryError('sent_at')
    if moment - now > MAX_FUTURE:
        raise TelemetryError('clock_skew')
    return moment


def _number(item, key, low=None, high=None, integer=False):
    value = item.get(key)
    if value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryError(key)
    # NaN/inf pass every comparison and would make the dashboard JSON invalid.
    if isinstance(value, float) and not math.isfinite(value):
        raise TelemetryError(key)
    if integer and (int(value) != value or abs(value) > MAX_COUNT):
        raise TelemetryError(key)
    if (low is not None and value < low) or (high is not None and value > high):
        raise TelemetryError(key)
    return int(value) if integer else float(value)


def _text(item, key):
    value = item.get(key)
    if value is None:
        return False
    if not isinstance(value, str):
        raise TelemetryError(key)
    return CONTROL_CHARS_RE.sub('', value).strip()[:TEXT_LIMITS[key]] or False


def decode_snapshot(value):
    """JPEG bytes or None; never raises (a bad photo must not drop the status, A-28)."""
    if not value or not isinstance(value, str) or len(value) > MAX_SNAPSHOT_B64:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > MAX_SNAPSHOT_BYTES or not raw.startswith(b'\xff\xd8'):
        return None
    return raw if _is_real_jpeg(raw) else None


def _is_real_jpeg(raw):
    """A JPEG Pillow can parse, of a sane size (not just the 2-byte magic)."""
    if Image is None:
        return True
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format != 'JPEG' or image.width * image.height > MAX_SNAPSHOT_PIXELS:
            return False
        image.verify()
    except Exception:  # Pillow raises many error types on hostile input
        return False
    return True


def parse_printer(item):
    """Validated status values for imago.printer.status, plus the raw snapshot (or None)."""
    if not isinstance(item, dict):
        raise TelemetryError('format')
    unknown = set(item) - PRINTER_KEYS
    if unknown:
        # Only key names are reported back, never their values (A-23).
        raise TelemetryError('unknown_keys:%s' % ','.join(sorted(unknown)))
    if item.get('state') not in PRINTER_STATES:
        raise TelemetryError('state')
    if not isinstance(item.get('reachable', True), bool):
        raise TelemetryError('reachable')
    values = {
        'reachable': item.get('reachable', True),
        'state': item['state'],
        'progress': _number(item, 'progress', 0, 100),
        # The CR-M4 reports no progress for prints started from USB: unknown is not 0 %.
        'progress_known': item.get('progress') is not None,
        'nozzle_temp': _number(item, 'nozzle_temp', *TEMP_RANGE),
        'nozzle_target': _number(item, 'nozzle_target', *TEMP_RANGE),
        'bed_temp': _number(item, 'bed_temp', *TEMP_RANGE),
        'bed_target': _number(item, 'bed_target', *TEMP_RANGE),
        'layer': _number(item, 'layer', 0, integer=True),
        'layer_total': _number(item, 'layer_total', 0, integer=True),
        'time_left_min': _number(item, 'time_left_min', 0, integer=True),
        'job_time_min': _number(item, 'job_time_min', 0, integer=True),
        'file_name': _text(item, 'file_name'),
        'error_text': _text(item, 'error_text'),
    }
    return values, decode_snapshot(item.get('snapshot_jpeg_b64'))
