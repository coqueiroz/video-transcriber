"""Interface gráfica (janela nativa com pywebview) — comando `transcrever-app`."""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from video_transcriber import downloader, formatters, pipeline, transcriber

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
APP_NAME = "Video Transcriber"

# Faixas da barra de progresso (em %) para cada etapa.
MODEL_END = 5.0
DOWNLOAD_END = 40.0
CONVERT_END = 45.0

FFMPEG_MESSAGE = (
    "O ffmpeg não está instalado, e ele é necessário para baixar vídeos. "
    "No Mac, instale pelo Terminal com: brew install ffmpeg"
)


@dataclass
class JobState:
    """Estado da transcrição atual, lido periodicamente pela interface."""

    status: str = "idle"  # idle | running | done | error
    percent: float = 0.0
    stage: str = ""
    title: str = ""
    error: str = ""
    result: dict[str, Any] | None = None


def transcription_payload(job: pipeline.JobResult) -> dict[str, Any]:
    """Dados da transcrição pronta, no formato consumido pelo JavaScript."""
    t = job.transcription
    return {
        "title": job.title,
        "language": t.language,
        "duration": t.duration,
        "text": formatters.to_txt(t).strip(),
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text.strip()}
            for s in t.segments
            if s.text.strip()
        ],
    }


def copy_to_clipboard(text: str) -> bool:
    """Copia texto para a área de transferência usando ferramentas do sistema."""
    commands = {"Darwin": ["pbcopy"], "Windows": ["clip"]}
    command = commands.get(platform.system(), ["xclip", "-selection", "clipboard"])
    try:
        subprocess.run(command, input=text.encode("utf-8"), check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def read_clipboard() -> str:
    """Lê o texto da área de transferência usando ferramentas do sistema."""
    commands = {
        "Darwin": ["pbpaste"],
        "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
    }
    command = commands.get(platform.system(), ["xclip", "-selection", "clipboard", "-o"])
    try:
        result = subprocess.run(command, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


KNOWN_ERRORS = {
    "incompatible architecture": (
        "O app foi aberto no modo Intel (Rosetta). Recrie o app com "
        "./scripts/criar_app_macos.sh e abra de novo."
    ),
    "Unsupported URL": "Esse link não é de um site suportado.",
    "Private video": "Esse vídeo é privado.",
    "Video unavailable": "Esse vídeo não está disponível.",
    "Sign in to confirm": "A plataforma pediu login para liberar esse vídeo.",
    "HTTP Error 404": "Vídeo não encontrado (erro 404). Confira o link.",
    "Unable to download": "Não foi possível baixar o vídeo. Confira o link e a internet.",
}
MAX_ERROR_LENGTH = 220
LOG_HINT = "Detalhes em ~/Library/Logs/VideoTranscriber.log"


def friendly_error(exc: BaseException) -> str:
    """Resume uma exceção em uma mensagem curta para a interface."""
    raw = str(exc).removeprefix("ERROR: ").strip() or type(exc).__name__
    for pattern, message in KNOWN_ERRORS.items():
        if pattern.lower() in raw.lower():
            return message
    first_line = raw.splitlines()[0]
    if len(first_line) > MAX_ERROR_LENGTH:
        first_line = first_line[: MAX_ERROR_LENGTH - 1].rstrip() + "…"
    return f"{first_line} ({LOG_HINT})"


class Api:
    """Métodos expostos ao JavaScript como `window.pywebview.api.*`.

    Atributos privados (com "_") não são expostos pelo pywebview.
    """

    def __init__(self, device: str = "auto") -> None:
        self._device = device
        self._last_job: pipeline.JobResult | None = None
        self._state = JobState()
        self._lock = threading.Lock()
        self._models: dict[str, Any] = {}
        self._window: Any = None

    # --- chamados pelo JavaScript -------------------------------------------------

    def start(self, entrada: str, idioma: str = "auto", modelo: str = "small") -> dict[str, Any]:
        """Inicia uma transcrição em segundo plano."""
        entrada = (entrada or "").strip()
        if not entrada:
            return {"ok": False, "error": "Cole um link ou escolha um arquivo."}
        if modelo not in transcriber.MODELS:
            return {"ok": False, "error": f"Modelo inválido: {modelo}"}
        is_local = Path(entrada).expanduser().is_file()
        if not is_local and not downloader.is_url(entrada):
            return {"ok": False, "error": "Isso não parece um link (deve começar com https://)."}
        if not is_local and not downloader.ffmpeg_available():
            return {"ok": False, "error": FFMPEG_MESSAGE}

        with self._lock:
            if self._state.status == "running":
                return {"ok": False, "error": "Já existe uma transcrição em andamento."}
            self._state = JobState(status="running", stage="Preparando...")

        language = None if idioma in ("", "auto") else idioma
        thread = threading.Thread(target=self._run, args=(entrada, language, modelo), daemon=True)
        thread.start()
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        """Estado atual (consultado pela interface várias vezes por segundo)."""
        with self._lock:
            return asdict(self._state)

    def pick_file(self) -> str | None:
        """Abre o seletor de arquivos e devolve o caminho escolhido."""
        if self._window is None:
            return None
        import webview

        types = ("Vídeo ou áudio (*.mp4;*.mov;*.mkv;*.webm;*.mp3;*.m4a;*.wav;*.ogg;*.flac)",)
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
        return chosen[0] if chosen else None

    def save(self, fmt: str) -> dict[str, Any]:
        """Salva a última transcrição onde o usuário escolher (nada é salvo sozinho)."""
        job = self._last_job
        if job is None:
            return {"ok": False, "error": "Nenhuma transcrição para salvar."}
        if fmt not in formatters.FORMATTERS:
            return {"ok": False, "error": f"Formato inválido: {fmt}"}
        path = self._ask_save_path(f"{formatters.sanitize_filename(job.title)}.{fmt}", fmt)
        if path is None:
            return {"ok": False, "cancelled": True}
        if path.suffix.lower() != f".{fmt}":
            path = path.with_name(f"{path.name}.{fmt}")
        content = formatters.FORMATTERS[fmt](job.transcription, job.metadata)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.exception("Falha ao salvar %s", path)
            return {"ok": False, "error": f"Não foi possível salvar: {exc.strerror or exc}"}
        return {"ok": True, "path": str(path)}

    def copy(self, text: str) -> bool:
        """Copia o texto para a área de transferência."""
        return copy_to_clipboard(text)

    def paste(self) -> str:
        """Devolve o texto da área de transferência (para o botão e o menu "Colar")."""
        return read_clipboard()

    # --- execução em segundo plano -------------------------------------------------

    def _ask_save_path(self, suggested_name: str, fmt: str) -> Path | None:
        """Abre o diálogo "Salvar como" e devolve o caminho escolhido."""
        if self._window is None:
            return None
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=suggested_name,
            file_types=(f"{fmt.upper()} (*.{fmt})",),
        )
        if not chosen:
            return None
        return Path(chosen if isinstance(chosen, str) else chosen[0])

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)

    def _get_model(self, name: str) -> Any:
        if name not in self._models:
            self._models[name] = transcriber.load_model(name, self._device)
        return self._models[name]

    def _download_hook(self, status: dict[str, Any]) -> None:
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            fraction = min(1.0, status.get("downloaded_bytes", 0) / total) if total else 0.0
            percent = MODEL_END + fraction * (DOWNLOAD_END - MODEL_END)
            self._update(stage="Baixando o áudio do vídeo...", percent=percent)
        elif status.get("status") == "finished":
            self._update(stage="Convertendo o áudio...", percent=DOWNLOAD_END)

    def _on_source(self, source: downloader.AudioSource) -> None:
        start = CONVERT_END if source.is_temporary else MODEL_END
        self._update(title=source.title, stage="Transcrevendo...", percent=start)

    def _on_progress(self, done: float, total: float, start: float) -> None:
        fraction = min(1.0, done / total) if total else 1.0
        self._update(percent=start + fraction * (99.0 - start))

    def _run(self, entrada: str, language: str | None, modelo: str) -> None:
        try:
            if modelo not in self._models:
                self._update(stage="Carregando o modelo (na primeira vez ele é baixado)...")
            model = self._get_model(modelo)
            self._update(stage="Obtendo o áudio...", percent=MODEL_END)
            self._last_job = None

            is_local = Path(entrada).expanduser().is_file()
            start = MODEL_END if is_local else CONVERT_END
            job = pipeline.run_job(
                entrada,
                model,
                language=language,
                download_hook=self._download_hook,
                on_source=self._on_source,
                on_progress=lambda done, total: self._on_progress(done, total, start),
            )
        except Exception as exc:  # noqa: BLE001 - qualquer erro vira mensagem na tela
            logger.exception("Falha ao transcrever %s", entrada)
            self._update(status="error", error=friendly_error(exc), stage="")
            return
        self._last_job = job
        self._update(
            status="done", percent=100.0, stage="Pronto!", result=transcription_payload(job)
        )


def _set_macos_app_identity(icon: Path) -> None:
    """No macOS, troca o nome "Python" e o ícone do foguete pelos do app."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = APP_NAME
        if icon.exists():
            image = NSImage.alloc().initWithContentsOfFile_(str(icon))
            NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:  # noqa: BLE001 - puramente cosmético
        logger.debug("Não foi possível ajustar nome/ícone do app", exc_info=True)


def main() -> None:
    """Abre a janela do Video Transcriber."""
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    try:
        import webview
    except ImportError:
        sys.exit('pywebview não instalado. Rode: pip install -e ".[app]"')

    if platform.system() == "Darwin":
        _set_macos_app_identity(WEB_DIR / "icon.png")

    api = Api()
    window = webview.create_window(
        APP_NAME,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=860,
        height=820,
        min_size=(560, 620),
    )
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()
