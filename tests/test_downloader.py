"""Downloader tests with yt-dlp mocked."""

from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp

from video_transcriber import downloader


class FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL that creates a fake file."""

    last_options: dict = {}

    def __init__(self, options: dict) -> None:
        FakeYDL.last_options = options
        self.options = options
        self.dest = Path(options.get("outtmpl", ".")).parent

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict:
        info = {"id": "abc123", "title": "My video", "duration": 600}
        return self.process_ie_result(info, download=True) if download else info

    def process_ie_result(self, info: dict, download: bool = True) -> dict:
        path = self.dest / "abc123.mp3"
        path.write_bytes(b"fake audio")
        return {**info, "requested_downloads": [{"filepath": str(path)}]}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=x", True),
        ("HTTP://tiktok.com/@a/video/1", True),
        ("  https://instagram.com/reel/x  ", True),
        ("video.mp4", False),
        ("ftp://example.com/a", False),
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
    file = tmp_path / "lecture 01.mp4"
    file.write_bytes(b"x")
    source = downloader.local_source(file)
    assert source.title == "lecture 01"
    assert source.path == file
    assert source.is_temporary is False


def test_build_options_audio_only(tmp_path) -> None:
    hook = lambda d: None  # noqa: E731
    options = downloader.build_options(tmp_path, hook)
    assert options["format"] == "bestaudio/best"
    assert options["noplaylist"] is True
    assert options["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert options["progress_hooks"] == [hook]


def test_build_options_without_ffmpeg(tmp_path) -> None:
    options = downloader.build_options(tmp_path, extract_audio=False)
    assert "postprocessors" not in options
    assert options["format"] == "bestaudio/best"


def test_download_audio(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    source = downloader.download_audio("https://youtu.be/abc123", tmp_path / "tmp")
    assert source.title == "My video"
    assert source.path.read_bytes() == b"fake audio"
    assert source.is_temporary is True
    assert source.origin == "https://youtu.be/abc123"


def test_download_audio_without_conversion_uses_original_ext(monkeypatch, tmp_path) -> None:
    class NoRequestedDownloads(FakeYDL):
        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            (self.dest / "vid.m4a").write_bytes(b"x")
            return {"id": "vid", "ext": "m4a", "title": "t"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", NoRequestedDownloads)
    source = downloader.download_audio("https://youtu.be/vid", tmp_path, extract_audio=False)
    assert source.path.name == "vid.m4a"
    assert "postprocessors" not in NoRequestedDownloads.last_options


def test_download_audio_wraps_errors(monkeypatch, tmp_path) -> None:
    class Failing(FakeYDL):
        def extract_info(self, url: str, download: bool = True) -> dict:
            raise yt_dlp.utils.DownloadError("Video unavailable")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Failing)
    with pytest.raises(downloader.DownloadError, match="Video unavailable"):
        downloader.download_audio("https://youtu.be/x", tmp_path)


def test_download_audio_missing_file(monkeypatch, tmp_path) -> None:
    class NoFile(FakeYDL):
        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            return {"id": "zzz", "title": "t"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", NoFile)
    with pytest.raises(downloader.DownloadError, match="not found"):
        downloader.download_audio("https://youtu.be/x", tmp_path)


def test_download_error_strips_prefix(monkeypatch, tmp_path) -> None:
    class Failing(FakeYDL):
        def extract_info(self, url: str, download: bool = True) -> dict:
            raise yt_dlp.utils.DownloadError("ERROR: Private video")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Failing)
    with pytest.raises(downloader.DownloadError) as info:
        downloader.download_audio("https://youtu.be/x", tmp_path)
    assert str(info.value) == "Private video"


def test_build_options_section_needs_ffmpeg(monkeypatch, tmp_path) -> None:
    from video_transcriber.timecodes import TimeRange

    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    options = downloader.build_options(tmp_path, section=TimeRange(60, 120))
    ranges = list(options["download_ranges"]({"duration": 600}, None))
    assert ranges == [{"start_time": 60, "end_time": 120}]

    open_ended = downloader.build_options(tmp_path, section=TimeRange(60, None))
    assert list(open_ended["download_ranges"]({}, None))[0]["end_time"] == float("inf")

    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    assert "download_ranges" not in downloader.build_options(tmp_path, section=TimeRange(60, 120))
    assert "download_ranges" not in downloader.build_options(tmp_path, section=TimeRange())


def test_download_section_reports_offset(monkeypatch, tmp_path) -> None:
    from video_transcriber.timecodes import TimeRange

    class Sectioned(FakeYDL):
        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            path = self.dest / "abc123.m4a"
            path.write_bytes(b"x")
            return {**info, "requested_downloads": [{"filepath": str(path), "section_start": 60}]}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Sectioned)
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(downloader, "media_duration", lambda path: 60.0)
    source = downloader.download_audio(
        "https://youtu.be/abc123", tmp_path, extract_audio=False, section=TimeRange(60, 120)
    )
    assert source.time_offset == 60


def test_section_failure_falls_back_to_whole_audio(monkeypatch, tmp_path) -> None:
    from video_transcriber.timecodes import TimeRange

    attempts: list[bool] = []

    class RangesUnsupported(FakeYDL):
        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            with_ranges = "download_ranges" in self.options
            attempts.append(with_ranges)
            if with_ranges:
                raise yt_dlp.utils.DownloadError("ERROR: server doesn't allow seeking")
            path = self.dest / "abc123.m4a"
            path.write_bytes(b"whole")
            return {**info, "requested_downloads": [{"filepath": str(path)}]}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", RangesUnsupported)
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    source = downloader.download_audio(
        "https://youtu.be/abc123", tmp_path, extract_audio=False, section=TimeRange(60, 120)
    )

    assert attempts == [True, False]
    assert source.time_offset == 0.0  # whole audio: the pipeline cuts the part out
    assert source.path.read_bytes() == b"whole"


def test_download_rejects_range_past_the_end_before_downloading(monkeypatch, tmp_path) -> None:
    from video_transcriber.timecodes import TimecodeError, TimeRange

    class MustNotDownload(FakeYDL):
        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            raise AssertionError("should not download")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", MustNotDownload)
    with pytest.raises(TimecodeError, match="only 10:00 long"):
        downloader.download_audio("https://youtu.be/x", tmp_path, section=TimeRange(0, 900))


def test_probe_link(monkeypatch) -> None:
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    info = downloader.probe("https://youtu.be/abc123")
    assert (info.title, info.duration) == ("My video", 600.0)
    assert FakeYDL.last_options["skip_download"] is True


def test_probe_local_file(tmp_path) -> None:
    import wave

    audio = tmp_path / "clip.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000 * 3)
    info = downloader.probe(str(audio))
    assert info.title == "clip"
    assert info.duration == pytest.approx(3.0, abs=0.05)


def test_probe_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        downloader.probe("not a link")
