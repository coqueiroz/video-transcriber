"""Testes do downloader com yt-dlp mockado."""

from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp

from video_transcriber import downloader


class FakeYDL:
    """Substituto de yt_dlp.YoutubeDL que cria um arquivo falso."""

    last_options: dict = {}

    def __init__(self, options: dict) -> None:
        FakeYDL.last_options = options
        self.dest = Path(options["outtmpl"]).parent

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict:
        path = self.dest / "abc123.mp3"
        path.write_bytes(b"fake audio")
        return {
            "id": "abc123",
            "title": "Meu vídeo",
            "requested_downloads": [{"filepath": str(path)}],
        }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=x", True),
        ("HTTP://tiktok.com/@a/video/1", True),
        ("  https://instagram.com/reel/x  ", True),
        ("video.mp4", False),
        ("ftp://exemplo.com/a", False),
        ("", False),
    ],
)
def test_is_url(value: str, expected: bool) -> None:
    assert downloader.is_url(value) is expected


def test_ffmpeg_available(monkeypatch) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    assert downloader.ffmpeg_available() is False
    monkeypatch.setattr(downloader.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    assert downloader.ffmpeg_available() is True


def test_local_source(tmp_path) -> None:
    file = tmp_path / "aula 01.mp4"
    file.write_bytes(b"x")
    source = downloader.local_source(file)
    assert source.title == "aula 01"
    assert source.path == file
    assert source.is_temporary is False


def test_build_options_audio_only(tmp_path) -> None:
    hook = lambda d: None  # noqa: E731
    options = downloader.build_options(tmp_path, hook)
    assert options["format"] == "bestaudio/best"
    assert options["noplaylist"] is True
    assert options["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert options["progress_hooks"] == [hook]


def test_download_audio(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    source = downloader.download_audio("https://youtu.be/abc123", tmp_path / "tmp")
    assert source.title == "Meu vídeo"
    assert source.path.read_bytes() == b"fake audio"
    assert source.is_temporary is True
    assert source.origin == "https://youtu.be/abc123"


def test_download_audio_wraps_errors(monkeypatch, tmp_path) -> None:
    class Failing(FakeYDL):
        def extract_info(self, url: str, download: bool = True) -> dict:
            raise yt_dlp.utils.DownloadError("Video unavailable")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Failing)
    with pytest.raises(downloader.DownloadError, match="Video unavailable"):
        downloader.download_audio("https://youtu.be/x", tmp_path)


def test_download_audio_missing_file(monkeypatch, tmp_path) -> None:
    class NoFile(FakeYDL):
        def extract_info(self, url: str, download: bool = True) -> dict:
            return {"id": "zzz", "title": "t"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", NoFile)
    with pytest.raises(downloader.DownloadError, match="não encontrado"):
        downloader.download_audio("https://youtu.be/x", tmp_path)


def test_download_error_strips_prefix(monkeypatch, tmp_path) -> None:
    class Failing(FakeYDL):
        def extract_info(self, url: str, download: bool = True) -> dict:
            raise yt_dlp.utils.DownloadError("ERROR: Private video")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Failing)
    with pytest.raises(downloader.DownloadError) as info:
        downloader.download_audio("https://youtu.be/x", tmp_path)
    assert str(info.value) == "Private video"
