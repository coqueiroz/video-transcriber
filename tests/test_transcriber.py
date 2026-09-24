"""Transcriber tests with a fake model."""

from __future__ import annotations

from pathlib import Path

from video_transcriber import transcriber


def test_resolve_device(monkeypatch) -> None:
    assert transcriber.resolve_device("cpu") == ("cpu", "int8")
    assert transcriber.resolve_device("cuda") == ("cuda", "float16")

    monkeypatch.setattr(transcriber, "cuda_available", lambda: False)
    assert transcriber.resolve_device("auto") == ("cpu", "int8")
    monkeypatch.setattr(transcriber, "cuda_available", lambda: True)
    assert transcriber.resolve_device("auto") == ("cuda", "float16")


def test_transcribe(fake_model) -> None:
    progress: list[tuple[float, float]] = []
    result = transcriber.transcribe(
        fake_model,
        Path("audio.mp3"),
        language="pt",
        on_progress=lambda d, t: progress.append((d, t)),
    )

    assert fake_model.calls[0]["path"] == "audio.mp3"
    assert fake_model.calls[0]["language"] == "pt"
    assert result.language == "pt"
    assert result.duration == 2.0
    assert [s.text for s in result.segments] == [" Hello.", " How are you?"]
    assert result.text == "Hello. How are you?"
    assert progress[-1] == (2.0, 2.0)


def test_transcribe_without_callback(fake_model) -> None:
    result = transcriber.transcribe(fake_model, Path("a.wav"))
    assert fake_model.calls[0]["language"] is None
    assert len(result.segments) == 2


def write_tone_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    """Mono WAV whose sample value encodes the time, so cuts can be checked exactly."""
    import wave

    import numpy as np

    t = np.arange(int(seconds * rate))
    samples = ((t // rate) * 1000).astype("<i2")  # value = 1000 × whole second
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())


def test_decode_range_cuts_exactly(tmp_path: Path) -> None:
    audio = tmp_path / "ten_seconds.wav"
    write_tone_wav(audio, 10)

    part = transcriber.decode_range(audio, 3.0, 6.0)

    assert len(part) == 3 * 16000
    # the first sample belongs to second 3, the last to second 5
    assert round(part[0] * 32768) == 3000
    assert round(part[-1] * 32768) == 5000


def test_decode_range_until_the_end_and_past_it(tmp_path: Path) -> None:
    audio = tmp_path / "ten_seconds.wav"
    write_tone_wav(audio, 10)
    assert len(transcriber.decode_range(audio, 8.0, None)) == 2 * 16000
    assert len(transcriber.decode_range(audio, 8.0, 99.0)) == 2 * 16000
    assert transcriber.decode_range(audio, 12.0, None).size == 0


def test_transcribe_range_shifts_timestamps(tmp_path: Path, fake_model) -> None:
    audio = tmp_path / "ten_seconds.wav"
    write_tone_wav(audio, 10)

    result = transcriber.transcribe(fake_model, audio, start=4.0, end=7.0)

    sent = fake_model.calls[0]["path"]
    assert len(sent) == 3 * 16000  # only the excerpt was sent to the model
    assert [(s.start, s.end) for s in result.segments] == [(4.0, 5.0), (5.0, 6.0)]


def test_transcribe_time_offset_for_downloaded_sections(fake_model) -> None:
    result = transcriber.transcribe(fake_model, Path("section.m4a"), time_offset=90.0)
    assert fake_model.calls[0]["path"] == "section.m4a"
    assert result.segments[0].start == 90.0


def test_transcribe_range_after_the_end(tmp_path: Path, fake_model) -> None:
    import pytest

    audio = tmp_path / "ten_seconds.wav"
    write_tone_wav(audio, 10)
    with pytest.raises(transcriber.EmptyRangeError):
        transcriber.transcribe(fake_model, audio, start=30.0)
