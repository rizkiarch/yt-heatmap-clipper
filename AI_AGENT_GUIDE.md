# AI Agent Guidelines & Project Architecture

This document serves as the authoritative source of truth for any AI Agent working on the `yt-heatmap-clipper` project. 
**CRITICAL RULE:** Read this document carefully before making ANY architectural or structural changes. Do not hallucinate file paths or typical framework structures (like MVC, `src/`, or `controllers/`). Stick strictly to the structure defined below.

## 1. Project Overview

`yt-heatmap-clipper` is a Python-based utility (both CLI and Web UI) that automatically extracts high-engagement segments from YouTube videos using heatmap ("Most Replayed") data. It processes video using FFmpeg and optionally generates AI subtitles using Faster-Whisper. 
The application relies heavily on system-level commands via `subprocess` (calling `ffmpeg` and `yt-dlp`).

## 2. Strict Folder & File Structure

This project has a flat and simple structure. **DO NOT** assume the existence of subdirectories other than what is listed here.

```text
yt-heatmap-clipper/
│
├── .env                  # Environment variables (RABBITMQ configuration, ASYNC_ENABLED)
├── .env.example          # Example environment variables
├── requirements.txt      # Python dependencies
├── check_setup.py        # Script to verify Python dependencies and FFmpeg availability
│
├── run.py                # CORE LOGIC. Contains video processing, downloading, clipping, FFmpeg filters, and CLI entry point.
├── app.py                # Flask Web Server. Exposes REST API and serves the UI. Integrates with background jobs.
├── job_service.py        # Job database (SQLite) management. Tracks job progress, state, and history.
├── queue_client.py       # RabbitMQ publisher/consumer client for async processing.
├── worker.py             # Background worker daemon that consumes from RabbitMQ and runs `process_job`.
│
├── templates/            # Contains Flask HTML templates.
│   └── index.html        # Single-page frontend UI. Uses Vanilla HTML/CSS/JS. No frontend framework!
│
├── clips/                # OUTPUT DIRECTORY. Generated .mp4 clips, .srt subtitles, and SQLite jobs database reside here.
│
└── venv/                 # Python Virtual Environment
```

## 3. Core Architecture & Workflows

### 3.1. Video Processing Workflow (`run.py`)
- **No external Video Libraries:** All video manipulation (cropping, splitting, overlaying, subtitle burning) is done strictly by building complex FFmpeg filter strings (`-vf` or `-filter_complex`) and executing them via `subprocess.run()`.
- **yt-dlp Integration:** Information retrieval and initial segment downloading is handled by invoking `yt-dlp` as a module or subprocess command.
- **Whisper Subtitles:** Subtitle generation is done via `faster-whisper`. The `run.py` script normalizes subtitles, saves an `.srt` file, and uses FFmpeg to hard-burn them into the video.

### 3.2. Web Server & Job Execution (`app.py`, `job_service.py`, `worker.py`)
- The web app runs on Flask (`app.py`).
- **Asynchronous Execution:** 
  - If `ASYNC_ENABLED=1`, submitting a job via the UI publishes a message to RabbitMQ (`queue_client.py`).
  - `worker.py` listens to the queue and triggers `process_job` (located in `job_service.py`).
  - If RabbitMQ fails or is disabled, it falls back to a background thread (`threading.Thread`) directly in Flask.
- **Job Tracking:** Job statuses, progress, logs, and results are stored in an SQLite database `clips/jobs.db` managed entirely by `job_service.py`.

### 3.3. Frontend UI (`templates/index.html`)
- The UI is a single HTML file containing its own CSS (`<style>`) and JavaScript.
- **No Build Tools:** Do not introduce Webpack, Vite, React, Vue, or Tailwind. Keep it Vanilla HTML/CSS/JS.
- **Interactivity:** It polls the Flask backend `/api/jobs/<job_id>` for progress updates and heavily uses standard Web APIs (`fetch`).

## 4. Anti-Hallucination Rules & Best Practices for AI

> [!WARNING]
> Follow these strict rules when modifying this codebase to prevent breaking the application.

1. **Do not introduce OOP where procedural is used:** `run.py` is procedural and relies heavily on dictionaries and standalone functions. Do not attempt to refactor the entire logic into OOP classes unless explicitly requested by the user.
2. **Do not change FFmpeg syntax without testing:** FFmpeg filter graphs (`-filter_complex`, `-vf`) are very brittle. When modifying crop logic or adding overlays, ensure you deeply understand the existing `scale`, `split`, `crop`, and `vstack` logic in `run.py`.
3. **Paths:** Do not import files from non-existent directories like `utils/` or `services/`. Keep new logic within the existing files (`run.py` for video, `job_service.py` for DB, `app.py` for routing) or ask the user before creating new structural directories.
4. **No ORM:** `job_service.py` uses raw `sqlite3` queries. Do not try to import or set up SQLAlchemy or Peewee.
5. **No Frontend Frameworks:** When modifying `templates/index.html`, write vanilla JS (`document.getElementById`, `addEventListener`, `fetch`). Do not suggest adding React/Vue.

## 5. Development Advice

- **When adding new crop modes:** You must update both `run.py` (for the actual FFmpeg logic and `main` CLI options) and `templates/index.html` (to add the new UI card), and finally `app.py` (to pass the parameter correctly and handle the preview generation).
- **When adding new text overlays:** Follow the pattern used in `build_source_tag_filter` in `run.py`. Note that text must be properly escaped (`_escape_drawtext_text`).
- **Testing:** Since the processing can take time, the system uses a 'Preview Lab' to generate single frames. If you change video layout dimensions, ensure you also update `_build_preview_crop_command` in `app.py` so the Web UI preview reflects the changes.
