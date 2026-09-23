"""Download de áudio com yt-dlp e tratamento de arquivos locais."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

AUDIO_CODEC = "mp3"

ProgressHook = Callable[[dict[str, Any]], None]

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    """Falha ao baixar ou extrair o áudio de um link."""


@dataclass
class AudioSource:
    """Arquivo de áudio pronto para transcrição."""

    path: Path
    title: str
    origin: str
    is_temporary: bool


class _YtDlpLogger:
    """Encaminha mensagens do yt-dlp para o logging (erros são tratados por quem chama)."""

    def debug(self, msg: str) -> None:
        logger.debug(msg)

    def info(self, msg: str) -> None:
        logger.debug(msg)

    def warning(self, msg: str) -> None:
        logger.debug(msg)

    def error(self, msg: str) -> None:
        logger.debug(msg)


def ffmpeg_available() -> bool:
    """Indica se o executável do ffmpeg está no PATH."""
    return shutil.which("ffmpeg") is not None


def is_url(value: str) -> bool:
    """Indica se o texto parece um link http(s)."""
    return value.strip().lower().startswith(("http://", "https://"))


def local_source(path: Path) -> AudioSource:
    """Usa um arquivo local existente, sem download."""
    return AudioSource(path=path, title=path.stem, origin=str(path), is_temporary=False)


def build_options(dest_dir: Path, progress_hook: ProgressHook | None = None) -> dict[str, Any]:
    """Monta as opções do yt-dlp para baixar apenas o áudio."""
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "logger": _YtDlpLogger(),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_CODEC, "preferredquality": "128"}
        ],
    }
    if progress_hook:
        options["progress_hooks"] = [progress_hook]
    return options


def _downloaded_path(info: dict[str, Any], dest_dir: Path) -> Path:
    """Descobre o caminho final do áudio após o pós-processamento."""
    for item in info.get("requested_downloads") or []:
        if item.get("filepath"):
            return Path(item["filepath"])
    return dest_dir / f"{info['id']}.{AUDIO_CODEC}"


def download_audio(
    url: str, dest_dir: Path, progress_hook: ProgressHook | None = None
) -> AudioSource:
    """Baixa o áudio de um link suportado pelo yt-dlp e converte com ffmpeg."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(build_options(dest_dir, progress_hook)) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc
    if not info:
        raise DownloadError(f"Nenhuma informação retornada para {url}")

    path = _downloaded_path(info, dest_dir)
    if not path.exists():
        raise DownloadError(f"Áudio não encontrado após o download: {path}")
    title = info.get("title") or info.get("id") or "audio"
    return AudioSource(path=path, title=title, origin=url, is_temporary=True)
