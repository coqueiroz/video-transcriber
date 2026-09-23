"""Command-line interface (`video-transcriber`, also available as `transcrever`)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from video_transcriber import __version__, downloader, formatters, pipeline, transcriber

logger = logging.getLogger("video_transcriber")
console = Console()

app = typer.Typer(
    add_completion=False,
    help="Download the audio from videos (YouTube, TikTok, Instagram...) and transcribe it.",
)

FFMPEG_WARNING = """[yellow]ffmpeg not found[/yellow] — downloads will keep their original audio \
format (m4a/webm/mp4), which works fine for transcription.
To convert downloads to mp3 (e.g. with --keep-audio), install it:
  • Windows: [cyan]winget install Gyan.FFmpeg[/cyan]
  • macOS:   [cyan]brew install ffmpeg[/cyan]
  • Linux:   [cyan]sudo apt install ffmpeg[/cyan]"""

FORMAT_ALIASES = {"todos": "all"}
FORMAT_CHOICES = (*formatters.FORMATTERS, "all")


class Model(str, Enum):
    tiny = "tiny"
    base = "base"
    small = "small"
    medium = "medium"
    large_v3 = "large-v3"


class Device(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"


@dataclass
class ItemResult:
    """Result of processing one input."""

    source: str
    ok: bool
    outputs: list[Path] = field(default_factory=list)
    error: str = ""


def setup_logging(verbose: bool) -> None:
    """Configure logging with rich formatting."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
        force=True,
    )
    logging.captureWarnings(True)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def read_links_file(path: Path) -> list[str]:
    """Read one input per line, ignoring blank lines and comments (#)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def collect_inputs(inputs: list[str] | None, links_file: Path | None) -> list[str]:
    """Merge inputs from the command line and the links file, without duplicates."""
    items = list(inputs or [])
    if links_file:
        items.extend(read_links_file(links_file))
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def parse_format(value: str) -> str:
    """Validate --format, accepting the Portuguese alias "todos"."""
    value = FORMAT_ALIASES.get(value.strip().lower(), value.strip().lower())
    if value not in FORMAT_CHOICES:
        raise typer.BadParameter(f"choose one of: {', '.join(FORMAT_CHOICES)}")
    return value


def expand_formats(fmt: str) -> list[str]:
    """Turn the --format value into a list of extensions."""
    return list(formatters.FORMATTERS) if fmt == "all" else [fmt]


def normalize_language(language: str | None) -> str | None:
    """Treat "auto" (or empty) as automatic language detection."""
    if not language or language.strip().lower() == "auto":
        return None
    return language.strip().lower()


def make_progress() -> Progress:
    """Progress bar used for downloads and transcriptions."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )


def process_item(
    item: str,
    model: Any,
    *,
    output_dir: Path,
    formats: list[str],
    language: str | None,
    keep: bool,
    extract_audio: bool = True,
) -> ItemResult:
    """Process one input while showing rich progress bars."""
    with make_progress() as progress:
        download_task = progress.add_task("Preparing", total=None)
        transcribe_task = progress.add_task("Transcribing", total=None, visible=False)

        def download_hook(status: dict[str, Any]) -> None:
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                done = status.get("downloaded_bytes", 0)
                progress.update(
                    download_task, description="Downloading audio", completed=done, total=total
                )
            elif status.get("status") == "finished":
                progress.update(download_task, description="Processing audio")

        def on_source(source: downloader.AudioSource) -> None:
            progress.update(download_task, visible=False)
            progress.update(transcribe_task, visible=True)
            console.print(f"  [bold]{escape(source.title)}[/bold]")

        job = pipeline.run_job(
            item,
            model,
            output_dir=output_dir,
            formats=formats,
            language=language,
            keep=keep,
            extract_audio=extract_audio,
            download_hook=download_hook,
            on_source=on_source,
            on_progress=lambda done, total: progress.update(
                transcribe_task, completed=done, total=total
            ),
        )
    return ItemResult(source=item, ok=True, outputs=job.outputs)


def print_summary(results: list[ItemResult]) -> None:
    """Print the final table of successes and failures."""
    table = Table(title="Summary", show_lines=True)
    table.add_column("Input", overflow="fold")
    table.add_column("Status", justify="center")
    table.add_column("Files / error", overflow="fold")
    for res in results:
        if res.ok:
            files = "\n".join(str(p) for p in res.outputs)
            table.add_row(escape(res.source), "[green]✓ ok[/green]", escape(files))
        else:
            table.add_row(escape(res.source), "[red]✗ failed[/red]", escape(res.error))
    console.print(table)

    ok = sum(r.ok for r in results)
    console.print(f"[green]{ok} succeeded[/green] · [red]{len(results) - ok} failed[/red]")


def version_callback(value: bool) -> None:
    if value:
        console.print(f"video-transcriber {__version__}")
        raise typer.Exit()


@app.command()
def main(
    inputs: Annotated[
        list[str] | None,
        typer.Argument(help="Video links and/or paths to local files.", show_default=False),
    ] = None,
    links_file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "--arquivo",
            "-a",
            help="Text file with one link per line.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    model: Annotated[
        Model, typer.Option("--model", "--modelo", "-m", help="Whisper model.")
    ] = Model.small,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            "--idioma",
            "-l",
            "-i",
            help='Language code, e.g. "en" or "pt". Default: auto-detect.',
        ),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "--formato",
            "-f",
            help="Output format: txt, srt, json or all.",
            callback=parse_format,
        ),
    ] = "txt",
    output_dir: Annotated[
        Path, typer.Option("--output", "--saida", "-o", help="Output folder.")
    ] = Path("transcriptions"),
    device: Annotated[
        Device, typer.Option("--device", "--dispositivo", "-d", help="Where to run the model.")
    ] = Device.auto,
    keep_audio: Annotated[
        bool,
        typer.Option(
            "--keep-audio", "--manter-audio", help="Keep the downloaded audio in the output folder."
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show detailed logs.")] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Show the version."
        ),
    ] = None,
) -> None:
    """Transcribe videos from links or local files."""
    setup_logging(verbose)
    items = collect_inputs(inputs, links_file)
    if not items:
        logger.error("No input given. Pass links, files, or use --file links.txt.")
        raise typer.Exit(code=2)

    extract_audio = downloader.ffmpeg_available()
    if not extract_audio and any(downloader.is_url(i) for i in items):
        console.print(FFMPEG_WARNING)

    resolved, compute_type = transcriber.resolve_device(device.value)
    with console.status(
        f"Loading model [bold]{model.value}[/bold] ({resolved}, {compute_type})..."
    ):
        whisper = transcriber.load_model(model.value, device.value)

    formats = expand_formats(fmt)
    lang = normalize_language(language)
    results: list[ItemResult] = []
    for index, item in enumerate(items, start=1):
        console.rule(f"[{index}/{len(items)}] {escape(item)}")
        try:
            result = process_item(
                item,
                whisper,
                output_dir=output_dir,
                formats=formats,
                language=lang,
                keep=keep_audio,
                extract_audio=extract_audio,
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the batch
            logger.error("Failed on %s: %s", item, exc)
            logger.debug("Error details", exc_info=True)
            result = ItemResult(source=item, ok=False, error=str(exc))
        results.append(result)

    print_summary(results)
    if not all(r.ok for r in results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
