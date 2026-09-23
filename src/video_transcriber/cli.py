"""Interface de linha de comando (comando `transcrever`)."""

from __future__ import annotations

import logging
import shutil
import tempfile
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

from video_transcriber import __version__, downloader, formatters, transcriber

logger = logging.getLogger("video_transcriber")
console = Console()

app = typer.Typer(
    add_completion=False,
    help="Baixa o áudio de vídeos (YouTube, TikTok, Instagram...) e gera a transcrição.",
)

FFMPEG_HELP = """[bold red]ffmpeg não encontrado.[/bold red]
O ffmpeg é necessário para extrair o áudio dos vídeos baixados. Instale com:
  • Windows: [cyan]winget install Gyan.FFmpeg[/cyan]  (ou [cyan]choco install ffmpeg[/cyan])
  • macOS:   [cyan]brew install ffmpeg[/cyan]
  • Linux:   [cyan]sudo apt install ffmpeg[/cyan]  (ou o gerenciador da sua distribuição)
Depois, abra um novo terminal e confirme com [cyan]ffmpeg -version[/cyan]."""


class Modelo(str, Enum):
    tiny = "tiny"
    base = "base"
    small = "small"
    medium = "medium"
    large_v3 = "large-v3"


class Formato(str, Enum):
    txt = "txt"
    srt = "srt"
    json = "json"
    todos = "todos"


class Dispositivo(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"


@dataclass
class ItemResult:
    """Resultado do processamento de uma entrada."""

    source: str
    ok: bool
    outputs: list[Path] = field(default_factory=list)
    error: str = ""


def setup_logging(verbose: bool) -> None:
    """Configura o logging com saída formatada pelo rich."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
        force=True,
    )
    logging.captureWarnings(True)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def read_links_file(path: Path) -> list[str]:
    """Lê um arquivo com uma entrada por linha, ignorando linhas vazias e comentários (#)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def collect_inputs(entradas: list[str] | None, arquivo: Path | None) -> list[str]:
    """Junta as entradas da linha de comando e do arquivo, sem duplicatas."""
    items = list(entradas or [])
    if arquivo:
        items.extend(read_links_file(arquivo))
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def expand_formats(formato: Formato) -> list[str]:
    """Converte a opção --formato em uma lista de extensões."""
    return list(formatters.FORMATTERS) if formato is Formato.todos else [formato.value]


def normalize_language(idioma: str | None) -> str | None:
    """Trata "auto" (ou vazio) como detecção automática."""
    if not idioma or idioma.strip().lower() == "auto":
        return None
    return idioma.strip().lower()


def make_progress() -> Progress:
    """Barra de progresso usada para downloads e transcrições."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )


def fetch_audio(item: str, temp_dir: Path, progress: Progress) -> downloader.AudioSource:
    """Obtém o áudio de uma entrada: arquivo local ou download via yt-dlp."""
    path = Path(item).expanduser()
    if path.is_file():
        return downloader.local_source(path)
    if not downloader.is_url(item):
        raise ValueError(f"Não é um link válido nem um arquivo existente: {item}")

    task = progress.add_task("Baixando áudio", total=None)

    def hook(status: dict[str, Any]) -> None:
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            progress.update(task, completed=status.get("downloaded_bytes", 0), total=total)
        elif status.get("status") == "finished":
            progress.update(task, description="Convertendo com ffmpeg")

    try:
        return downloader.download_audio(item, temp_dir, progress_hook=hook)
    finally:
        progress.remove_task(task)


def keep_audio(source: downloader.AudioSource, output_dir: Path, base_name: str) -> Path:
    """Move o áudio temporário para a pasta de saída com um nome legível."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{formatters.sanitize_filename(base_name)}{source.path.suffix}"
    shutil.move(str(source.path), target)
    return target


def process_item(
    item: str,
    model: Any,
    *,
    output_dir: Path,
    formats: list[str],
    language: str | None,
    keep: bool,
) -> ItemResult:
    """Baixa (se necessário), transcreve e grava as saídas de uma entrada."""
    with (
        tempfile.TemporaryDirectory(prefix="video-transcriber-") as tmp,
        make_progress() as progress,
    ):
        source = fetch_audio(item, Path(tmp), progress)
        console.print(f"  [bold]{escape(source.title)}[/bold]")

        task = progress.add_task("Transcrevendo", total=None)
        result = transcriber.transcribe(
            model,
            source.path,
            language=language,
            on_progress=lambda done, total: progress.update(task, completed=done, total=total),
        )
        progress.remove_task(task)
        if not result.segments:
            logger.warning("Nenhuma fala detectada em %s", item)

        metadata = {"titulo": source.title, "origem": source.origin}
        outputs = formatters.write_outputs(result, output_dir, source.title, formats, metadata)
        if keep and source.is_temporary:
            outputs.append(keep_audio(source, output_dir, source.title))
    return ItemResult(source=item, ok=True, outputs=outputs)


def print_summary(results: list[ItemResult]) -> None:
    """Mostra a tabela final com sucessos e falhas."""
    table = Table(title="Resumo", show_lines=True)
    table.add_column("Entrada", overflow="fold")
    table.add_column("Status", justify="center")
    table.add_column("Arquivos / erro", overflow="fold")
    for res in results:
        if res.ok:
            files = "\n".join(str(p) for p in res.outputs)
            table.add_row(escape(res.source), "[green]✓ ok[/green]", escape(files))
        else:
            table.add_row(escape(res.source), "[red]✗ falhou[/red]", escape(res.error))
    console.print(table)

    ok = sum(r.ok for r in results)
    console.print(f"[green]{ok} sucesso(s)[/green] · [red]{len(results) - ok} falha(s)[/red]")


def version_callback(value: bool) -> None:
    if value:
        console.print(f"video-transcriber {__version__}")
        raise typer.Exit()


@app.command()
def main(
    entradas: Annotated[
        list[str] | None,
        typer.Argument(help="Links de vídeo e/ou caminhos de arquivos locais.", show_default=False),
    ] = None,
    arquivo: Annotated[
        Path | None,
        typer.Option(
            "--arquivo",
            "-a",
            help="Arquivo .txt com um link por linha.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    modelo: Annotated[Modelo, typer.Option("--modelo", "-m", help="Modelo do Whisper.")] = (
        Modelo.small
    ),
    idioma: Annotated[
        str | None,
        typer.Option("--idioma", "-i", help='Idioma, ex.: "pt". Padrão: detecção automática.'),
    ] = None,
    formato: Annotated[Formato, typer.Option("--formato", "-f", help="Formato de saída.")] = (
        Formato.txt
    ),
    saida: Annotated[Path, typer.Option("--saida", "-o", help="Pasta de saída.")] = Path(
        "transcricoes"
    ),
    dispositivo: Annotated[
        Dispositivo, typer.Option("--dispositivo", "-d", help="Onde rodar o modelo.")
    ] = Dispositivo.auto,
    manter_audio: Annotated[
        bool, typer.Option("--manter-audio", help="Guarda o áudio baixado na pasta de saída.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra logs detalhados.")
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Mostra a versão."
        ),
    ] = None,
) -> None:
    """Transcreve vídeos a partir de links ou arquivos locais."""
    setup_logging(verbose)
    items = collect_inputs(entradas, arquivo)
    if not items:
        logger.error("Nenhuma entrada informada. Passe links, arquivos ou use --arquivo links.txt.")
        raise typer.Exit(code=2)

    needs_download = any(downloader.is_url(i) for i in items)
    if needs_download and not downloader.ffmpeg_available():
        console.print(FFMPEG_HELP)
        raise typer.Exit(code=1)

    device, compute_type = transcriber.resolve_device(dispositivo.value)
    status = f"Carregando modelo [bold]{modelo.value}[/bold] ({device}, {compute_type})..."
    with console.status(status):
        model = transcriber.load_model(modelo.value, dispositivo.value)

    formats = expand_formats(formato)
    language = normalize_language(idioma)
    results: list[ItemResult] = []
    for index, item in enumerate(items, start=1):
        console.rule(f"[{index}/{len(items)}] {escape(item)}")
        try:
            result = process_item(
                item, model, output_dir=saida, formats=formats, language=language, keep=manter_audio
            )
        except Exception as exc:  # noqa: BLE001 - uma falha não deve parar o lote
            logger.error("Falha em %s: %s", item, exc)
            logger.debug("Detalhes do erro", exc_info=True)
            result = ItemResult(source=item, ok=False, error=str(exc))
        results.append(result)

    print_summary(results)
    if not all(r.ok for r in results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
