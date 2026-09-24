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
from video_transcriber.timecodes import TimeRange, format_timecode

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Result of a successfully processed input."""

    title: str
    transcription: transcriber.Transcription
    origin: str = ""
    time_range: TimeRange = field(default_factory=TimeRange)
    outputs: list[Path] = field(default_factory=list)

    @property
    def metadata(self) -> dict[str, Any]:
        """Metadata written to the JSON output."""
        data: dict[str, Any] = {"title": self.title, "source": self.origin}
        if not self.time_range.is_full:
            data["range"] = {"start": self.time_range.start, "end": self.time_range.end}
        return data

    @property
    def output_name(self) -> str:
        """Base filename; a partial transcript gets its range appended."""
        return output_name(self.title, self.time_range)


def output_name(title: str, time_range: TimeRange | None = None) -> str:
    """Filename stem for a transcript, e.g. "Talk (1-34-50 to 1-40-00)"."""
    if time_range is None or time_range.is_full:
        return title
    start = format_timecode(time_range.start).replace(":", "-")
    end = format_timecode(time_range.end).replace(":", "-") if time_range.end else "end"
    return f"{title} ({start} to {end})"


def resolve_source(
    item: str,
    temp_dir: Path,
    download_hook: downloader.ProgressHook | None = None,
    extract_audio: bool = True,
    time_range: TimeRange | None = None,
) -> downloader.AudioSource:
    """Get the audio for an input: a local file or a download via yt-dlp.

    The time range is checked against the media's duration before any heavy work.
    """
    path = Path(item).expanduser()
    if path.is_file():
        if time_range is not None:
            time_range.validate(downloader.media_duration(path))
        return downloader.local_source(path)
    if not downloader.is_url(item):
        raise ValueError(f"Not a valid link or an existing file: {item}")
    return downloader.download_audio(
        item,
        temp_dir,
        progress_hook=download_hook,
        extract_audio=extract_audio,
        section=time_range,
    )


def keep_audio(source: downloader.AudioSource, output_dir: Path, name: str = "") -> Path:
    """Move the temporary audio to the output folder with a readable name."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = (
        output_dir / f"{formatters.sanitize_filename(name or source.title)}{source.path.suffix}"
    )
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
    time_range: TimeRange | None = None,
    download_hook: downloader.ProgressHook | None = None,
    on_source: Any = None,
    on_progress: transcriber.ProgressCallback | None = None,
) -> JobResult:
    """Download (if needed) and transcribe one input.

    With `time_range`, only that part is transcribed (timestamps stay relative to the
    original video). Files are written only when `output_dir` and `formats` are given;
    otherwise nothing is stored on disk except the temporary audio, deleted at the end.
    """
    time_range = time_range or TimeRange()
    time_range.validate()
    with tempfile.TemporaryDirectory(prefix="video-transcriber-") as tmp:
        source = resolve_source(
            item,
            Path(tmp),
            download_hook,
            extract_audio,
            None if time_range.is_full else time_range,
        )
        if on_source:
            on_source(source)

        if source.time_offset > 0:  # only the section was downloaded
            cut = {"time_offset": source.time_offset}
        elif not time_range.is_full:  # whole audio available: cut the part out
            cut = {"start": time_range.start, "end": time_range.end}
        else:
            cut = {}
        result = transcriber.transcribe(
            model, source.path, language=language, on_progress=on_progress, **cut
        )
        if not result.segments:
            logger.warning("No speech detected in %s", item)

        job = JobResult(
            title=source.title, transcription=result, origin=source.origin, time_range=time_range
        )
        if output_dir is not None and formats:
            job.outputs = formatters.write_outputs(
                result, output_dir, job.output_name, formats, job.metadata
            )
            if keep and source.is_temporary:
                job.outputs.append(keep_audio(source, output_dir, job.output_name))
    return job
