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
