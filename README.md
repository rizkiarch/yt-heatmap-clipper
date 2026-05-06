# yt-heatmap-clipper

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Required-green.svg)](https://ffmpeg.org/)
[![Whisper](https://img.shields.io/badge/AI-Faster--Whisper-orange.svg)](https://github.com/guillaumekln/faster-whisper)

Automatically extract the most engaging segments from YouTube videos using **Most Replayed (heatmap) data** and convert them into vertical-ready clips with AI-powered subtitles.

This tool parses YouTube audience engagement markers to detect high-interest moments and generates short vertical videos suitable for **YouTube Shorts**, **Instagram Reels**, and **TikTok**.

---

## Features

### Core Features
- Extracts YouTube **Most Replayed (heatmap)** segments
- Automatically selects **high-engagement moments**
- Configurable **pre and post padding** for each clip
- Outputs **9:16 vertical video format** (720x1280)
- **No YouTube API key required**
- Supports standard YouTube videos and Shorts
- Smart fallback when heatmap is unavailable (yt-dlp heatmap, chapters, or timeline intervals)

### Crop Modes
- **Default**: Center crop from original video
- **Split Left**: Top = center content, Bottom = bottom-left (facecam)
- **Split Right**: Top = center content, Bottom = bottom-right (facecam)
- **Blur Center**: 16:9 content centered with blurred top/bottom

### AI Auto Subtitle (Faster-Whisper)
- 4-5x faster than standard Whisper
- Auto-detects spoken language (99+ languages)
- Multiple model sizes: tiny, base, small, medium, large-v3
- Automatic transcription and subtitle burning
- 5 subtitle style presets: modern, karaoke, minimal, bold, neon
- Built-in subtitle mask to hide hardcoded source subtitles
- Optional subtitle translation (e.g. en -> id, id -> en) via Argos Translate

### Source Tag Overlay
- Animated sliding source tag showing YouTube channel name
- 4 style presets: classic, glass, minimal, neon
- Configurable position: top-left, top-right, bottom-left, bottom-right
- Adjustable scale and animation interval

### Quality & Overlay Presets
- **Video Quality**: High (1080p), Medium (720p), Fast (720p)
- **Overlay Presets**: Compact, Professional, Bold
  - Each preset bundles subtitle font size, bottom margin, max chars per line, and source tag scale

---

## How It Works

1. **Parse Heatmap Data**: Fetches YouTube watch page and extracts "Most Replayed" markers.
2. **Filter Segments**: Identifies high-engagement moments based on score threshold.
3. **Fallback Strategy**: If heatmap is unavailable, tries yt-dlp heatmap, chapters, or evenly-spaced timeline slices.
4. **User Selection**: Interactive CLI or Web UI for crop mode, quality, subtitle, source tag, and overlay preset.
5. **Smart Download**: Downloads only the required time ranges (with padding) using yt-dlp with multiple client fallbacks.
6. **Video Processing**:
   - Applies selected crop mode.
   - Converts to 720x1280 vertical format.
   - Adds animated source tag overlay (optional).
   - Applies subtitle mask to hide hardcoded subtitles (optional).
7. **AI Transcription** (optional):
   - Transcribes audio using Faster-Whisper.
   - Optionally translates to target language.
   - Generates SRT subtitle file and burns subtitles with selected style.
8. **Export**: Saves optimized MP4 clips ready for social media.

---

## Requirements

- Python **3.8 or higher**
- **FFmpeg** (must be installed and available in PATH)
- **JavaScript runtime** (Deno recommended, or Node.js / Bun / QuickJS)
  - Required since yt-dlp 2025.11.12 for full YouTube support
- Internet connection

### Python Dependencies
- `requests` - HTTP requests
- `yt-dlp` - YouTube video downloader
- `yt-dlp-ejs` - External JS solver for yt-dlp YouTube challenge cipher
- `faster-whisper` - AI transcription (optional, for subtitles)
- `flask` + `flask-socketio` - Web UI (optional, for `app.py`)
- `argostranslate` - Subtitle translation (optional)

### Hardware Requirements
- **Minimum**: 2 GB RAM, 1 GB free disk space
- **Recommended** (with subtitle): 4 GB RAM, 2 GB free disk space
- Internet bandwidth: ~10 MB/s for smooth downloading

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/0xACAB666/yt-heatmap-clipper.git
cd yt-heatmap-clipper
```

### 2. Install JavaScript Runtime (Required)

yt-dlp requires an external JS runtime to solve YouTube cipher challenges.

**Deno (Recommended)**
```bash
# Linux/macOS
curl -fsSL https://deno.land/install.sh | sh

# Windows (PowerShell)
irm https://deno.land/install.ps1 | iex
```

**Node.js (Alternative)**
```bash
# Via package manager or https://nodejs.org/
```

Verify installation:
```bash
deno --version   # or node --version
```

### 3. Install Python Dependencies

**Basic installation** (without subtitle support):
```bash
pip install requests yt-dlp yt-dlp-ejs
```

**Full installation** (with AI subtitle + Web UI):
```bash
pip install requests yt-dlp yt-dlp-ejs faster-whisper flask flask-socketio python-dotenv
```

Or use requirements file if available:
```bash
pip install -r requirements.txt
```

### 4. Install FFmpeg

FFmpeg is the core engine for video processing and **must** be installed.

**Windows**
```bash
1. Download from https://ffmpeg.org/download.html
2. Extract to C:\ffmpeg
3. Add C:\ffmpeg\bin to system PATH
4. Restart terminal
```

**macOS**
```bash
brew install ffmpeg
```

**Linux**
```bash
sudo apt update && sudo apt install ffmpeg
```

### 5. Verify Installation

Run the included setup checker:

```bash
python check_setup.py
```

**Expected Output:**
```text
✅ FFmpeg is installed and recognized.
✅ Library 'requests' is installed.
✅ Library 'yt_dlp' is installed.
✅ Library 'yt-dlp-ejs' is installed.
✅ JavaScript runtime found: deno
✅ Library 'faster_whisper' is installed.
```

---

## Usage

### CLI Usage

```bash
python run.py
```

The script will guide you through an interactive setup:

1. **Select Crop Mode** (1-4):
   - `1` - Default (center crop)
   - `2` - Split 1 (top: center, bottom: bottom-left facecam)
   - `3` - Split 2 (top: center, bottom: bottom-right facecam)
   - `4` - Blur Center (16:9 center with blurred top/bottom)

2. **Select Video Quality**:
   - `high` - 1080p, slow preset, CRF 18
   - `medium` - 720p, medium preset, CRF 23
   - `fast` - 720p, ultrafast preset, CRF 28

3. **Source Tag Overlay** (y/n):
   - Configure animation interval, style (classic/glass/minimal/neon), and position.

4. **Auto Subtitle** (y/n):
   - Select model (tiny/base/small/medium/large-v3).
   - Select subtitle style (modern/karaoke/minimal/bold/neon).
   - Optionally translate subtitle to another language.

5. **Select Overlay Preset** (compact/professional/bold):
   - Bundles subtitle font size, bottom margin, max chars per line, and source tag scale.

6. **Enter YouTube URL**.

7. **Processing**.

### Local Web Usage

Run the browser-based UI:

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

From the web UI you can:
- Input YouTube URL
- Select crop mode, quality, and overlay preset
- Enable/disable auto subtitle and source tag
- Preview frames with live subtitle and source tag overlay
- Submit background jobs and watch real-time progress via WebSocket
- View generated clips and download history

### Example Session

```text
=== Crop Mode ===
1. Default (center crop)
2. Split 1 (top: center, bottom: bottom-left (facecam))
3. Split 2 (top: center, bottom: bottom-right (facecam))
4. Blur Center (16:9 center with blurred top/bottom)

Select crop mode (1-4): 4
Selected: Blur center (16:9 center with blurred top/bottom)

=== Video Quality ===
high. High (1080p)
medium. Medium (720p)
fast. Fast (720p)
Select quality preset (default medium): medium
Selected quality: Medium (720p)

=== Source Tag Overlay ===
Show animated source label (YouTube + channel)? (y/n): y
Animation interval in seconds (default 30): 30

Available source tag styles: classic, glass, minimal, neon
Select source tag style (default classic): classic
Source tag enabled (interval: 30.0s, style: classic)

=== Auto Subtitle ===
Available model: large-v3 (~2.9 GB)
Add auto subtitle using Faster-Whisper? (y/n): y

Available subtitle styles: modern, karaoke, minimal, bold, neon
Select subtitle style (default modern): modern
Translate subtitle? (y/n): n
Subtitle enabled (style: modern, translate: False)

=== Overlay Preset ===
compact. Compact
professional. Professional
bold. Bold
Select overlay preset (default compact): compact
Selected overlay: Compact

YouTube Link: https://www.youtube.com/watch?v=dQw4w9WgXcQ
Reading video metadata...
Source label channel: Rick Astley
Found 6 high-engagement segments.
Processing clips with 10s pre-padding and 10s post-padding.
Clip duration target: min 60s, max 160s
Using crop mode: Blur center (16:9 center with blurred top/bottom)
[Clip 1] Processing segment (230s - 268s, padding 10s)
  Downloading video segment...
  Video cropped successfully
  Adding animated source tag...
  Generating subtitle with AI...
  Subtitle generated (detected: en)
  Burning subtitle to video...
  Raw subtitle saved: clips/clip_1.srt
  Clip successfully generated.
Finished processing. 1 clip(s) successfully saved to 'clips'.
```

Generated clips are saved in the `clips/` directory.

---

## Configuration

You can modify settings at the top of `run.py` or via environment variables in `.env`.

### Basic Settings
```python
OUTPUT_DIR = "clips"      # Output directory for generated clips
MAX_DURATION = 160         # Maximum clip duration (seconds)
MIN_DURATION = 60          # Minimum clip duration (seconds)
MIN_SCORE = 0.30          # Minimum heatmap score threshold (0.0-1.0)
MAX_CLIPS = 1             # Maximum clips per video
PADDING = 10              # Seconds added before and after each segment
```

### Crop Mode Settings
```python
TOP_HEIGHT = 960          # Height for top section in split mode (px)
BOTTOM_HEIGHT = 320       # Height for bottom section (facecam) in split mode (px)
```
> **Note**: `TOP_HEIGHT + BOTTOM_HEIGHT = 1280` (total vertical resolution)

### Subtitle Settings
```python
USE_SUBTITLE = True       # Enable auto subtitle (can be overridden at runtime)
WHISPER_MODEL = "large-v3"   # Whisper model: tiny, base, small, medium, large-v3
SAVE_RAW_SUBTITLE = True  # Save generated .srt alongside output clip
MASK_BUILTIN_SUBTITLE = True  # Mask lower area to hide hardcoded source subtitles
```

### Source Tag Settings
```python
SOURCE_TAG_DEFAULT_INTERVAL = 30.0  # Seconds between each animation cycle
```

### yt-dlp Download Settings
Override via environment variables in `.env`:

```bash
# Override format selector (advanced)
YTDLP_FORMAT=best

# Max height when YTDLP_FORMAT is not set (default 1080)
YTDLP_MAX_HEIGHT=720

# Cookie-based authentication (recommended for age-restricted videos)
YTDLP_COOKIES_FILE=cookies.txt
# OR use browser cookies
YTDLP_COOKIES_FROM_BROWSER=chrome

# PO Token + Visitor Data (YouTube-specific bypass)
YTDLP_PO_TOKEN=your_token_here
YTDLP_VISITOR_DATA=your_visitor_data_here

# Network timeout (seconds) — increase for slow/unstable connections (default 30)
YTDLP_SOCKET_TIMEOUT=60

# Extractor retries — increase if YouTube is flaky (default 3)
YTDLP_EXTRACTOR_RETRIES=5

# Proxy configuration — useful behind corporate firewall/VPN
YTDLP_PROXY=http://proxy:port
```

Notes:
- `YTDLP_FORMAT` takes priority over `YTDLP_MAX_HEIGHT`.
- If you see "Requested format is not available", ensure you have a JS runtime (Deno/Node) installed and `yt-dlp-ejs` is up to date.
- If you get "Read timed out" errors, increase `YTDLP_SOCKET_TIMEOUT` and `YTDLP_EXTRACTOR_RETRIES`.
- Cookies are the strongest authentication method for restricted videos.

### Whisper Model Comparison

| Model | Size | RAM | Speed (60s) | Accuracy | Best For |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **tiny** | 75 MB | ~500 MB | ~5-7s | Good | Quick clips, low-end PC |
| **base** | 142 MB | ~700 MB | ~8-10s | Better | General purpose |
| **small** | 466 MB | ~1.5 GB | ~15-20s | Great | Quality content |
| **medium** | 1.5 GB | ~3 GB | ~40-50s | Excellent | Professional work |
| **large-v3** | 2.9 GB | ~6 GB | ~90-120s | Best | Production quality |

> **Recommendation**: Use `tiny` for speed, `small` for quality balance.

---

## Output

### Video Specifications
- **Format**: MP4 (H.264 video + AAC audio)
- **Resolution**: 720x1280 (9:16 vertical)
- **Video Codec**: libx264, CRF 18-28 (depends on quality preset)
- **Audio Codec**: AAC, 128 kbps
- **Subtitle**: Burned-in (if enabled), style depends on preset

### File Naming
```text
clips/
├── clip_1.mp4
├── clip_1.srt
├── clip_1_id.srt       # translated subtitle (if translation enabled)
├── clip_2.mp4
├── clip_2.srt
└── ...
```

When subtitle is enabled, raw `.srt` files are saved alongside clips.

---

## Troubleshooting

### "Requested format is not available"
This error means yt-dlp cannot find any downloadable format for the video. Common causes:

1. **Missing JS runtime** (most common since 2025.11.12):
   - Install Deno: `curl -fsSL https://deno.land/install.sh | sh`
   - Or install Node.js from https://nodejs.org/
   - Verify with `deno --version` or `node --version`

2. **yt-dlp-ejs outdated**:
   - Run `pip install -U yt-dlp yt-dlp-ejs`
   - Restart the script after updating

3. **Private / age-restricted / region-blocked video**:
   - The script now detects this early and shows a clear message.
   - For age-restricted videos, set cookies via `.env`:
     ```bash
     YTDLP_COOKIES_FILE=cookies.txt
     ```

4. **Live stream**:
   - Live streams are not supported for clipping. The script will report this explicitly.

### FFmpeg not found
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html), add `bin` folder to PATH.
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### No high-engagement segments found
- Video might not have "Most Replayed" data yet (needs views/engagement).
- Try lowering `MIN_SCORE` (e.g., from 0.30 to 0.25).
- Check if video URL is correct.
- The script will automatically fall back to yt-dlp heatmap, chapters, or timeline intervals.

### Subtitle generation fails
- Ensure internet connection for first-time model download.
- Check available RAM (Whisper needs ~500MB-6GB depending on model).
- Try smaller model: change `WHISPER_MODEL` from `large-v3` to `tiny`.

---

## Tips & Best Practices

### For Gaming Content
- Use **Split Right** or **Split Left** mode (facecam in corner).
- Keep `PADDING = 10` for context before/after action.
- Use `small` or `base` model for accurate gaming terminology.

### For Tutorial/Vlog Content
- Use **Default** or **Blur Center** mode.
- Increase `MAX_DURATION = 160` for longer explanations.
- Enable subtitles with `tiny` model for fast processing.

### Subtitle Customization
Edit `SUBTITLE_STYLES` in `run.py` to customize subtitle appearance:

```python
# Current style (white text, black outline):
FontName=Arial,FontSize=14,Bold=1,
PrimaryColour=&HFFFFFF,OutlineColour=&H78000000,
BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=50

# Large text:
FontSize=28,Outline=4

# Position higher (avoid facecam):
MarginV=400

# Different color (yellow):
PrimaryColour=&H00FFFF
```

---

## Contribution

Contributions are welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests
- Improve documentation

---

## License

MIT License

---

## Credits

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - YouTube video downloader
- **[FFmpeg](https://ffmpeg.org/)** - Video processing
- **[Faster-Whisper](https://github.com/guillaumekln/faster-whisper)** - AI transcription
- **[OpenAI Whisper](https://github.com/openai/whisper)** - Speech recognition model
- **[Argos Translate](https://github.com/argosopentech/argos-translate)** - Open-source translation
- **[Flask](https://flask.palletsprojects.com/)** - Web framework
- **[Flask-SocketIO](https://flask-socketio.readthedocs.io/)** - Real-time WebSocket support

---

## Support

If you find this tool useful, please **star this repository!**

For issues and questions, please open an issue on GitHub.

---

# Instal pendukung Virtual Environment

Karena Anda menggunakan Python versi baru (3.12+), pastikan modul venv sudah terinstal di sistem:

```bash
sudo apt update
sudo apt install python3-venv
```

## Buat folder lingkungan virtual

Jalankan perintah ini di dalam folder proyek Anda (`/workspace/yt-heatmap-clipper`):

```bash
python3 -m venv venv
```

Perintah ini akan membuat folder baru bernama `venv` yang berisi salinan Python khusus untuk proyek ini.

## Aktifkan Virtual Environment

Anda harus "masuk" ke dalam lingkungan ini sebelum menginstal apa pun:

```bash
source venv/bin/activate
```

Tanda keberhasilannya adalah muncul tulisan `(venv)` di sebelah kiri kursor terminal Anda.

## Instal requirements sekarang

Sekarang jalankan kembali perintah Anda. Error "externally-managed-environment" tidak akan muncul lagi:

```bash
pip install -r requirements.txt
```

## Catatan Tambahan

- Setiap kali Anda membuka terminal baru untuk mengerjakan proyek ini, jangan lupa jalankan `source venv/bin/activate` lagi.
- Jika ingin keluar dari lingkungan virtual, cukup ketik `deactivate`.
