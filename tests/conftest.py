"""Shared fixtures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from video_transcriber.transcriber import Segment, Transcription


@pytest.fixture
def transcription() -> Transcription:
    """Sample transcription with two segments and an empty one."""
    return Transcription(
        segments=[
            Segment(0.0, 2.5, " Hello, world!"),
            Segment(2.5, 2.6, "   "),
            Segment(3.0, 3661.042, " Olá, segunda frase."),
        ],
        language="en",
        language_probability=0.98765,
        duration=3662.0,
    )


class FakeModel:
    """Mimics the WhisperModel.transcribe interface."""

    def __init__(self, texts: list[str] | None = None) -> None:
        self.texts = texts if texts is not None else ["Hello.", "How are you?"]
        self.calls: list[dict] = []

    def transcribe(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        segments = (
            SimpleNamespace(start=float(i), end=float(i + 1), text=f" {t}")
            for i, t in enumerate(self.texts)
        )
        info = SimpleNamespace(
            language=kwargs.get("language") or "en",
            language_probability=0.9,
            duration=float(len(self.texts)),
        )
        return segments, info


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()
