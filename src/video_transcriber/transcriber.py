"""Transcrição de áudio com faster-whisper."""

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
    """Trecho transcrito com tempos em segundos."""

    start: float
    end: float
    text: str


@dataclass
class Transcription:
    """Resultado completo de uma transcrição."""

    segments: list[Segment] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0

    @property
    def text(self) -> str:
        """Texto completo em um único parágrafo."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


def cuda_available() -> bool:
    """Indica se há GPU CUDA utilizável pelo CTranslate2."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - qualquer falha significa "sem CUDA"
        return False


def resolve_device(device: str) -> tuple[str, str]:
    """Resolve o dispositivo ("auto", "cpu", "cuda") e o compute_type adequado."""
    if device == "auto":
        device = "cuda" if cuda_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def load_model(model_name: str, device: str = "auto") -> WhisperModel:
    """Carrega (e baixa, na primeira vez) o modelo Whisper."""
    from faster_whisper import WhisperModel

    resolved, compute_type = resolve_device(device)
    return WhisperModel(model_name, device=resolved, compute_type=compute_type)


def transcribe(
    model: Any,
    audio_path: Path,
    language: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> Transcription:
    """Transcreve um arquivo de áudio/vídeo, reportando o progresso em segundos."""
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
