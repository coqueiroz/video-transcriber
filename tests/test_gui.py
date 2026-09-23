"""Testes da API usada pela interface gráfica (sem abrir janela)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from video_transcriber import downloader, gui, transcriber


@pytest.fixture
def api(monkeypatch, tmp_path, fake_model) -> gui.Api:
    monkeypatch.setattr(transcriber, "load_model", lambda name, device: fake_model)
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    return gui.Api(output_dir=tmp_path / "out")


def wait_until_finished(api: gui.Api, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = api.status()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.01)
    raise AssertionError("A transcrição não terminou a tempo")


@pytest.mark.parametrize(
    ("entrada", "message"),
    [("", "Cole um link"), ("texto qualquer", "não parece um link")],
)
def test_start_rejects_invalid_input(api: gui.Api, entrada: str, message: str) -> None:
    result = api.start(entrada)
    assert result["ok"] is False
    assert message in result["error"]
    assert api.status()["status"] == "idle"


def test_start_rejects_unknown_model(api: gui.Api) -> None:
    assert api.start("https://youtu.be/x", modelo="gigante")["ok"] is False


def test_start_requires_ffmpeg_for_links(api: gui.Api, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    result = api.start("https://youtu.be/x")
    assert result["ok"] is False
    assert "ffmpeg" in result["error"]


def test_local_file_end_to_end(api: gui.Api, tmp_path: Path, fake_model) -> None:
    audio = tmp_path / "entrevista.wav"
    audio.write_bytes(b"x")

    assert api.start(str(audio), idioma="pt", modelo="base") == {"ok": True}
    state = wait_until_finished(api)

    assert state["status"] == "done", state["error"]
    assert state["percent"] == 100.0
    assert state["result"]["title"] == "entrevista"
    assert state["result"]["text"] == "Olá.\nTudo bem?"
    assert state["result"]["segments"][1] == {"start": 1.0, "end": 2.0, "text": "Tudo bem?"}
    assert sorted(Path(p).name for p in state["outputs"]) == [
        "entrevista.json",
        "entrevista.srt",
        "entrevista.txt",
    ]
    assert fake_model.calls[0]["language"] == "pt"


def test_download_progress_and_errors(api: gui.Api, monkeypatch) -> None:
    def failing_download(url, dest_dir, progress_hook=None):
        progress_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        assert 5 < api.status()["percent"] < 40
        raise downloader.DownloadError("Private video")

    monkeypatch.setattr(downloader, "download_audio", failing_download)
    assert api.start("https://youtu.be/x", idioma="auto")["ok"] is True
    state = wait_until_finished(api)

    assert state["status"] == "error"
    assert state["error"] == "Esse vídeo é privado."
    # Depois de um erro, é possível começar de novo.
    assert api.start("https://youtu.be/y")["ok"] is True
    wait_until_finished(api)


def test_model_is_cached(api: gui.Api, monkeypatch, tmp_path: Path, fake_model) -> None:
    loads: list[str] = []

    def counting_load(name, device):
        loads.append(name)
        return fake_model

    monkeypatch.setattr(transcriber, "load_model", counting_load)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    for _ in range(2):
        api.start(str(audio), modelo="small")
        wait_until_finished(api)
    assert loads == ["small"]


def test_web_assets_exist() -> None:
    assert (gui.WEB_DIR / "index.html").is_file()
    assert (gui.WEB_DIR / "icon.png").is_file()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (OSError("dlopen(...): incompatible architecture (have 'arm64')"), "modo Intel"),
        (downloader.DownloadError("[TikTok] 123: Unsupported URL: x"), "não é de um site"),
        (ValueError(""), "ValueError"),
    ],
)
def test_friendly_error(raw: Exception, expected: str) -> None:
    assert expected in gui.friendly_error(raw)


def test_friendly_error_truncates_long_messages() -> None:
    message = gui.friendly_error(RuntimeError("x" * 1000 + "\nsegunda linha"))
    assert len(message) < gui.MAX_ERROR_LENGTH + len(gui.LOG_HINT) + 5
    assert "segunda linha" not in message
    assert gui.LOG_HINT in message


def test_paste_reads_clipboard(api: gui.Api, monkeypatch) -> None:
    monkeypatch.setattr(gui, "read_clipboard", lambda: "https://www.tiktok.com/@a/video/1")
    assert api.paste() == "https://www.tiktok.com/@a/video/1"
