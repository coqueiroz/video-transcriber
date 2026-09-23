"""Geração dos arquivos de saída (txt, srt, json) e sanitização de nomes."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from video_transcriber.transcriber import Transcription

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
DEFAULT_NAME = "sem_titulo"


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Converte um título qualquer em um nome de arquivo seguro em todos os sistemas."""
    name = unicodedata.normalize("NFC", name or "")
    name = INVALID_CHARS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:max_length].rstrip(" .")
    if not name:
        return DEFAULT_NAME
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = f"_{name}"
    return name


def format_timestamp(seconds: float, separator: str = ",") -> str:
    """Formata segundos como HH:MM:SS,mmm (padrão SRT)."""
    total_ms = max(0, round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def to_txt(transcription: Transcription, metadata: dict[str, Any] | None = None) -> str:
    """Texto corrido, um segmento por linha."""
    lines = (seg.text.strip() for seg in transcription.segments)
    return "\n".join(line for line in lines if line) + "\n"


def to_srt(transcription: Transcription, metadata: dict[str, Any] | None = None) -> str:
    """Legenda no formato SubRip (.srt)."""
    blocks = []
    segments = (seg for seg in transcription.segments if seg.text.strip())
    for index, seg in enumerate(segments, start=1):
        start, end = format_timestamp(seg.start), format_timestamp(seg.end)
        blocks.append(f"{index}\n{start} --> {end}\n{seg.text.strip()}\n")
    return "\n".join(blocks)


def to_json(transcription: Transcription, metadata: dict[str, Any] | None = None) -> str:
    """JSON com metadados, texto completo e segmentos com tempos."""
    data = {
        **(metadata or {}),
        "idioma": transcription.language,
        "probabilidade_idioma": round(transcription.language_probability, 4),
        "duracao": round(transcription.duration, 3),
        "texto": transcription.text,
        "segmentos": [
            {"inicio": round(s.start, 3), "fim": round(s.end, 3), "texto": s.text.strip()}
            for s in transcription.segments
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


FORMATTERS: dict[str, Callable[[Transcription, dict[str, Any] | None], str]] = {
    "txt": to_txt,
    "srt": to_srt,
    "json": to_json,
}


def write_outputs(
    transcription: Transcription,
    output_dir: Path,
    base_name: str,
    formats: Iterable[str],
    metadata: dict[str, Any] | None = None,
) -> list[Path]:
    """Grava a transcrição nos formatos pedidos e devolve os caminhos criados."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_filename(base_name)
    written = []
    for fmt in formats:
        path = output_dir / f"{stem}.{fmt}"
        path.write_text(FORMATTERS[fmt](transcription, metadata), encoding="utf-8")
        written.append(path)
    return written
