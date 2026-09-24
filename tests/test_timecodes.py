"""Tests for reading, validating and formatting time positions."""

from __future__ import annotations

import pytest

from video_transcriber.timecodes import (
    TimecodeError,
    TimeRange,
    format_timecode,
    parse_timecode,
    start_from_url,
)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("0", 0),
        ("50", 50),
        ("94:50", 94 * 60 + 50),
        ("1:34:50", 3600 + 34 * 60 + 50),
        ("01:34:50", 3600 + 34 * 60 + 50),
        (" 00:00:07 ", 7),
        ("2:05", 125),
    ],
)
def test_parse_timecode(text: str, seconds: int) -> None:
    assert parse_timecode(text) == seconds


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("1:75", "up to 59"),
        ("1:00:60", "up to 59"),
        ("1.34.50", "Can't read"),
        ("1h34m", "Can't read"),
        ("", "Can't read"),
        ("1:2:3:4", "Can't read"),
        ("-5", "Can't read"),
    ],
)
def test_parse_timecode_rejects(text: str, message: str) -> None:
    with pytest.raises(TimecodeError, match=message):
        parse_timecode(text)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0:00"), (7, "0:07"), (125, "2:05"), (3600 + 34 * 60 + 50, "1:34:50"), (59.6, "1:00")],
)
def test_format_timecode(seconds: float, text: str) -> None:
    assert format_timecode(seconds) == text


def test_time_range_basics() -> None:
    assert TimeRange().is_full
    assert not TimeRange(start=10).is_full
    assert not TimeRange(end=10).is_full
    assert TimeRange(5694, 6000).label() == "1:34:54–1:40:00"
    assert TimeRange(60).label() == "1:00–end"


@pytest.mark.parametrize(
    ("time_range", "duration", "message"),
    [
        (TimeRange(10, 10), None, '"To" must be after "From"'),
        (TimeRange(20, 10), None, '"To" must be after "From"'),
        (TimeRange(-1, None), None, "negative"),
        (TimeRange(700, None), 600, "after the end of the video"),
        (TimeRange(0, 700), 600, "only 10:00 long"),
    ],
)
def test_time_range_validate_rejects(time_range, duration, message) -> None:
    with pytest.raises(TimecodeError, match=message):
        time_range.validate(duration)


def test_time_range_validate_accepts() -> None:
    TimeRange(0, 600).validate(600)
    TimeRange(0, 600.4).validate(600)  # durations are rounded by platforms
    TimeRange(100, None).validate(600)
    TimeRange(100, None).validate(None)


@pytest.mark.parametrize(
    ("url", "seconds"),
    [
        ("https://www.youtube.com/watch?v=abc&t=3750", 3750),
        ("https://www.youtube.com/watch?v=abc&t=3750s", 3750),
        ("https://youtu.be/abc?t=1h2m30s", 3750),
        ("https://youtu.be/abc?t=2m", 120),
        ("https://www.youtube.com/watch?v=abc#t=45", 45),
        ("https://www.youtube.com/watch?v=abc", None),
        ("https://www.youtube.com/watch?v=abc&t=banana", None),
        ("not a url", None),
    ],
)
def test_start_from_url(url: str, seconds) -> None:
    assert start_from_url(url) == seconds
