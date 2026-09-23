# video-transcriber

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green.svg)](LICENSE)
[![Testes](https://github.com/coqueiroz/video-transcriber/actions/workflows/tests.yml/badge.svg)](https://github.com/coqueiroz/video-transcriber/actions/workflows/tests.yml)

Ferramenta de linha de comando que baixa o áudio de vídeos do YouTube, TikTok, Instagram e [outros sites suportados pelo yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) e gera a transcrição localmente com [faster-whisper](https://github.com/SYSTRAN/faster-whisper), em `.txt`, `.srt` ou `.json`.

<!-- Substitua pelo GIF de demonstração -->
<p align="center">
  <img src="docs/demo.gif" alt="Demonstração do comando transcrever" width="720">
</p>

## Funcionalidades

- Um ou vários links de uma vez, ou um arquivo `.txt` com um link por linha
- Arquivos de vídeo/áudio locais também são aceitos (sem download)
- Saída em texto puro, legenda `.srt` ou `.json` com tempos de cada trecho
- Nomes de arquivo seguros gerados a partir do título do vídeo
- Progresso no terminal e resumo final com sucessos e falhas; um link com erro não interrompe os demais
- Tudo roda na sua máquina: nenhum áudio é enviado para serviços externos

## Requisitos

- **Python 3.10+**
- **ffmpeg** (usado para extrair o áudio dos vídeos baixados)

| Sistema | Instalação do ffmpeg |
|---|---|
| Windows | `winget install Gyan.FFmpeg` (ou `choco install ffmpeg`) |
| macOS | `brew install ffmpeg` |
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` |
| Linux (Fedora) | `sudo dnf install ffmpeg` |

Confirme com `ffmpeg -version`. No Windows, abra um novo terminal depois de instalar.

> Para transcrever apenas arquivos locais o ffmpeg não é obrigatório: o faster-whisper decodifica o áudio sozinho.

## Instalação

```bash
git clone https://github.com/coqueiroz/video-transcriber.git
cd video-transcriber

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e .
```

Pronto: o comando `transcrever` fica disponível enquanto o ambiente virtual estiver ativo.

> Na primeira execução o modelo do Whisper é baixado automaticamente (de ~75 MB a ~3 GB, conforme o modelo) e fica em cache.

## Uso

```bash
# Um link
transcrever "https://www.youtube.com/watch?v=VIDEO_ID"

# Vários links
transcrever "https://www.tiktok.com/@usuario/video/123" "https://www.instagram.com/reel/abc/"

# Arquivo .txt com um link por linha (linhas vazias e iniciadas por # são ignoradas)
transcrever --arquivo links.txt

# Arquivo local (vídeo ou áudio)
transcrever ~/Videos/aula.mp4

# Legenda .srt em português com um modelo mais preciso
transcrever "https://youtu.be/VIDEO_ID" --idioma pt --formato srt --modelo medium

# Todos os formatos, em outra pasta, guardando o áudio baixado
transcrever --arquivo links.txt --formato todos --saida minhas_transcricoes --manter-audio
```

### Opções

| Opção | Padrão | Descrição |
|---|---|---|
| `--arquivo`, `-a` | — | Arquivo `.txt` com um link por linha |
| `--modelo`, `-m` | `small` | `tiny`, `base`, `small`, `medium` ou `large-v3` |
| `--idioma`, `-i` | automático | Código do idioma, ex.: `pt`, `en`, `es` |
| `--formato`, `-f` | `txt` | `txt`, `srt`, `json` ou `todos` |
| `--saida`, `-o` | `./transcricoes` | Pasta onde os arquivos são salvos |
| `--dispositivo`, `-d` | `auto` | `cpu`, `cuda` ou `auto` (usa GPU NVIDIA se houver) |
| `--manter-audio` | desligado | Mantém o áudio baixado na pasta de saída |
| `--verbose`, `-v` | desligado | Logs detalhados (útil para investigar erros) |

O comando termina com código `1` se alguma entrada falhar, o que facilita o uso em scripts.

## Qual modelo escolher?

| Modelo | Tamanho | Velocidade | Precisão | Indicado para |
|---|---|---|---|---|
| `tiny` | ~75 MB | ⚡⚡⚡⚡⚡ | ★☆☆☆☆ | Testes rápidos, áudio muito limpo |
| `base` | ~145 MB | ⚡⚡⚡⚡ | ★★☆☆☆ | Rascunhos rápidos |
| `small` | ~485 MB | ⚡⚡⚡ | ★★★☆☆ | **Padrão**: bom equilíbrio em CPU |
| `medium` | ~1,5 GB | ⚡⚡ | ★★★★☆ | Áudio com ruído, sotaques, termos técnicos |
| `large-v3` | ~3 GB | ⚡ | ★★★★★ | Máxima qualidade (ideal com GPU) |

Em CPU o modelo roda em `int8`; com GPU NVIDIA (`cuda`), em `float16`. Informar `--idioma` evita erros de detecção em vídeos curtos.

## Desenvolvimento

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

Estrutura:

```
src/video_transcriber/
├── cli.py          # interface (typer + rich)
├── downloader.py   # download do áudio com yt-dlp
├── transcriber.py  # transcrição com faster-whisper
└── formatters.py   # geração de txt/srt/json e nomes de arquivo seguros
```

## Aviso legal

Esta ferramenta foi criada para **uso pessoal e educacional** (estudo, acessibilidade, anotações).

- Respeite os **termos de uso** de cada plataforma (YouTube, TikTok, Instagram etc.).
- Respeite os **direitos autorais** dos criadores de conteúdo.
- **Não redistribua** transcrições, legendas ou áudios de conteúdo de terceiros sem autorização.

Os autores não se responsabilizam pelo uso indevido do software.

## Licença

[MIT](LICENSE)

---

## English

**video-transcriber** is a command-line tool that downloads the audio from videos (YouTube, TikTok, Instagram and any site supported by yt-dlp) and transcribes it locally with faster-whisper, producing `.txt`, `.srt` or `.json` files.

```bash
pip install -e .
transcrever "https://youtu.be/VIDEO_ID" --idioma en --formato srt
transcrever --arquivo links.txt --formato todos
```

Requires Python 3.10+ and ffmpeg. Intended for personal and educational use only: respect each platform's terms of service and creators' copyrights, and do not redistribute third-party content.
