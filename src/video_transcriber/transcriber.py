"""Speech-to-text with faster-whisper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

MODELS = ("tiny", "base", "small", "medium", "large-v3")

ProgressCallback = Callable[[float, float], None]


@dataclass
class Segment:
    """Transcribed chunk with start/end times in seconds."""

    start: float
    end: float
    text: str


@dataclass
class Transcription:
    """Full result of a transcription."""

    segments: list[Segment] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0

    @property
    def text(self) -> str:
        """Whole transcript as a single paragraph."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


def cuda_available() -> bool:
    """Whether CTranslate2 can use a CUDA GPU."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - any failure means "no CUDA"
        return False


def resolve_device(device: str) -> tuple[str, str]:
    """Resolve the device ("auto", "cpu", "cuda") and a suitable compute_type."""
    if device == "auto":
        device = "cuda" if cuda_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def load_model(model_name: str, device: str = "auto") -> WhisperModel:
    """Load the Whisper model (downloading it the first time)."""
    from faster_whisper import WhisperModel

    resolved, compute_type = resolve_device(device)
    return WhisperModel(model_name, device=resolved, compute_type=compute_type)


def transcribe(
    model: Any,
    audio_path: Path,
    language: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> Transcription:
    """Transcribe an audio/video file, reporting progress in seconds of audio."""
    raw_segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True)
    result = Transcription(
        language=info.language,
        language_probability=info.language_probability,
        duration=info.duration,
    )
    for seg in raw_segments:
        result.segments.append(Segment(start=seg.start, end=seg.end, text=seg.text))
        if on_progress:
            on_progress(seg.end, info.duration)
    if on_progress:
        on_progress(info.duration, info.duration)
    return result
