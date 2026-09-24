"""Parsing, validation and formatting of time positions like "1:34:50"."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_COLON_FORMAT = re.compile(r"^\d{1,2}(?::\d{1,2}){0,2}$")
_YOUTUBE_T = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")


class TimecodeError(ValueError):
    """A time position that can't be read or doesn't make sense."""


@dataclass(frozen=True)
class TimeRange:
    """Part of a video to transcribe, in seconds (`end=None` means until the end)."""

    start: float = 0.0
    end: float | None = None

    @property
    def is_full(self) -> bool:
        return self.start <= 0 and self.end is None

    def validate(self, duration: float | None = None) -> None:
        """Raise TimecodeError if the range is impossible (optionally for a known duration)."""
        if self.start < 0 or (self.end is not None and self.end < 0):
            raise TimecodeError("Times can't be negative.")
        if self.end is not None and self.end <= self.start:
            raise TimecodeError('"To" must be after "From".')
        if duration:
            if self.start >= duration:
                raise TimecodeError(
                    f"The start ({format_timecode(self.start)}) is after the end of the video "
                    f"({format_timecode(duration)})."
                )
            if self.end is not None and self.end > duration + 0.5:
                raise TimecodeError(f"This video is only {format_timecode(duration)} long.")

    def label(self) -> str:
        """Human-readable range, e.g. "1:34:50–1:40:00" or "1:34:50–end"."""
        end = format_timecode(self.end) if self.end is not None else "end"
        return f"{format_timecode(self.start)}–{end}"


def parse_timecode(value: str) -> float:
    """Read "SS", "MM:SS" or "HH:MM:SS" (minutes and seconds up to 59 after a colon)."""
    text = (value or "").strip()
    if not _COLON_FORMAT.match(text):
        raise TimecodeError(
            f'Can\'t read "{value}". Use HH:MM:SS, MM:SS or seconds, e.g. 1:34:50 or 94:50.'
        )
    parts = [int(p) for p in text.split(":")]
    if len(parts) > 1 and any(p > 59 for p in parts[1:]):
        raise TimecodeError(f'"{value}": minutes and seconds go up to 59.')
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return float(seconds)


def format_timecode(seconds: float) -> str:
    """Format seconds as "M:SS" or "H:MM:SS"."""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def start_from_url(url: str) -> float | None:
    """Start time embedded in a link, e.g. YouTube's "?t=3750" or "&t=1h2m30s"."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    values = parse_qs(parsed.query).get("t") or parse_qs(parsed.query).get("start")
    if not values and parsed.fragment.startswith("t="):
        values = [parsed.fragment[2:]]
    if not values:
        return None
    match = _YOUTUBE_T.match(values[0].strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, secs = (int(g) if g else 0 for g in match.groups())
    return float(hours * 3600 + minutes * 60 + secs)
