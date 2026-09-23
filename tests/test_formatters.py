"""Tests for output formatting and filename sanitization."""

from __future__ import annotations

import json

import pytest

from video_transcriber import formatters
from video_transcriber.formatters import format_timestamp, sanitize_filename
from video_transcriber.transcriber import Transcription


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Normal video", "Normal video"),
        ('a<b>c:d"e/f\\g|h?i*j', "a b c d e f g h i j"),
        ("  too   many spaces  ", "too many spaces"),
        ("new\nline\ttab", "new line tab"),
        ("ends with dots...", "ends with dots"),
        ("Emoji 🎉 and accents çãé", "Emoji 🎉 and accents çãé"),
        ("", "untitled"),
        ("???", "untitled"),
        ("...", "untitled"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("CONSOLE", "CONSOLE"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_normalizes_unicode() -> None:
    decomposed = "Café"  # "e" + combining accent
    assert sanitize_filename(decomposed) == "Café"


def test_sanitize_filename_truncates() -> None:
    result = sanitize_filename("a" * 50 + " " + "b" * 200, max_length=51)
    assert result == "a" * 50
    assert len(sanitize_filename("x" * 500)) == 120


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (61.001, "00:01:01,001"),
        (3661.042, "01:01:01,042"),
        (59.9999, "00:01:00,000"),
        (-3, "00:00:00,000"),
    ],
)
def test_format_timestamp(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_format_timestamp_custom_separator() -> None:
    assert format_timestamp(1.25, separator=".") == "00:00:01.250"


def test_to_txt_skips_empty_segments(transcription: Transcription) -> None:
    assert formatters.to_txt(transcription) == "Hello, world!\nOlá, segunda frase.\n"


def test_to_srt(transcription: Transcription) -> None:
    expected = (
        "1\n00:00:00,000 --> 00:00:02,500\nHello, world!\n"
        "\n"
        "2\n00:00:03,000 --> 01:01:01,042\nOlá, segunda frase.\n"
    )
    assert formatters.to_srt(transcription) == expected


def test_to_json(transcription: Transcription) -> None:
    data = json.loads(formatters.to_json(transcription, {"title": "Test", "source": "x"}))
    assert data["title"] == "Test"
    assert data["source"] == "x"
    assert data["language"] == "en"
    assert data["language_probability"] == 0.9877
    assert data["text"] == "Hello, world! Olá, segunda frase."
    assert data["segments"][0] == {"start": 0.0, "end": 2.5, "text": "Hello, world!"}
    assert len(data["segments"]) == 3


def test_to_json_keeps_accents() -> None:
    assert "ção" in formatters.to_json(Transcription(language="ção"))


def test_empty_transcription() -> None:
    empty = Transcription()
    assert formatters.to_txt(empty) == "\n"
    assert formatters.to_srt(empty) == ""


def test_write_outputs(tmp_path, transcription: Transcription) -> None:
    out = tmp_path / "out" / "sub"
    paths = formatters.write_outputs(transcription, out, "My: video?", ["txt", "srt", "json"])

    assert [p.name for p in paths] == ["My video.txt", "My video.srt", "My video.json"]
    assert all(p.exists() for p in paths)
    assert paths[0].read_text(encoding="utf-8").startswith("Hello, world!")
