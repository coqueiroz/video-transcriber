#!/usr/bin/env bash
# Cria "Video Transcriber.app" (padrão: ~/Applications) que abre a interface gráfica.
# O app usa o ambiente virtual deste projeto, então mantenha a pasta do projeto no lugar.
# Uso: ./scripts/criar_app_macos.sh [pasta_de_destino]
set -euo pipefail

APP_NAME="Video Transcriber"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-$HOME/Applications}"
APP="$DEST_DIR/$APP_NAME.app"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Este script é só para macOS." >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Ambiente virtual não encontrado em $PROJECT_DIR/.venv" >&2
  echo "Crie com: python3 -m venv .venv && .venv/bin/pip install -e \".[app]\"" >&2
  exit 1
fi
if ! "$PYTHON" -c "import webview" 2>/dev/null; then
  echo "Instalando a interface gráfica (pywebview)..."
  "$PYTHON" -m pip install -q -e "$PROJECT_DIR[app]"
fi

echo "Criando $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Ícone (.icns) a partir do PNG
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$PROJECT_DIR/assets/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$PROJECT_DIR/assets/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>io.github.coqueiroz.video-transcriber</string>
  <key>CFBundleVersion</key><string>0.2.0</string>
  <key>CFBundleShortVersionString</key><string>0.2.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSArchitecturePriority</key>
  <array><string>arm64</string><string>x86_64</string></array>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Apps abertos pelo Finder não herdam o PATH do terminal: incluímos o Homebrew (ffmpeg).
# Um executável em shell script pode ser aberto pelo macOS via Rosetta (Intel) em Macs
# Apple Silicon; forçamos arm64 para que as bibliotecas nativas (av, ctranslate2) carreguem.
cat > "$APP/Contents/MacOS/launcher" <<LAUNCHER
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
LOG="\$HOME/Library/Logs/VideoTranscriber.log"
if [[ "\$(sysctl -n hw.optional.arm64 2>/dev/null)" == "1" ]]; then
  exec /usr/bin/arch -arm64 "$PYTHON" -m video_transcriber.gui >>"\$LOG" 2>&1
fi
exec "$PYTHON" -m video_transcriber.gui >>"\$LOG" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/launcher"

touch "$APP"
echo "Pronto! Abra \"$APP_NAME\" pelo Launchpad, Spotlight (⌘ + espaço) ou em $DEST_DIR."
echo "Dica: com o app aberto, clique com o botão direito no ícone do Dock > Opções > Manter no Dock."
