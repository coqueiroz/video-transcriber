"""Tests for the API behind the desktop app (no window is opened)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from video_transcriber import downloader, gui, transcriber


@pytest.fixture
def api(monkeypatch, fake_model) -> gui.Api:
    monkeypatch.setattr(transcriber, "load_model", lambda name, device: fake_model)
    return gui.Api()


class FakeWindow:
    """Mimics the pywebview window, answering the "Save as" dialog."""

    def __init__(self, answer):
        self.answer = answer
        self.dialogs: list[dict] = []

    def create_file_dialog(self, dialog_type, **kwargs):
        self.dialogs.append(kwargs)
        return self.answer


def wait_until_finished(api: gui.Api, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = api.status()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.01)
    raise AssertionError("The transcription did not finish in time")


def transcribe_local(api: gui.Api, tmp_path: Path, name: str = "interview.wav") -> dict:
    audio = tmp_path / name
    audio.write_bytes(b"x")
    assert api.start(str(audio), language="pt", model="base") == {"ok": True}
    return wait_until_finished(api)


@pytest.mark.parametrize(
    ("source", "message"),
    [("", "Paste a link"), ("some text", "doesn't look like a link")],
)
def test_start_rejects_invalid_input(api: gui.Api, source: str, message: str) -> None:
    result = api.start(source)
    assert result["ok"] is False
    assert message in result["error"]
    assert api.status()["status"] == "idle"


def test_start_rejects_unknown_model(api: gui.Api) -> None:
    assert api.start("https://youtu.be/x", model="huge")["ok"] is False


def test_links_do_not_require_ffmpeg(api: gui.Api, monkeypatch) -> None:
    calls = []

    def fake_download(url, dest_dir, progress_hook=None, extract_audio=True):
        calls.append(extract_audio)
        path = dest_dir / "a.m4a"
        path.write_bytes(b"x")
        return downloader.AudioSource(path, "Clip", url, is_temporary=True)

    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    monkeypatch.setattr(downloader, "download_audio", fake_download)
    assert api.start("https://youtu.be/x")["ok"] is True
    assert wait_until_finished(api)["status"] == "done"
    assert calls == [False]


def test_local_file_end_to_end_saves_nothing(
    api: gui.Api, tmp_path: Path, fake_model, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    state = transcribe_local(api, tmp_path)

    assert state["status"] == "done", state["error"]
    assert state["percent"] == 100.0
    assert state["result"]["title"] == "interview"
    assert state["result"]["text"] == "Hello.\nHow are you?"
    assert state["result"]["segments"][1] == {"start": 1.0, "end": 2.0, "text": "How are you?"}
    assert fake_model.calls[0]["language"] == "pt"
    # Nothing is written to disk automatically.
    assert [p.name for p in tmp_path.iterdir()] == ["interview.wav"]


def test_download_progress_and_errors(api: gui.Api, monkeypatch) -> None:
    def failing_download(url, dest_dir, progress_hook=None, extract_audio=True):
        progress_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        assert 5 < api.status()["percent"] < 40
        raise downloader.DownloadError("Private video")

    monkeypatch.setattr(downloader, "download_audio", failing_download)
    assert api.start("https://youtu.be/x", language="auto")["ok"] is True
    state = wait_until_finished(api)

    assert state["status"] == "error"
    assert state["error"] == "This video is private."
    # After an error, a new transcription can start.
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
        api.start(str(audio), model="small")
        wait_until_finished(api)
    assert loads == ["small"]


def test_web_assets_exist() -> None:
    assert (gui.WEB_DIR / "index.html").is_file()
    assert (gui.WEB_DIR / "icon.png").is_file()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (OSError("dlopen(...): incompatible architecture (have 'arm64')"), "Rosetta"),
        (downloader.DownloadError("[TikTok] 123: Unsupported URL: x"), "not from a supported"),
        (ValueError(""), "ValueError"),
    ],
)
def test_friendly_error(raw: Exception, expected: str) -> None:
    assert expected in gui.friendly_error(raw)


def test_friendly_error_truncates_long_messages() -> None:
    message = gui.friendly_error(RuntimeError("x" * 1000 + "\nsecond line"))
    assert message.startswith("x" * (gui.MAX_ERROR_LENGTH - 1) + "…")
    assert "second line" not in message
    assert str(gui.log_path()) in message


def test_log_path_is_per_platform(monkeypatch) -> None:
    monkeypatch.setattr(gui, "IS_MACOS", False)
    monkeypatch.setattr(gui, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/me/AppData/Local")
    assert gui.log_path() == Path("C:/Users/me/AppData/Local/VideoTranscriber/VideoTranscriber.log")
    monkeypatch.setattr(gui, "IS_MACOS", True)
    monkeypatch.setattr(gui, "IS_WINDOWS", False)
    assert gui.log_path().parts[-3:] == ("Library", "Logs", "VideoTranscriber.log")


def test_paste_reads_clipboard(api: gui.Api, monkeypatch) -> None:
    monkeypatch.setattr(gui, "read_clipboard", lambda: "https://www.tiktok.com/@a/video/1")
    assert api.paste() == "https://www.tiktok.com/@a/video/1"


def test_windows_clipboard_uses_utf16(monkeypatch) -> None:
    sent = {}

    def fake_run(command, data=None):
        sent["command"], sent["data"] = command, data
        return b""

    monkeypatch.setattr(gui, "IS_MACOS", False)
    monkeypatch.setattr(gui, "IS_WINDOWS", True)
    monkeypatch.setattr(gui, "_run_quiet", fake_run)
    assert gui.copy_to_clipboard("ação") is True
    assert sent["command"] == ["clip"]
    assert sent["data"].decode("utf-16") == "ação"


def test_save_requires_a_transcription(api: gui.Api) -> None:
    assert api.save("txt")["ok"] is False


@pytest.mark.parametrize(
    ("fmt", "answer", "expected_name", "start"),
    [
        ("txt", "chosen.txt", "chosen.txt", "Hello."),
        ("srt", "subtitles", "subtitles.srt", "1\n00:00:00,000"),
        ("json", ("data.json",), "data.json", "{"),
    ],
)
def test_save_writes_only_where_chosen(
    api: gui.Api, tmp_path: Path, fmt: str, answer, expected_name: str, start: str
) -> None:
    transcribe_local(api, tmp_path)
    answer = (str(tmp_path / answer[0]),) if isinstance(answer, tuple) else str(tmp_path / answer)
    window = FakeWindow(answer)
    api._window = window

    result = api.save(fmt)

    assert result == {"ok": True, "path": str(tmp_path / expected_name)}
    assert (tmp_path / expected_name).read_text(encoding="utf-8").startswith(start)
    assert window.dialogs[0]["save_filename"] == f"interview.{fmt}"


def test_save_cancelled(api: gui.Api, tmp_path: Path) -> None:
    transcribe_local(api, tmp_path)
    api._window = FakeWindow(None)
    assert api.save("txt") == {"ok": False, "cancelled": True}
    assert [p.name for p in tmp_path.iterdir()] == ["interview.wav"]


def test_save_rejects_unknown_format(api: gui.Api, tmp_path: Path) -> None:
    transcribe_local(api, tmp_path)
    assert api.save("docx")["ok"] is False
