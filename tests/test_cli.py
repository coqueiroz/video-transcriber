"""Testes da CLI com download e modelo mockados."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from video_transcriber import cli, downloader, transcriber

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_model(monkeypatch, fake_model):
    monkeypatch.setattr(transcriber, "load_model", lambda name, device: fake_model)
    monkeypatch.setattr(transcriber, "resolve_device", lambda device: ("cpu", "int8"))
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    return fake_model


@pytest.fixture
def mock_download(monkeypatch):
    """Simula o yt-dlp: links com "falha" levantam erro, os demais criam um áudio falso."""

    def fake_download(url: str, dest_dir: Path, progress_hook=None) -> downloader.AudioSource:
        if "falha" in url:
            raise downloader.DownloadError("vídeo indisponível [privado]")
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / "id.mp3"
        path.write_bytes(b"x")
        if progress_hook:
            progress_hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 1})
            progress_hook({"status": "finished"})
        return downloader.AudioSource(path, f"Título de {url[-1]}", url, is_temporary=True)

    monkeypatch.setattr(downloader, "download_audio", fake_download)


def test_collect_inputs_merges_and_dedupes(tmp_path) -> None:
    links = tmp_path / "links.txt"
    links.write_text(
        "# comentário\nhttps://a/1\n\n  https://a/2  \nhttps://a/1\n", encoding="utf-8"
    )
    assert cli.collect_inputs(["https://a/0", "https://a/2"], links) == [
        "https://a/0",
        "https://a/2",
        "https://a/1",
    ]


def test_expand_formats() -> None:
    assert cli.expand_formats(cli.Formato.todos) == ["txt", "srt", "json"]
    assert cli.expand_formats(cli.Formato.srt) == ["srt"]


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("auto", None), (" PT ", "pt")])
def test_normalize_language(value, expected) -> None:
    assert cli.normalize_language(value) == expected


def test_no_inputs_exits_with_error() -> None:
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2


def test_missing_ffmpeg_shows_help(monkeypatch) -> None:
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    result = runner.invoke(cli.app, ["https://youtu.be/x"])
    assert result.exit_code == 1
    assert "ffmpeg não encontrado" in result.output


def test_local_file_skips_ffmpeg_check_and_download(monkeypatch, tmp_path, mock_model) -> None:
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    audio = tmp_path / "gravação.wav"
    audio.write_bytes(b"x")
    out = tmp_path / "out"

    result = runner.invoke(cli.app, [str(audio), "--saida", str(out), "--formato", "todos"])

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == [
        "gravação.json",
        "gravação.srt",
        "gravação.txt",
    ]
    assert audio.exists()  # arquivo local nunca é apagado
    assert mock_model.calls[0]["path"] == str(audio)


def test_links_file_continues_after_failure(tmp_path, mock_download, mock_model) -> None:
    links = tmp_path / "links.txt"
    links.write_text("https://ok/1\nhttps://falha/2\nhttps://ok/3\n", encoding="utf-8")
    out = tmp_path / "out"

    result = runner.invoke(
        cli.app, ["--arquivo", str(links), "-o", str(out), "--idioma", "pt", "-f", "srt"]
    )

    assert result.exit_code == 1
    assert sorted(p.name for p in out.iterdir()) == ["Título de 1.srt", "Título de 3.srt"]
    assert "2 sucesso(s)" in result.output
    assert "1 falha(s)" in result.output
    assert "[privado]" in result.output
    assert all(call["language"] == "pt" for call in mock_model.calls)


def test_temp_audio_removed_by_default(tmp_path, mock_download) -> None:
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert [p.name for p in out.iterdir()] == ["Título de 1.txt"]


def test_keep_audio(tmp_path, mock_download) -> None:
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(out), "--manter-audio"])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == ["Título de 1.mp3", "Título de 1.txt"]


def test_invalid_input_is_reported(tmp_path) -> None:
    result = runner.invoke(cli.app, ["nao_existe.mp4", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "1 falha(s)" in result.output


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "video-transcriber" in result.output


def test_warns_when_no_speech(tmp_path, mock_download, mock_model) -> None:
    mock_model.texts = []
    result = runner.invoke(cli.app, ["https://ok/1", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "Nenhuma fala detectada" in result.output
