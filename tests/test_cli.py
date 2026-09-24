"""CLI tests with download and model mocked."""

from __future__ import annotations

import re

import pytest
import typer
from typer.testing import CliRunner

from video_transcriber import cli, downloader, transcriber

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(result) -> str:
    """CLI output without color codes (CI terminals force colors on)."""
    return ANSI.sub("", result.output)


@pytest.fixture(autouse=True)
def mock_model(monkeypatch, fake_model):
    monkeypatch.setattr(transcriber, "load_model", lambda name, device: fake_model)
    monkeypatch.setattr(transcriber, "resolve_device", lambda device: ("cpu", "int8"))
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    return fake_model


@pytest.fixture
def download_calls(monkeypatch) -> list[dict]:
    """Mock yt-dlp: links containing "fail" raise, the others create a fake audio file."""
    calls: list[dict] = []

    def fake_download(url, dest_dir, progress_hook=None, extract_audio=True, section=None):
        calls.append({"url": url, "extract_audio": extract_audio, "section": section})
        if "fail" in url:
            raise downloader.DownloadError("video unavailable [private]")
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / ("id.mp3" if extract_audio else "id.m4a")
        path.write_bytes(b"x")
        if progress_hook:
            progress_hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 1})
            progress_hook({"status": "finished"})
        offset = section.start if section is not None else 0.0  # as if only the part came down
        return downloader.AudioSource(
            path, f"Title {url[-1]}", url, is_temporary=True, time_offset=offset
        )

    monkeypatch.setattr(downloader, "download_audio", fake_download)
    return calls


def test_collect_inputs_merges_and_dedupes(tmp_path) -> None:
    links = tmp_path / "links.txt"
    links.write_text("# comment\nhttps://a/1\n\n  https://a/2  \nhttps://a/1\n", encoding="utf-8")
    assert cli.collect_inputs(["https://a/0", "https://a/2"], links) == [
        "https://a/0",
        "https://a/2",
        "https://a/1",
    ]


@pytest.mark.parametrize(
    ("value", "expected"), [("txt", "txt"), (" SRT ", "srt"), ("all", "all"), ("todos", "all")]
)
def test_parse_format(value: str, expected: str) -> None:
    assert cli.parse_format(value) == expected


def test_parse_format_rejects_unknown() -> None:
    with pytest.raises(typer.BadParameter):
        cli.parse_format("docx")


def test_expand_formats() -> None:
    assert cli.expand_formats("all") == ["txt", "srt", "json"]
    assert cli.expand_formats("srt") == ["srt"]


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("auto", None), (" PT ", "pt")])
def test_normalize_language(value, expected) -> None:
    assert cli.normalize_language(value) == expected


def test_no_inputs_exits_with_error() -> None:
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2


def test_missing_ffmpeg_warns_and_skips_conversion(monkeypatch, tmp_path, download_calls) -> None:
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(out), "--keep-audio"])

    assert result.exit_code == 0, result.output
    assert "ffmpeg not found" in plain(result)
    assert download_calls[0]["extract_audio"] is False
    assert sorted(p.name for p in out.iterdir()) == ["Title 1.m4a", "Title 1.txt"]


def test_local_file_skips_download(monkeypatch, tmp_path, mock_model) -> None:
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    audio = tmp_path / "gravação.wav"
    audio.write_bytes(b"x")
    out = tmp_path / "out"

    result = runner.invoke(cli.app, [str(audio), "--output", str(out), "--format", "all"])

    assert result.exit_code == 0, result.output
    assert "ffmpeg not found" not in plain(result)
    assert sorted(p.name for p in out.iterdir()) == [
        "gravação.json",
        "gravação.srt",
        "gravação.txt",
    ]
    assert audio.exists()  # local files are never deleted
    assert mock_model.calls[0]["path"] == str(audio)


def test_links_file_continues_after_failure(tmp_path, download_calls, mock_model) -> None:
    links = tmp_path / "links.txt"
    links.write_text("https://ok/1\nhttps://fail/2\nhttps://ok/3\n", encoding="utf-8")
    out = tmp_path / "out"

    result = runner.invoke(
        cli.app, ["--file", str(links), "-o", str(out), "--language", "pt", "-f", "srt"]
    )

    assert result.exit_code == 1
    assert sorted(p.name for p in out.iterdir()) == ["Title 1.srt", "Title 3.srt"]
    assert "2 succeeded" in plain(result)
    assert "1 failed" in plain(result)
    assert "[private]" in plain(result)
    assert all(call["language"] == "pt" for call in mock_model.calls)


def test_portuguese_aliases_still_work(tmp_path, download_calls, mock_model) -> None:
    links = tmp_path / "links.txt"
    links.write_text("https://ok/1\n", encoding="utf-8")
    out = tmp_path / "saida"

    result = runner.invoke(
        cli.app,
        [
            "--arquivo",
            str(links),
            "--saida",
            str(out),
            "--idioma",
            "pt",
            "--formato",
            "todos",
            "--modelo",
            "base",
            "--manter-audio",
        ],
    )

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == [
        "Title 1.json",
        "Title 1.mp3",
        "Title 1.srt",
        "Title 1.txt",
    ]
    assert mock_model.calls[0]["language"] == "pt"


def test_temp_audio_removed_by_default(tmp_path, download_calls) -> None:
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert [p.name for p in out.iterdir()] == ["Title 1.txt"]


def test_invalid_input_is_reported(tmp_path) -> None:
    result = runner.invoke(cli.app, ["does_not_exist.mp4", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "1 failed" in plain(result)


def test_warns_when_no_speech(tmp_path, download_calls, mock_model) -> None:
    mock_model.texts = []
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "No speech detected" in plain(result)


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "video-transcriber" in plain(result)


def test_range_options(tmp_path, download_calls, mock_model, monkeypatch) -> None:
    import wave

    audio = tmp_path / "lecture.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000 * 10)
    out = tmp_path / "out"

    result = runner.invoke(
        cli.app, [str(audio), "--start", "0:02", "--end", "5", "-o", str(out), "-f", "srt"]
    )

    assert result.exit_code == 0, result.output
    assert "Transcribing only 0:02–0:05" in plain(result)
    assert [p.name for p in out.iterdir()] == ["lecture (0-02 to 0-05).srt"]
    assert (
        (out / "lecture (0-02 to 0-05).srt").read_text().splitlines()[1].startswith("00:00:02,000")
    )


def test_range_portuguese_aliases(tmp_path, download_calls) -> None:
    result = runner.invoke(
        cli.app, ["https://ok/1", "--inicio", "1:00", "--fim", "2:00", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert download_calls[0]["section"].start == 60
    assert download_calls[0]["section"].end == 120
    assert [p.name for p in tmp_path.iterdir()] == ["Title 1 (1-00 to 2-00).txt"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--start", "1:75"], "up to 59"),
        (["--end", "1.30"], "Can't read"),
        (["--start", "5:00", "--end", "4:00"], '"To" must be after "From"'),
    ],
)
def test_range_errors(args, message, mock_model) -> None:
    result = runner.invoke(cli.app, ["https://ok/1", *args])
    flat = " ".join(plain(result).replace("│", " ").split())  # undo the error box wrapping
    assert result.exit_code == 2
    assert message in flat
    assert mock_model.calls == []
