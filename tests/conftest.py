"""Fixtures compartilhadas."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from video_transcriber.transcriber import Segment, Transcription


@pytest.fixture
def transcription() -> Transcription:
    """Transcrição de exemplo com dois segmentos e um vazio."""
    return Transcription(
        segments=[
            Segment(0.0, 2.5, " Olá, mundo!"),
            Segment(2.5, 2.6, "   "),
            Segment(3.0, 3661.042, " Segunda frase."),
        ],
        language="pt",
        language_probability=0.98765,
        duration=3662.0,
    )


class FakeModel:
    """Imita a interface de WhisperModel.transcribe."""

    def __init__(self, texts: list[str] | None = None) -> None:
        self.texts = texts or ["Olá.", "Tudo bem?"]
        self.calls: list[dict] = []

    def transcribe(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        segments = (
            SimpleNamespace(start=float(i), end=float(i + 1), text=f" {t}")
            for i, t in enumerate(self.texts)
        )
        info = SimpleNamespace(
            language=kwargs.get("language") or "pt",
            language_probability=0.9,
            duration=float(len(self.texts)),
        )
        return segments, info


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()
