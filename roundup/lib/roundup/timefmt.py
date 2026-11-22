"""Time helpers: backend timestamps to ISO 8601, durations, stale threshold parsing."""
from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Optional

_UTC = _dt.timezone.utc
_DURATION_RE = re.compile(r"^(\d+)([dhm])$")
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60}


def _fmt(dt: _dt.datetime) -> str:
    return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def us_to_iso(us) -> Optional[str]:
    """Microseconds since the epoch to ISO 8601 UTC; None or 0 gives None."""
    if not us:
        return None
    us = int(us)
    return _fmt(_dt.datetime.fromtimestamp(us // 1_000_000, tz=_UTC))


def ms_to_iso(ms) -> Optional[str]:
    """Milliseconds since the epoch to ISO 8601 UTC; None or 0 gives None."""
    if not ms:
        return None
    ms = int(ms)
    return _fmt(_dt.datetime.fromtimestamp(ms // 1000, tz=_UTC))


def parse_iso(value: Optional[str]) -> Optional[_dt.datetime]:
    """Parse an ISO 8601 string (with Z or an offset) into an aware datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # Python 3.9 fromisoformat accepts only 3 or 6 fractional digits.
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m and m.group(2):
        frac = (m.group(2)[1:] + "000000")[:6]
        text = "%s.%s%s" % (m.group(1), frac, m.group(3))
    dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt


def now_iso() -> str:
    """The snapshot time: $ROUNDUP_NOW when set (tests), else the current UTC time."""
    override = os.environ.get("ROUNDUP_NOW")
    if override:
        return _fmt(parse_iso(override))
    return _fmt(_dt.datetime.now(tz=_UTC))


def seconds_between(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[int]:
    """Whole seconds from start to end (never negative); None if either is missing."""
    start, end = parse_iso(start_iso), parse_iso(end_iso)
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


def parse_duration(value: str) -> int:
    """Parse "3d", "12h" or "30m" into seconds. Raises ValueError otherwise."""
    m = _DURATION_RE.match((value or "").strip())
    if not m or int(m.group(1)) <= 0:
        raise ValueError("invalid duration: %s (use Nd, Nh or Nm)" % value)
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def format_duration(seconds) -> str:
    """Compact duration: "5d 3h", "2h 10m", "4m" (two units at most)."""
    seconds = max(0, int(seconds or 0))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%dd %dh" % (days, hours) if hours else "%dd" % days
    if hours:
        return "%dh %dm" % (hours, minutes) if minutes else "%dh" % hours
    return "%dm" % minutes
