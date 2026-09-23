"""Fluxo completo de uma entrada: obter áudio, transcrever e gravar as saídas.

Compartilhado pela CLI e pela interface gráfica; não depende de nenhuma das duas.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_transcriber import downloader, formatters, transcriber

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Resultado de uma entrada processada com sucesso."""

    title: str
    transcription: transcriber.Transcription
    outputs: list[Path] = field(default_factory=list)


def resolve_source(
    item: str, temp_dir: Path, download_hook: downloader.ProgressHook | None = None
) -> downloader.AudioSource:
    """Obtém o áudio de uma entrada: arquivo local ou download via yt-dlp."""
    path = Path(item).expanduser()
    if path.is_file():
        return downloader.local_source(path)
    if not downloader.is_url(item):
        raise ValueError(f"Não é um link válido nem um arquivo existente: {item}")
    return downloader.download_audio(item, temp_dir, progress_hook=download_hook)


def keep_audio(source: downloader.AudioSource, output_dir: Path) -> Path:
    """Move o áudio temporário para a pasta de saída com um nome legível."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{formatters.sanitize_filename(source.title)}{source.path.suffix}"
    shutil.move(str(source.path), target)
    return target


def run_job(
    item: str,
    model: Any,
    *,
    output_dir: Path,
    formats: list[str],
    language: str | None = None,
    keep: bool = False,
    download_hook: downloader.ProgressHook | None = None,
    on_source: Any = None,
    on_progress: transcriber.ProgressCallback | None = None,
) -> JobResult:
    """Baixa (se necessário), transcreve e grava as saídas de uma entrada."""
    with tempfile.TemporaryDirectory(prefix="video-transcriber-") as tmp:
        source = resolve_source(item, Path(tmp), download_hook)
        if on_source:
            on_source(source)

        result = transcriber.transcribe(
            model, source.path, language=language, on_progress=on_progress
        )
        if not result.segments:
            logger.warning("Nenhuma fala detectada em %s", item)

        metadata = {"titulo": source.title, "origem": source.origin}
        outputs = formatters.write_outputs(result, output_dir, source.title, formats, metadata)
        if keep and source.is_temporary:
            outputs.append(keep_audio(source, output_dir))
    return JobResult(title=source.title, transcription=result, outputs=outputs)
