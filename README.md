# Video Transcriber

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/coqueiroz/video-transcriber/actions/workflows/tests.yml/badge.svg)](https://github.com/coqueiroz/video-transcriber/actions/workflows/tests.yml)
[![Windows build](https://github.com/coqueiroz/video-transcriber/actions/workflows/build-windows.yml/badge.svg)](https://github.com/coqueiroz/video-transcriber/actions/workflows/build-windows.yml)
[![Latest release](https://img.shields.io/github/v/release/coqueiroz/video-transcriber)](https://github.com/coqueiroz/video-transcriber/releases/latest)

Paste a YouTube, TikTok or Instagram link (or [any site supported by yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)) and get the transcript — locally, with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Comes as a **desktop app** for Windows and macOS and as a **command-line tool**.

<!-- Demo GIF placeholder: record the app, save it as docs/demo.gif and uncomment:
<p align="center">
  <img src="docs/demo.gif" alt="Video Transcriber demo" width="720">
</p>
-->

## Features

- **Desktop app**: paste a link, watch the progress bar, read the transcript right in the window
- Plain text or **with timestamps**; copy it with one click or save it as `.txt`, `.srt` or `.json`
- Works with links **and** local video/audio files
- Automatic language detection (or pick one), several quality levels
- **Private by design**: everything runs on your computer, and the app saves nothing unless you ask
- **CLI** for batches: many links at once or a `.txt` file with one link per line; a failing link doesn't stop the others

## Download (Windows)

1. Go to the **[latest release](https://github.com/coqueiroz/video-transcriber/releases/latest)**.
2. Download **`VideoTranscriber-Setup-x.y.z.exe`** and run it. No admin rights are needed, and nothing else has to be installed.
   Prefer not to install? Use the **`…-windows-portable.zip`**: unzip it and run `VideoTranscriber.exe`.
3. Open **Video Transcriber** from the Start menu.

> The executable isn't code-signed, so Windows SmartScreen may show *"Windows protected your PC"*. Click **More info → Run anyway**.

## macOS (and running from source)

Requires **Python 3.10+**.

```bash
git clone https://github.com/coqueiroz/video-transcriber.git
cd video-transcriber
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[app]"
video-transcriber-app              # opens the desktop app
```

**On macOS, install it as a real app** (Launchpad, Spotlight and Dock icon):

```bash
./scripts/create_macos_app.sh
```

This creates `~/Applications/Video Transcriber.app`. The app uses the project's virtual environment, so keep the project folder where it is (if you move it, recreate `.venv` and run the script again). Logs go to `~/Library/Logs/VideoTranscriber.log`.

> The first time you use each quality level, its Whisper model is downloaded (≈145 MB to ≈3 GB) and cached for later.

## Using the app

1. Copy a video link and click **Paste** (or right-click the field → *Paste*, or Ctrl/⌘+V).
2. Choose the **Language** (or leave *Auto-detect*) and the **Quality**.
3. Click **Transcribe** and follow the percentage.
4. When it reaches 100%, the transcript appears below. Switch between **Text** and **With timestamps**, **Copy text**, or **Save…** it as `.txt`, `.srt` (subtitles) or `.json`.

You can also click *or choose a file from your computer* to transcribe a local video or audio file.

## Command line

The CLI writes the results to files (default folder: `./transcriptions`).

```bash
# One link
video-transcriber "https://www.youtube.com/watch?v=VIDEO_ID"

# Several links
video-transcriber "https://www.tiktok.com/@user/video/123" "https://www.instagram.com/reel/abc/"

# A .txt file with one link per line (blank lines and lines starting with # are ignored)
video-transcriber --file links.txt

# A local file (video or audio)
video-transcriber ~/Videos/lecture.mp4

# Portuguese .srt subtitles with a more accurate model
video-transcriber "https://youtu.be/VIDEO_ID" --language pt --format srt --model medium

# Every format, another folder, keeping the downloaded audio
video-transcriber --file links.txt --format all --output my_transcripts --keep-audio
```

| Option | Default | Description |
|---|---|---|
| `--file`, `-a` | — | Text file with one link per line |
| `--model`, `-m` | `small` | `tiny`, `base`, `small`, `medium` or `large-v3` |
| `--language`, `-l` | auto-detect | Language code, e.g. `en`, `pt`, `es` |
| `--format`, `-f` | `txt` | `txt`, `srt`, `json` or `all` |
| `--output`, `-o` | `./transcriptions` | Folder where files are written |
| `--device`, `-d` | `auto` | `cpu`, `cuda` or `auto` (uses an NVIDIA GPU if available) |
| `--keep-audio` | off | Keep the downloaded audio in the output folder |
| `--verbose`, `-v` | off | Detailed logs (useful when something fails) |

The command exits with code `1` if any input fails, which makes it script-friendly. The original Portuguese names (`transcrever`, `--arquivo`, `--idioma`, `--formato`, `--saida`, `--manter-audio`…) still work as aliases.

**ffmpeg is optional.** Without it, downloads keep their original audio format (m4a/webm/mp4), which transcribes just fine. Install it if you want downloads converted to mp3 (handy with `--keep-audio`): `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux).

## Which model should I pick?

| Model | App label | Size | Speed | Accuracy | Good for |
|---|---|---|---|---|---|
| `tiny` | — | ~75 MB | ⚡⚡⚡⚡⚡ | ★☆☆☆☆ | Quick tests, very clean audio |
| `base` | Fast | ~145 MB | ⚡⚡⚡⚡ | ★★☆☆☆ | Fast drafts |
| `small` | Balanced | ~485 MB | ⚡⚡⚡ | ★★★☆☆ | **Default** — good balance on a CPU |
| `medium` | High | ~1.5 GB | ⚡⚡ | ★★★★☆ | Noisy audio, accents, technical terms |
| `large-v3` | Best | ~3 GB | ⚡ | ★★★★★ | Maximum quality (ideally with a GPU) |

On a CPU the model runs in `int8`; on an NVIDIA GPU (`cuda`) in `float16`. Setting the language avoids detection mistakes on short videos.

## Development

```bash
pip install -e ".[dev,app]"
ruff check .
pytest
```

**The Windows app is built on GitHub Actions** ([`build-windows.yml`](.github/workflows/build-windows.yml)): pushing a tag like `v0.3.0` builds the executable with PyInstaller, creates the installer with Inno Setup, installs it and runs a real transcription as a self-test, then attaches both files to the GitHub release. It can also be started manually from the *Actions* tab. To build locally on Windows:

```bash
pip install ".[app,build]"
pyinstaller packaging/video_transcriber.spec --noconfirm
iscc /DAppVersion=0.3.0 packaging\installer.iss
```

Project layout:

```
src/video_transcriber/
├── cli.py          # command-line interface (typer + rich)
├── gui.py          # desktop app backend (pywebview)
├── web/            # the app's HTML/CSS/JS
├── pipeline.py     # shared flow: get audio → transcribe → (optionally) save
├── downloader.py   # audio download with yt-dlp
├── transcriber.py  # speech-to-text with faster-whisper
└── formatters.py   # txt/srt/json output and safe filenames
packaging/          # PyInstaller recipe and Inno Setup installer script
scripts/            # macOS .app builder
```

## Legal notice

This tool is meant for **personal and educational use** (studying, accessibility, note-taking).

- Respect the **terms of service** of each platform (YouTube, TikTok, Instagram, etc.).
- Respect the **copyright** of content creators.
- **Do not redistribute** transcripts, subtitles or audio of third-party content without permission.

The authors are not responsible for misuse of this software.

## License

[MIT](LICENSE)
