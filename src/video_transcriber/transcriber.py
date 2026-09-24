"""Speech-to-text with faster-whisper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from faster_whisper import WhisperModel

MODELS = ("tiny", "base", "small", "medium", "large-v3")
SAMPLE_RATE = 16000

ProgressCallback = Callable[[float, float], None]


class EmptyRangeError(ValueError):
    """The requested part of the audio contains no samples (e.g. start after the end)."""


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


def decode_range(
    path: Path, start: float = 0.0, end: float | None = None, sampling_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """Decode only [start, end) of an audio/video file as 16 kHz mono float32.

    Seeks close to `start` instead of decoding from the beginning, so a short excerpt
    of a long video is fast and doesn't load the whole audio into memory.
    """
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    chunks: list[np.ndarray] = []
    first_time: float | None = None
    with av.open(str(path), metadata_errors="ignore") as container:
        stream = container.streams.audio[0]
        if start > 0 and stream.time_base:
            container.seek(int(start / stream.time_base), stream=stream)
        clock = 0.0
        for frame in container.decode(stream):
            frame_start = frame.time if frame.time is not None else clock
            clock = frame_start + frame.samples / frame.sample_rate
            if clock <= start:
                continue
            if end is not None and frame_start >= end:
                break
            if first_time is None:
                first_time = frame_start
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
        chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))

    if not chunks or first_time is None:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    audio = audio[max(0, round((start - first_time) * sampling_rate)) :]
    if end is not None:
        audio = audio[: round((end - start) * sampling_rate)]
    return audio


def transcribe(
    model: Any,
    audio_path: Path,
    language: str | None = None,
    on_progress: ProgressCallback | None = None,
    start: float = 0.0,
    end: float | None = None,
    time_offset: float = 0.0,
) -> Transcription:
    """Transcribe an audio/video file, reporting progress in seconds of audio.

    With `start`/`end`, only that part is transcribed; timestamps stay relative to the
    original video. `time_offset` shifts timestamps for files that were already cut
    (e.g. a downloaded section that starts at `time_offset` in the original video).
    """
    audio: Any = str(audio_path)
    if start > 0 or end is not None:
        audio = decode_range(audio_path, start, end)
        if audio.size == 0:
            raise EmptyRangeError("The chosen start is after the end of the audio.")
        time_offset += start

    raw_segments, info = model.transcribe(audio, language=language, vad_filter=True)
    result = Transcription(
        language=info.language,
        language_probability=info.language_probability,
        duration=info.duration,
    )
    for seg in raw_segments:
        result.segments.append(
            Segment(start=seg.start + time_offset, end=seg.end + time_offset, text=seg.text)
        )
        if on_progress:
            on_progress(seg.end, info.duration)
    if on_progress:
        on_progress(info.duration, info.duration)
    return result
