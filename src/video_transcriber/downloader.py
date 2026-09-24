"""Audio download with yt-dlp and handling of local files."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from video_transcriber.timecodes import TimeRange

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
    # Where this file starts in the original video (>0 when only a section was downloaded).
    time_offset: float = 0.0


@dataclass
class MediaInfo:
    """Title and duration of a link or local file, fetched without downloading it."""

    title: str
    duration: float | None


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


def media_duration(path: Path) -> float | None:
    """Duration of a local audio/video file in seconds (None if unknown)."""
    import av

    try:
        with av.open(str(path), metadata_errors="ignore") as container:
            if container.duration:
                return container.duration / av.time_base
            stream = container.streams.audio[0] if container.streams.audio else None
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except (av.FFmpegError, OSError, IndexError):
        logger.debug("Could not read the duration of %s", path, exc_info=True)
    return None


def probe(item: str) -> MediaInfo:
    """Get the title and duration of a link or local file without downloading it."""
    path = Path(item).expanduser()
    if path.is_file():
        return MediaInfo(title=path.stem, duration=media_duration(path))
    if not is_url(item):
        raise ValueError(f"Not a valid link or an existing file: {item}")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "logger": _YtDlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(item, download=False) or {}
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc
    duration = info.get("duration")
    return MediaInfo(
        title=info.get("title") or info.get("id") or item,
        duration=float(duration) if duration else None,
    )


def build_options(
    dest_dir: Path,
    progress_hook: ProgressHook | None = None,
    extract_audio: bool = True,
    section: TimeRange | None = None,
) -> dict[str, Any]:
    """Build yt-dlp options that download only the audio.

    With `extract_audio=False` the file keeps its original container (m4a, webm, mp4...),
    which faster-whisper decodes on its own, so ffmpeg is not required. `section` asks
    yt-dlp to download only that part of the video (when ffmpeg is available; otherwise
    the whole audio is downloaded and the part is cut out before transcribing).
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
    if section is not None and not section.is_full and ffmpeg_available():
        end = section.end if section.end is not None else float("inf")
        options["download_ranges"] = yt_dlp.utils.download_range_func(None, [(section.start, end)])
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


def _section_start(info: dict[str, Any]) -> float:
    """Where the downloaded file starts in the original video (0 if it's the whole thing)."""
    for item in info.get("requested_downloads") or []:
        if item.get("section_start") is not None:
            return float(item["section_start"])
    return float(info.get("section_start") or 0.0)


def _fetch(url: str, dest_dir: Path, options: dict[str, Any], section: TimeRange | None) -> dict:
    """Run yt-dlp once: read the video info, check the section, then download."""
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise DownloadError(f"No information returned for {url}")
            if section is not None and info.get("duration"):
                section.validate(float(info["duration"]))
            return ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc


def download_audio(
    url: str,
    dest_dir: Path,
    progress_hook: ProgressHook | None = None,
    extract_audio: bool = True,
    section: TimeRange | None = None,
) -> AudioSource:
    """Download the audio from any link supported by yt-dlp.

    With `section` (and ffmpeg available) only that part is downloaded; the returned
    `time_offset` says where the file starts in the original video. If downloading just
    the part fails (some servers don't allow it), the whole audio is downloaded instead
    and the caller cuts the part out. The section is checked against the video's
    duration before anything is downloaded.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = build_options(dest_dir, progress_hook, extract_audio, section)
    info: dict | None = None
    if "download_ranges" in options:
        try:
            info = _fetch(url, dest_dir, options, section)
            path = _downloaded_path(info, dest_dir, extract_audio)
            if not path.exists() or not media_duration(path):
                raise DownloadError("the downloaded part is empty")
        except DownloadError as exc:
            logger.info("Could not download only the part (%s); getting the whole audio", exc)
            for leftover in dest_dir.iterdir():
                leftover.unlink(missing_ok=True)
            options.pop("download_ranges")
            info = None
    if info is None:
        info = _fetch(url, dest_dir, options, section)

    path = _downloaded_path(info, dest_dir, extract_audio)
    if not path.exists():
        raise DownloadError(f"Audio file not found after download: {path}")
    title = info.get("title") or info.get("id") or "audio"
    offset = _section_start(info) if "download_ranges" in options else 0.0
    return AudioSource(path=path, title=title, origin=url, is_temporary=True, time_offset=offset)
