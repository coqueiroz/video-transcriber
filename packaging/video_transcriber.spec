# PyInstaller recipe for the desktop app (used by .github/workflows/build-windows.yml).
# Build: pip install ".[app,build]" && pyinstaller packaging/video_transcriber.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - defined by PyInstaller

datas = [(os.path.join(ROOT, "src", "video_transcriber", "web"), "video_transcriber/web")]
binaries = []
hiddenimports = []

# Packages with native libraries or data files (e.g. faster-whisper's VAD model).
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "webview"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "app_entry.py")],  # noqa: F821
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoTranscriber",
    console=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="VideoTranscriber",
    upx=False,
)
