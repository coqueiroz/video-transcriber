"""Desktop app (native window via pywebview) — `video-transcriber-app` command."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import tempfile
import threading
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from video_transcriber import __version__, downloader, formatters, pipeline, transcriber
from video_transcriber.timecodes import TimecodeError, TimeRange, format_timecode, start_from_url

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
APP_NAME = "Video Transcriber"
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

# Progress bar ranges (in %) for each stage.
MODEL_END = 5.0
DOWNLOAD_END = 40.0

KNOWN_ERRORS = {
    "incompatible architecture": (
        "The app was opened in Intel (Rosetta) mode. Rebuild it with "
        "./scripts/create_macos_app.sh and open it again."
    ),
    "Unsupported URL": "This link is not from a supported site.",
    "Private video": "This video is private.",
    "Video unavailable": "This video is not available.",
    "Sign in to confirm": "The platform asked for a login to allow this video.",
    "HTTP Error 404": "Video not found (error 404). Check the link.",
    "Unable to download": "Could not download the video. Check the link and your connection.",
}
MAX_ERROR_LENGTH = 220


def log_path() -> Path:
    """Where the app writes its log file on each operating system."""
    if IS_MACOS:
        return Path.home() / "Library" / "Logs" / "VideoTranscriber.log"
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "VideoTranscriber" / "VideoTranscriber.log"
    return Path.home() / ".local" / "state" / "video-transcriber" / "VideoTranscriber.log"


@dataclass
class JobState:
    """State of the current transcription, polled by the UI."""

    status: str = "idle"  # idle | running | done | error
    percent: float = 0.0
    stage: str = ""
    title: str = ""
    error: str = ""
    result: dict[str, Any] | None = None


def transcription_payload(job: pipeline.JobResult) -> dict[str, Any]:
    """Finished transcription in the shape consumed by the JavaScript side."""
    t = job.transcription
    return {
        "title": job.title,
        "language": t.language,
        "duration": t.duration,
        "range": None if job.time_range.is_full else job.time_range.label(),
        "text": formatters.to_txt(t).strip(),
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text.strip()}
            for s in t.segments
            if s.text.strip()
        ],
    }


def _run_quiet(command: list[str], data: bytes | None = None) -> bytes:
    """Run a helper command without flashing a console window on Windows."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
    result = subprocess.run(
        command, input=data, capture_output=True, check=True, creationflags=flags
    )
    return result.stdout


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the clipboard using system tools."""
    if IS_MACOS:
        command, data = ["pbcopy"], text.encode("utf-8")
    elif IS_WINDOWS:
        command, data = ["clip"], text.encode("utf-16")  # clip.exe expects UTF-16 with BOM
    else:
        command, data = ["xclip", "-selection", "clipboard"], text.encode("utf-8")
    try:
        _run_quiet(command, data)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def read_clipboard() -> str:
    """Read text from the clipboard using system tools."""
    if IS_MACOS:
        command = ["pbpaste"]
    elif IS_WINDOWS:
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"
        command = ["powershell", "-NoProfile", "-Command", script]
    else:
        command = ["xclip", "-selection", "clipboard", "-o"]
    try:
        return _run_quiet(command).decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def friendly_error(exc: BaseException) -> str:
    """Summarize an exception as a short message for the UI."""
    if isinstance(exc, (TimecodeError, transcriber.EmptyRangeError)):
        return str(exc)  # already written for people
    raw = str(exc).removeprefix("ERROR: ").strip() or type(exc).__name__
    for pattern, message in KNOWN_ERRORS.items():
        if pattern.lower() in raw.lower():
            return message
    first_line = raw.splitlines()[0]
    if len(first_line) > MAX_ERROR_LENGTH:
        first_line = first_line[: MAX_ERROR_LENGTH - 1].rstrip() + "…"
    return f"{first_line} (details in {log_path()})"


class Api:
    """Methods exposed to JavaScript as `window.pywebview.api.*`.

    Private attributes (starting with "_") are not exposed by pywebview.
    """

    def __init__(self, device: str = "auto") -> None:
        self._device = device
        self._last_job: pipeline.JobResult | None = None
        self._state = JobState()
        self._lock = threading.Lock()
        self._models: dict[str, Any] = {}
        self._durations: dict[str, float | None] = {}
        self._window: Any = None

    # --- called from JavaScript ----------------------------------------------------

    def probe(self, source: str) -> dict[str, Any]:
        """Look up a link's (or file's) title and duration before transcribing it."""
        source = (source or "").strip()
        if not source:
            return {"ok": False}
        is_local = Path(source).expanduser().is_file()
        if not is_local and not downloader.is_url(source):
            return {"ok": False}
        try:
            info = downloader.probe(source)
        except Exception as exc:  # noqa: BLE001 - the transcription itself will report it
            logger.info("Could not probe %s: %s", source, exc)
            return {"ok": False, "error": friendly_error(exc)}
        self._durations[source] = info.duration
        return {
            "ok": True,
            "title": info.title,
            "duration": info.duration,
            "duration_label": format_timecode(info.duration) if info.duration else None,
            "start_hint": None if is_local else start_from_url(source),
        }

    def start(
        self,
        source: str,
        language: str = "auto",
        model: str = "small",
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """Start a transcription in the background (optionally only from `start` to `end`)."""
        source = (source or "").strip()
        if not source:
            return {"ok": False, "error": "Paste a link or choose a file."}
        if model not in transcriber.MODELS:
            return {"ok": False, "error": f"Invalid model: {model}"}
        is_local = Path(source).expanduser().is_file()
        if not is_local and not downloader.is_url(source):
            return {
                "ok": False,
                "error": "That doesn't look like a link (it should start with https://).",
            }
        time_range = TimeRange(start=float(start or 0), end=None if end is None else float(end))
        try:
            time_range.validate(self._durations.get(source))
        except TimecodeError as exc:
            return {"ok": False, "error": str(exc)}

        with self._lock:
            if self._state.status == "running":
                return {"ok": False, "error": "A transcription is already running."}
            self._state = JobState(status="running", stage="Preparing...")

        lang = None if language in ("", "auto") else language
        thread = threading.Thread(
            target=self._run, args=(source, lang, model, time_range), daemon=True
        )
        thread.start()
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        """Current state (polled by the UI several times per second)."""
        with self._lock:
            return asdict(self._state)

    def pick_file(self) -> str | None:
        """Open the file picker and return the chosen path."""
        if self._window is None:
            return None
        import webview

        types = ("Video or audio (*.mp4;*.mov;*.mkv;*.webm;*.mp3;*.m4a;*.wav;*.ogg;*.flac)",)
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
        return chosen[0] if chosen else None

    def save(self, fmt: str) -> dict[str, Any]:
        """Save the last transcription wherever the user chooses (nothing is saved on its own)."""
        job = self._last_job
        if job is None:
            return {"ok": False, "error": "There is no transcription to save."}
        if fmt not in formatters.FORMATTERS:
            return {"ok": False, "error": f"Invalid format: {fmt}"}
        path = self._ask_save_path(f"{formatters.sanitize_filename(job.output_name)}.{fmt}", fmt)
        if path is None:
            return {"ok": False, "cancelled": True}
        if path.suffix.lower() != f".{fmt}":
            path = path.with_name(f"{path.name}.{fmt}")
        content = formatters.FORMATTERS[fmt](job.transcription, job.metadata)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to save %s", path)
            return {"ok": False, "error": f"Could not save: {exc.strerror or exc}"}
        return {"ok": True, "path": str(path)}

    def copy(self, text: str) -> bool:
        """Copy text to the clipboard."""
        return copy_to_clipboard(text)

    def paste(self) -> str:
        """Return the clipboard text (for the "Paste" button and menu)."""
        return read_clipboard()

    # --- background work ----------------------------------------------------------

    def _ask_save_path(self, suggested_name: str, fmt: str) -> Path | None:
        """Open the "Save as" dialog and return the chosen path."""
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
            self._update(stage="Downloading the audio...", percent=percent)
        elif status.get("status") == "finished":
            self._update(stage="Processing the audio...", percent=DOWNLOAD_END)

    def _on_source(self, source: downloader.AudioSource) -> None:
        start = DOWNLOAD_END if source.is_temporary else MODEL_END
        self._update(title=source.title, stage="Transcribing...", percent=start)

    def _on_progress(self, done: float, total: float, start: float) -> None:
        fraction = min(1.0, done / total) if total else 1.0
        self._update(percent=start + fraction * (99.0 - start))

    def _run(
        self,
        source: str,
        language: str | None,
        model_name: str,
        time_range: TimeRange | None = None,
    ) -> None:
        try:
            if model_name not in self._models:
                self._update(stage="Loading the model (downloaded the first time)...")
            model = self._get_model(model_name)
            self._update(stage="Getting the audio...", percent=MODEL_END)
            self._last_job = None

            is_local = Path(source).expanduser().is_file()
            start = MODEL_END if is_local else DOWNLOAD_END
            job = pipeline.run_job(
                source,
                model,
                language=language,
                # faster-whisper decodes m4a/webm/mp4 by itself: no ffmpeg needed.
                extract_audio=False,
                time_range=time_range,
                download_hook=self._download_hook,
                on_source=self._on_source,
                on_progress=lambda done, total: self._on_progress(done, total, start),
            )
        except Exception as exc:  # noqa: BLE001 - any error becomes a message on screen
            logger.exception("Failed to transcribe %s", source)
            self._update(status="error", error=friendly_error(exc), stage="")
            return
        self._last_job = job
        self._update(status="done", percent=100.0, stage="Done!", result=transcription_payload(job))


def _set_macos_app_identity(icon: Path) -> None:
    """On macOS, replace the "Python" name and rocket icon with the app's own."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = APP_NAME
        if icon.exists():
            image = NSImage.alloc().initWithContentsOfFile_(str(icon))
            NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:  # noqa: BLE001 - purely cosmetic
        logger.debug("Could not set the app name/icon", exc_info=True)


def setup_logging() -> None:
    """Log to a file; in windowed builds (no console) also route stdout/stderr there."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )
    logging.captureWarnings(True)


def self_test() -> int:
    """Check that every native dependency loads and a real transcription runs.

    Used by CI to validate the packaged Windows build: `VideoTranscriber.exe --self-test`.
    """
    import av  # noqa: F401
    import ctranslate2  # noqa: F401
    import webview  # noqa: F401
    import yt_dlp  # noqa: F401

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "silence.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)
        model = transcriber.load_model("tiny", "cpu")
        result = transcriber.transcribe(model, audio)
    print(f"self-test ok: {APP_NAME} {__version__}, audio {result.duration:.1f}s")
    return 0


def main() -> None:
    """Open the Video Transcriber window."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    setup_logging()
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        import webview
    except ImportError:
        sys.exit('pywebview is not installed. Run: pip install -e ".[app]"')

    if IS_MACOS:
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
