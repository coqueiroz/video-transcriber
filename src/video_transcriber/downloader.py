"""Audio download with yt-dlp and handling of local files."""

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
    """Failed to download or extract the audio from a link."""


@dataclass
class AudioSource:
    """Audio (or video) file ready to be transcribed."""

    path: Path
    title: str
    origin: str
    is_temporary: bool


class _YtDlpLogger:
    """Routes yt-dlp messages to logging (errors are reported by the caller)."""

    def debug(self, msg: str) -> None:
        logger.debug(msg)

    def info(self, msg: str) -> None:
        logger.debug(msg)

    def warning(self, msg: str) -> None:
        logger.debug(msg)

    def error(self, msg: str) -> None:
        logger.debug(msg)


def ffmpeg_available() -> bool:
    """Whether the ffmpeg executable is on the PATH."""
    return shutil.which("ffmpeg") is not None


def is_url(value: str) -> bool:
    """Whether the text looks like an http(s) link."""
    return value.strip().lower().startswith(("http://", "https://"))


def local_source(path: Path) -> AudioSource:
    """Use an existing local file, without downloading anything."""
    return AudioSource(path=path, title=path.stem, origin=str(path), is_temporary=False)


def build_options(
    dest_dir: Path, progress_hook: ProgressHook | None = None, extract_audio: bool = True
) -> dict[str, Any]:
    """Build yt-dlp options that download only the audio.

    With `extract_audio=False` the file keeps its original container (m4a, webm, mp4...),
    which faster-whisper decodes on its own, so ffmpeg is not required.
    """
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "logger": _YtDlpLogger(),
    }
    if extract_audio:
        options["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_CODEC, "preferredquality": "128"}
        ]
    if progress_hook:
        options["progress_hooks"] = [progress_hook]
    return options


def _downloaded_path(info: dict[str, Any], dest_dir: Path, extract_audio: bool) -> Path:
    """Find the final file path after post-processing."""
    for item in info.get("requested_downloads") or []:
        if item.get("filepath"):
            return Path(item["filepath"])
    ext = AUDIO_CODEC if extract_audio else info.get("ext", "")
    return dest_dir / f"{info['id']}.{ext}"


def download_audio(
    url: str,
    dest_dir: Path,
    progress_hook: ProgressHook | None = None,
    extract_audio: bool = True,
) -> AudioSource:
    """Download the audio from any link supported by yt-dlp."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = build_options(dest_dir, progress_hook, extract_audio)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc
    if not info:
        raise DownloadError(f"No information returned for {url}")

    path = _downloaded_path(info, dest_dir, extract_audio)
    if not path.exists():
        raise DownloadError(f"Audio file not found after download: {path}")
    title = info.get("title") or info.get("id") or "audio"
    return AudioSource(path=path, title=title, origin=url, is_temporary=True)
