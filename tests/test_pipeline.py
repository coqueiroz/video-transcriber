"""Tests for the shared flow, focused on time ranges."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from video_transcriber import downloader, pipeline
from video_transcriber.timecodes import TimecodeError, TimeRange


def silent_wav(path: Path, seconds: int) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000 * seconds)
    return path


def test_output_name() -> None:
    assert pipeline.output_name("Talk") == "Talk"
    assert pipeline.output_name("Talk", TimeRange()) == "Talk"
    assert pipeline.output_name("Talk", TimeRange(5690, 6000)) == "Talk (1-34-50 to 1-40-00)"
    assert pipeline.output_name("Talk", TimeRange(60)) == "Talk (1-00 to end)"


def test_local_file_range_is_cut_and_labelled(tmp_path, fake_model) -> None:
    audio = silent_wav(tmp_path / "lecture.wav", 10)
    out = tmp_path / "out"

    job = pipeline.run_job(
        str(audio), fake_model, output_dir=out, formats=["json"], time_range=TimeRange(2, 5)
    )

    assert len(fake_model.calls[0]["path"]) == 3 * 16000
    assert job.transcription.segments[0].start == 2.0
    assert job.metadata["range"] == {"start": 2, "end": 5}
    assert [p.name for p in job.outputs] == ["lecture (0-02 to 0-05).json"]


def test_local_file_range_past_the_end(tmp_path, fake_model) -> None:
    audio = silent_wav(tmp_path / "short.wav", 3)
    with pytest.raises(TimecodeError, match="after the end of the video"):
        pipeline.run_job(str(audio), fake_model, time_range=TimeRange(10, None))
    assert fake_model.calls == []


def test_invalid_range_fails_before_anything(fake_model) -> None:
    with pytest.raises(TimecodeError):
        pipeline.run_job("https://youtu.be/x", fake_model, time_range=TimeRange(50, 20))


def test_downloaded_section_uses_offset(monkeypatch, tmp_path, fake_model) -> None:
    seen = {}

    def fake_download(url, dest_dir, progress_hook=None, extract_audio=True, section=None):
        seen["section"] = section
        path = dest_dir / "part.m4a"
        path.write_bytes(b"x")
        return downloader.AudioSource(path, "Talk", url, True, time_offset=section.start)

    monkeypatch.setattr(downloader, "download_audio", fake_download)
    job = pipeline.run_job("https://youtu.be/x", fake_model, time_range=TimeRange(90, 150))

    assert seen["section"] == TimeRange(90, 150)
    assert fake_model.calls[0]["path"].endswith("part.m4a")  # no extra cutting
    assert job.transcription.segments[0].start == 90.0


def test_full_download_is_cut_when_no_section(monkeypatch, tmp_path, fake_model) -> None:
    def fake_download(url, dest_dir, progress_hook=None, extract_audio=True, section=None):
        return downloader.AudioSource(silent_wav(dest_dir / "all.wav", 10), "Talk", url, True)

    monkeypatch.setattr(downloader, "download_audio", fake_download)
    job = pipeline.run_job("https://youtu.be/x", fake_model, time_range=TimeRange(6, None))

    assert len(fake_model.calls[0]["path"]) == 4 * 16000
    assert job.transcription.segments[0].start == 6.0
