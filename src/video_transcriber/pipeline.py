"""Full flow for one input: get the audio, transcribe it and (optionally) write outputs.

Shared by the CLI and the desktop app; depends on neither.
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
    """Result of a successfully processed input."""

    title: str
    transcription: transcriber.Transcription
    origin: str = ""
    outputs: list[Path] = field(default_factory=list)

    @property
    def metadata(self) -> dict[str, str]:
        """Metadata written to the JSON output."""
        return {"title": self.title, "source": self.origin}


def resolve_source(
    item: str,
    temp_dir: Path,
    download_hook: downloader.ProgressHook | None = None,
    extract_audio: bool = True,
) -> downloader.AudioSource:
    """Get the audio for an input: a local file or a download via yt-dlp."""
    path = Path(item).expanduser()
    if path.is_file():
        return downloader.local_source(path)
    if not downloader.is_url(item):
        raise ValueError(f"Not a valid link or an existing file: {item}")
    return downloader.download_audio(
        item, temp_dir, progress_hook=download_hook, extract_audio=extract_audio
    )


def keep_audio(source: downloader.AudioSource, output_dir: Path) -> Path:
    """Move the temporary audio to the output folder with a readable name."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{formatters.sanitize_filename(source.title)}{source.path.suffix}"
    shutil.move(str(source.path), target)
    return target


def run_job(
    item: str,
    model: Any,
    *,
    output_dir: Path | None = None,
    formats: list[str] | None = None,
    language: str | None = None,
    keep: bool = False,
    extract_audio: bool = True,
    download_hook: downloader.ProgressHook | None = None,
    on_source: Any = None,
    on_progress: transcriber.ProgressCallback | None = None,
) -> JobResult:
    """Download (if needed) and transcribe one input.

    Files are written only when `output_dir` and `formats` are given; otherwise nothing
    is stored on disk except the temporary audio, which is deleted at the end.
    """
    with tempfile.TemporaryDirectory(prefix="video-transcriber-") as tmp:
        source = resolve_source(item, Path(tmp), download_hook, extract_audio)
        if on_source:
            on_source(source)

        result = transcriber.transcribe(
            model, source.path, language=language, on_progress=on_progress
        )
        if not result.segments:
            logger.warning("No speech detected in %s", item)

        job = JobResult(title=source.title, transcription=result, origin=source.origin)
        if output_dir is not None and formats:
            job.outputs = formatters.write_outputs(
                result, output_dir, source.title, formats, job.metadata
            )
            if keep and source.is_temporary:
                job.outputs.append(keep_audio(source, output_dir))
    return job
