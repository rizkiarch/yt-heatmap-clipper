import os
import platform
import re
import json
import sys
import subprocess
import requests
import shutil
import time
import uuid
from glob import glob
from urllib.parse import urlparse, parse_qs
from functools import wraps, lru_cache
import warnings
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

# ── Retry Configuration ──────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
RETRY_BACKOFF = 2  # multiplier

OUTPUT_DIR = "clips"      # Directory where generated clips will be saved
MAX_DURATION = 160         # Maximum duration (in seconds) for each clip
MIN_DURATION = 60          # Minimum duration (in seconds) for each clip
MIN_SCORE = 0.15          # Minimum heatmap intensity score to be considered viral
MAX_CLIPS = 20           # Maximum number of clips to generate per video
MAX_WORKERS = 1           # Number of parallel workers (reserved for future concurrency)
PADDING = 10              # Extra seconds added before and after each detected segment
TOP_HEIGHT = 960          # Height for top section (center content) in split mode
BOTTOM_HEIGHT = 320       # Height for bottom section (facecam) in split mode (Total: 1280px)
USE_SUBTITLE = True       # Enable auto subtitle using Faster-Whisper (4-5x faster)
WHISPER_MODEL = "large-v3"   # Whisper model size: tiny, base, small, medium, large-v3
SAVE_RAW_SUBTITLE = True  # Save generated .srt subtitle file alongside output clip
SOURCE_TAG_DEFAULT_INTERVAL = 30.0  # Seconds between each source tag animation cycle
MASK_BUILTIN_SUBTITLE = True  # Mask lower area to hide hardcoded source subtitles before burning new subtitles.
BUILTIN_SUBTITLE_MASK_HEIGHT_RATIO = 0.22
BUILTIN_SUBTITLE_MASK_COLOR = "black@1.0"

# Subtitle splitting limits to prevent wall-of-text on screen
SUBTITLE_MAX_WORDS_PER_ENTRY = 8      # Max words shown per subtitle entry
SUBTITLE_MAX_DURATION_PER_ENTRY = 4.0   # Max seconds a subtitle stays on screen

PREVIEW_STAGE_BASE_WIDTH = 280.0
RENDER_STAGE_WIDTH = 720.0
PREVIEW_TO_RENDER_SCALE = RENDER_STAGE_WIDTH / PREVIEW_STAGE_BASE_WIDTH

# --- Subtitle Style Presets ---
# Each preset maps to an FFmpeg `force_style` string for the subtitles filter.
SUBTITLE_STYLES = {
    "modern": (
        "FontName=Arial,FontSize=14,Bold=1,"
        "PrimaryColour=&HFFFFFF,OutlineColour=&H78000000,"
        "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=50"
    ),
    "karaoke": (
        "FontName=Arial,FontSize=16,Bold=1,"
        "PrimaryColour=&H7DF9FF,OutlineColour=&H96000000,"
        "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=50"
    ),
    "minimal": (
        "FontName=Arial,FontSize=11,Bold=0,"
        "PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,"
        "BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=30"
    ),
    "bold": (
        "FontName=Impact,FontSize=20,Bold=1,"
        "PrimaryColour=&HFFFFFF,OutlineColour=&H5A000000,"
        "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=55"
    ),
    "neon": (
        "FontName=Arial,FontSize=14,Bold=1,"
        "PrimaryColour=&H00FF88,OutlineColour=&HFF00AA,"
        "BorderStyle=1,Outline=2,Shadow=1,ShadowColour=&H80FF00FF,"
        "Alignment=2,MarginV=50"
    ),
}

# --- Source Tag Style Presets ---
# Each preset is a callable builder or a key used in build_source_tag_filter.
SOURCE_TAG_STYLES = {
    "classic": {
        "box_color": "black@0.42",
        "accent_color": "red@0.95",
        "text_color": "white",
        "accent_icon": ">",
    },
    "glass": {
        "box_color": "white@0.15",
        "accent_color": "white@0.6",
        "text_color": "white",
        "accent_icon": "▶",
    },
    "minimal": {
        "box_color": None,  # No background box
        "accent_color": None,
        "text_color": "white",
        "accent_icon": "",
    },
    "neon": {
        "box_color": "black@0.55",
        "accent_color": "0x00FF88@0.95",
        "text_color": "0x00FF88",
        "accent_icon": "▶",
    },
}

# --- Video Quality Presets ---
VIDEO_QUALITY_PRESETS = {
    "high": {"resolution": 1080, "crf": 18, "preset": "slow", "label": "High (1080p)"},
    "medium": {"resolution": 720, "crf": 23, "preset": "medium", "label": "Medium (720p)"},
    "fast": {"resolution": 720, "crf": 28, "preset": "ultrafast", "label": "Fast (720p)"},
}

# --- Overlay Control Presets ---
OVERLAY_PRESETS = {
    "compact": {
        "subtitle_font_size": 28,
        "subtitle_bottom_margin": 72,
        "subtitle_max_chars": 24,
        "source_tag_scale": 0.88,
        "source_tag_position": "top-right",
        "label": "Compact",
    },
    "professional": {
        "subtitle_font_size": 34,
        "subtitle_bottom_margin": 100,
        "subtitle_max_chars": 30,
        "source_tag_scale": 1.0,
        "source_tag_position": "top-left",
        "label": "Professional",
    },
    "bold": {
        "subtitle_font_size": 42,
        "subtitle_bottom_margin": 140,
        "subtitle_max_chars": 36,
        "source_tag_scale": 1.12,
        "source_tag_position": "top-left",
        "label": "Bold",
    },
}
DEFAULT_OVERLAY_PRESET = "compact"


def retry_on_failure(max_retries=None, retry_delay=None, exceptions=None):
    """
    Decorator for retrying functions on failure with exponential backoff.
    Usage: @retry_on_failure(max_retries=3, retry_delay=2)
    """
    if max_retries is None:
        max_retries = MAX_RETRIES
    if retry_delay is None:
        retry_delay = RETRY_DELAY
    if exceptions is None:
        exceptions = (Exception,)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = retry_delay

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        print(f"⚠️  Attempt {attempt}/{max_retries} failed: {e}")
                        print(f"   Retrying in {delay}s...")
                        time.sleep(delay)
                        delay *= RETRY_BACKOFF  # Exponential backoff
                    else:
                        print(f"❌ All {max_retries} attempts failed for {func.__name__}")

            raise last_exception
        return wrapper
    return decorator


def clamp_int(value, minimum, maximum, default):
    """Clamp an integer value to safe bounds."""
    try:
        v = int(value)
    except Exception:
        v = int(default)
    return max(int(minimum), min(int(maximum), v))


def clamp_float(value, minimum, maximum, default):
    """Clamp a float value to safe bounds."""
    try:
        v = float(value)
    except Exception:
        v = float(default)
    return max(float(minimum), min(float(maximum), v))


# ── yt-dlp Network Configuration ─────────────────────────────────────────────
YTDLP_SOCKET_TIMEOUT = clamp_int(os.getenv("YTDLP_SOCKET_TIMEOUT", ""), 10, 120, 30)
YTDLP_EXTRACTOR_RETRIES = clamp_int(os.getenv("YTDLP_EXTRACTOR_RETRIES", ""), 1, 10, 3)
INTER_CLIP_DELAY = clamp_int(os.getenv("INTER_CLIP_DELAY", ""), 0, 120, 10)  # Seconds to wait between clip downloads
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "").strip()


def _get_ytdlp_format_choice():
    """
    Resolve yt-dlp format selector with optional env overrides.
    Returns (format_selector, has_override).
    """
    override = os.getenv("YTDLP_FORMAT", "").strip()
    if override:
        return override, True

    max_height = clamp_int(os.getenv("YTDLP_MAX_HEIGHT", ""), 144, 4320, 1080)
    selector = (
        f"bestvideo[height<={max_height}]+bestaudio/"
        f"best[height<={max_height}]/best"
    )
    return selector, False


def _resolve_download_output_path(output_base):
    """
    Resolve the actual yt-dlp output file from a base name.
    """
    if output_base and os.path.exists(output_base):
        return output_base

    candidates = []
    for path in glob(f"{output_base}.*"):
        if not os.path.isfile(path):
            continue
        if path.endswith(".part") or path.endswith(".ytdl") or path.endswith(".temp"):
            continue
        candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=os.path.getmtime)


def _cleanup_temp_download(output_base):
    if not output_base:
        return
    for path in glob(f"{output_base}.*"):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def sanitize_filename(title):
    """
    Sanitize a YouTube video title for use as a filename.
    Removes special characters, limits length, and normalizes whitespace.
    """
    if not title:
        return "clip"
    # Remove characters not allowed in filenames
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    # Collapse whitespace
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    # Limit length
    if len(sanitized) > 80:
        sanitized = sanitized[:80].rsplit(' ', 1)[0]
    return sanitized or "clip"


def clamp_clip_duration(seconds):
    """
    Clamp clip duration using configurable MIN_DURATION and MAX_DURATION.
    """
    max_dur = max(1.0, float(MAX_DURATION))
    min_dur = max(1.0, float(MIN_DURATION))
    if min_dur > max_dur:
        min_dur = max_dur
    return min(max(float(seconds), min_dur), max_dur)

def extract_video_id(url):
    """
    Extract the YouTube video ID from a given URL.
    Supports standard YouTube URLs, shortened URLs, and Shorts URLs.
    """
    parsed = urlparse(url)

    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path[1:]

    if parsed.hostname in ("youtube.com", "www.youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2]

    return None


def get_model_size(model):
    """
    Get the approximate size of a Whisper model.
    """
    sizes = {
        "tiny": "75 MB",
        "base": "142 MB",
        "small": "466 MB",
        "medium": "1.5 GB",
        "large-v1": "2.9 GB",
        "large-v2": "2.9 GB",
        "large-v3": "2.9 GB"
    }
    return sizes.get(model, "unknown size")


def _get_ytdlp_auth_args():
    """
    Build extra yt-dlp CLI args for YouTube authentication/cookies.
    Detects, in priority order:
      1. YTDLP_COOKIES_FILE env var or cookies.txt in project root
      2. YTDLP_COOKIES_FROM_BROWSER env var (chrome/firefox/edge/safari)
      3. YTDLP_PO_TOKEN + YTDLP_VISITOR_DATA for YouTube PO token bypass
    Returns a list of extra CLI args.
    """
    extra = []

    # 1. Cookies file
    cookies_file = os.getenv("YTDLP_COOKIES_FILE", "").strip()
    if not cookies_file:
        # Auto-detect cookies.txt in project root
        auto_cookies = os.path.join(os.path.dirname(__file__), "cookies.txt")
        if os.path.exists(auto_cookies):
            cookies_file = auto_cookies
    if cookies_file:
        resolved = os.path.join(os.path.dirname(__file__), cookies_file) if not os.path.isabs(cookies_file) else cookies_file
        if os.path.exists(resolved):
            extra.extend(["--cookies", resolved])
            return extra  # cookies file is the strongest method
        print(f"⚠️  Cookies file not found: {resolved}. Skipping cookies auth.")

    # 2. Browser cookies
    browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip().lower()
    if browser:
        # yt-dlp supports: chrome, firefox, edge, safari, opera, chromium, etc.
        extra.extend(["--cookies-from-browser", browser])
        return extra

    # 3. PO Token + Visitor Data (YouTube-specific)
    po_token = os.getenv("YTDLP_PO_TOKEN", "").strip()
    visitor_data = os.getenv("YTDLP_VISITOR_DATA", "").strip()
    if po_token:
        if po_token.lower() == "auto":
            extra.extend(["--extractor-args", "youtube:player_client=web;po_token=web+auto"])
        else:
            extra.extend(["--extractor-args", f"youtube:player_client=web;po_token=web+{po_token}"])
    if visitor_data:
        extra.extend(["--extractor-args", f"youtube:player_client=web;visitor_data={visitor_data}"])

    return extra


def _get_ytdlp_network_args():
    """
    Build network-related yt-dlp CLI args (timeout, retries, proxy).
    Includes both --socket-timeout (TCP) and --retries (HTTP-level) to cover
    yt-dlp internal requests that may use a separate timeout value.
    """
    extra = [
        "--socket-timeout", str(YTDLP_SOCKET_TIMEOUT),
        "--extractor-retries", str(YTDLP_EXTRACTOR_RETRIES),
        "--retries", str(YTDLP_EXTRACTOR_RETRIES),
    ]
    if YTDLP_PROXY:
        extra.extend(["--proxy", YTDLP_PROXY])
    return extra


def _has_js_runtime():
    """Check whether a JS runtime required by yt-dlp-ejs is available."""
    for binary in ["deno", "node", "bun", "qjs"]:
        if shutil.which(binary):
            return binary
    return None


def _install_ytdlp_ejs():
    """Install or update the yt-dlp external JS solver package."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp-ejs"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def check_dependencies(install_whisper=False, update_ytdlp=True):
    """
    Ensure required dependencies are available.
    Automatically updates yt-dlp, yt-dlp-ejs, checks FFmpeg,
    and warns about missing JS runtime (Deno/Node) needed for YouTube.
    """
    # 1. Update yt-dlp core
    if update_ytdlp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    # 2. yt-dlp YouTube support now requires an external JS solver (2025.11.12+)
    _install_ytdlp_ejs()

    js_runtime = _has_js_runtime()
    if not js_runtime:
        print(
            "⚠️  WARNING: No JavaScript runtime found (Deno / Node.js / Bun / QuickJS).\n"
            "   yt-dlp YouTube support requires a JS runtime since late 2025.\n"
            "   Install Deno (recommended): https://docs.deno.com/getting_started/installation\n"
            "   Or Node.js: https://nodejs.org/\n"
            "   Without it, most YouTube formats will be unavailable.\n"
        )
    else:
        print(f"✅ JavaScript runtime found: {js_runtime}")

    # 3. Whisper
    if install_whisper:
        try:
            import faster_whisper
            print(f"✅ Faster-Whisper package installed.")

            cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
            model_name = f"faster-whisper-{WHISPER_MODEL}"

            model_cached = False
            if os.path.exists(cache_dir):
                try:
                    cached_items = os.listdir(cache_dir)
                    model_cached = any(model_name in item.lower() for item in cached_items)
                except Exception:
                    pass

            if model_cached:
                print(f"✅ Model '{WHISPER_MODEL}' already cached and ready.\n")
            else:
                print(f"⚠️  Model '{WHISPER_MODEL}' not found in cache.")
                print(f"   📥 Will auto-download ~{get_model_size(WHISPER_MODEL)} on first transcribe.")
                print(f"   ⏱️  Download happens only once, then cached for future use.\n")

        except ImportError:
            print("📦 Installing Faster-Whisper package...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "faster-whisper"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            print(f"✅ Faster-Whisper package installed successfully.")
            print(f"⚠️  Model '{WHISPER_MODEL}' (~{get_model_size(WHISPER_MODEL)}) will be downloaded on first use.\n")

    # 4. FFmpeg
    if not shutil.which("ffmpeg"):
        print("FFmpeg not found. Please install FFmpeg and ensure it is in PATH.")
        sys.exit(1)


def check_video_availability(video_id, metadata=None):
    """
    Inspect metadata and return (is_available: bool, reason: str).
    Catches private videos, region blocks, age-gate, and removed videos
    before attempting expensive download attempts.
    """
    if metadata is None:
        metadata = get_video_metadata(video_id)

    if not metadata:
        return (
            False,
            "Could not retrieve video metadata. Possible causes:\n"
            "  - The video is private, removed, or region-blocked\n"
            "  - YouTube rate limiting (wait a few minutes)\n"
            "  - Missing JS runtime or outdated yt-dlp-ejs (ensure Deno/Node is installed)\n"
            "  - Missing or expired cookies for age-restricted videos",
        )

    title = metadata.get("title") or ""
    if title.lower() in ("[private video]", "private video"):
        return False, "This video is private."

    if metadata.get("availability") == "needs_auth":
        return False, "This video requires sign-in (age-restricted or members-only). Set cookies to proceed."

    if metadata.get("availability") == "unavailable":
        return False, "This video is unavailable (removed, region-blocked, or account terminated)."

    live_status = metadata.get("live_status")
    if live_status == "is_live":
        return False, "This video is currently live. Live streams are not supported for clipping."

    formats = metadata.get("formats") or []
    if not formats and not metadata.get("url"):
        return False, "No downloadable formats found. This usually means yt-dlp's JS solver is missing or outdated."

    return True, ""


def _list_available_formats(video_id):
    """
    Run yt-dlp --list-formats to help the user debug why downloads failed.
    Prints a concise summary (best formats only) to avoid log spam.
    """
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--quiet", "--no-warnings",
        "--list-formats",
    ] + _get_ytdlp_auth_args() + _get_ytdlp_network_args() + [
        f"https://youtu.be/{video_id}",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        lines = res.stdout.splitlines()
        # Show at most the first 30 lines to avoid flooding the console.
        summary = "\n".join(lines[:30])
        print(f"\n📋 Available formats (first 30 lines):\n{summary}")
        if len(lines) > 30:
            print(f"   ... ({len(lines) - 30} more lines omitted)")
    except Exception as e:
        print(f"   Could not list formats: {e}")


def _extract_json_blob(text, marker):
    """
    Extract a JSON object assigned to a marker (e.g. ytInitialData).
    Uses brace-matching so it is resilient to large nested payloads.
    """
    marker_index = text.find(marker)
    if marker_index == -1:
        return None

    start = text.find("{", marker_index)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def _collect_heat_markers(node, out):
    """
    Walk nested JSON and collect heat marker objects.
    """
    if isinstance(node, dict):
        current = node.get("heatMarkerRenderer", node)

        if (
            isinstance(current, dict)
            and "startMillis" in current
            and "durationMillis" in current
            and "intensityScoreNormalized" in current
        ):
            out.append(current)

        for value in node.values():
            _collect_heat_markers(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_heat_markers(item, out)


def fetch_most_replayed(video_id):
    """
    Fetch and parse YouTube 'Most Replayed' heatmap data.
    Returns a list of high-engagement segments.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "Referer": "https://www.youtube.com/"
    }

    print("Reading YouTube heatmap data...")

    html = ""
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            html = response.text
            break
        except requests.exceptions.Timeout:
            if attempt < retries:
                wait = attempt * 2
                print(f"    Heatmap fetch timed out (attempt {attempt}/{retries}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print("Failed to fetch YouTube page after all retries (timeout).")
                return []
        except Exception as e:
            print(f"Failed to fetch YouTube page: {e}")
            return []

    if not html:
        print("Failed to fetch YouTube page (empty response).")
        return []

    # Some regions/accounts return interstitial pages without watch data.
    if "ytInitialData" not in html and "ytInitialPlayerResponse" not in html:
        print("Watch data not found in page source (possible consent/sign-in interstitial).")
        return []

    raw_markers = []

    # Strategy 1: parse known YouTube JSON payloads.
    for marker_name in ("ytInitialData", "ytInitialPlayerResponse"):
        blob = _extract_json_blob(html, marker_name)
        if not blob:
            continue

        try:
            data = json.loads(blob)
            _collect_heat_markers(data, raw_markers)
        except Exception:
            continue

    # Strategy 2: fallback regex for changing page layouts.
    if not raw_markers:
        fallback_pattern = re.compile(
            r'"startMillis":"?(\d+)"?.*?'
            r'"durationMillis":"?(\d+)"?.*?'
            r'"intensityScoreNormalized":([0-9.]+)',
            re.DOTALL
        )
        for start_millis, duration_millis, score_value in fallback_pattern.findall(html):
            raw_markers.append({
                "startMillis": start_millis,
                "durationMillis": duration_millis,
                "intensityScoreNormalized": score_value
            })

    if not raw_markers:
        print("No 'Most Replayed' marker data found for this video.")
        return []

    results = []
    max_seen_score = 0.0

    for marker in raw_markers:
        try:
            score = float(marker.get("intensityScoreNormalized", 0))
            max_seen_score = max(max_seen_score, score)
            if score >= MIN_SCORE:
                results.append({
                    "start": float(marker["startMillis"]) / 1000,
                    "duration": clamp_clip_duration(float(marker["durationMillis"]) / 1000),
                    "score": score
                })
        except Exception:
            continue

    if not results:
        # Keep processing by selecting top heatmap points even below threshold.
        fallback_candidates = []
        for marker in raw_markers:
            try:
                score = float(marker.get("intensityScoreNormalized", 0))
                fallback_candidates.append({
                    "start": float(marker["startMillis"]) / 1000,
                    "duration": clamp_clip_duration(float(marker["durationMillis"]) / 1000),
                    "score": score,
                })
            except Exception:
                continue

        fallback_candidates.sort(key=lambda x: x["score"], reverse=True)
        results = fallback_candidates[:MAX_CLIPS]

        if results:
            print(
                f"Heatmap found, but no segment passed MIN_SCORE={MIN_SCORE:.2f}. "
                f"Using top {len(results)} segment(s) anyway (max score: {max_seen_score:.2f})."
            )
            return results

        print(
            f"Heatmap found, but no segment passed MIN_SCORE={MIN_SCORE:.2f}. "
            f"Max score found: {max_seen_score:.2f}. Try lowering MIN_SCORE to 0.30 or 0.25."
        )
        return []

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def fetch_fallback_segments(video_id, total_duration, metadata=None):
    """
    Build fallback segments when Most Replayed heatmap is unavailable.
    Priority: yt-dlp heatmap -> chapters -> evenly spaced timeline slices.
    """
    url = f"https://youtu.be/{video_id}"
    print("Trying fallback segment strategies...")

    # Strategy 1 and 2: pull metadata once via yt-dlp.
    if metadata is None:
        metadata = get_video_metadata(video_id)

    if metadata:
        # Strategy 1: yt-dlp heatmap (when available).
        heatmap = metadata.get("heatmap") or []
        heatmap_results = []
        for point in heatmap:
            try:
                start = float(point.get("start_time", 0))
                end = float(point.get("end_time", start))
                duration = min(max(3.0, end - start), MAX_DURATION)
                duration = clamp_clip_duration(duration)
                score = float(point.get("value", 0))
                heatmap_results.append({
                    "start": start,
                    "duration": duration,
                    "score": score,
                })
            except Exception:
                continue

        if heatmap_results:
            heatmap_results.sort(key=lambda x: x["score"], reverse=True)
            print(f"Using yt-dlp heatmap fallback ({len(heatmap_results)} point(s)).")
            return heatmap_results

        # Strategy 2: chapter-based clips.
        chapters = metadata.get("chapters") or []
        chapter_results = []
        for idx, chapter in enumerate(chapters):
            try:
                start = float(chapter.get("start_time", 0))
                end = float(chapter.get("end_time", start))
                duration = min(max(3.0, end - start), MAX_DURATION)
                duration = clamp_clip_duration(duration)
                chapter_results.append({
                    "start": start,
                    "duration": duration,
                    "score": max(0.1, 1.0 - (idx * 0.02)),
                })
            except Exception:
                continue

        if chapter_results:
            print(f"Using chapter fallback ({len(chapter_results)} chapter(s)).")
            return chapter_results

    # Strategy 3: evenly spaced slices across timeline.
    if total_duration <= 0:
        return []

    target_segments = min(MAX_CLIPS, max(3, total_duration // 300))
    step = max(1, total_duration // target_segments)
    interval_results = []

    for idx in range(target_segments):
        start = idx * step
        if start >= total_duration:
            break

        duration = clamp_clip_duration(max(20, step // 2))
        interval_results.append({
            "start": float(start),
            "duration": float(duration),
            "score": max(0.05, 0.3 - (idx * 0.01)),
        })

    if interval_results:
        print(f"Using timeline interval fallback ({len(interval_results)} segment(s)).")
    return interval_results


@retry_on_failure(max_retries=3, retry_delay=2, exceptions=(subprocess.CalledProcessError,))
def download_video_segment(video_id, start, end, output_base):
    """
    Download a specific segment of a YouTube video.
    Uses yt-dlp --download-sections for native segment support (works with DASH/HLS).
    Falls back through multiple strategies if the primary method fails.
    """
    format_selector, has_override = _get_ytdlp_format_choice()
    output_template = f"{output_base}.%(ext)s"
    section = f"*{start}-{end}"

    def _build_cmd(fmt=None, extra_args=None):
        """Build a yt-dlp command for segment download."""
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--quiet", "--no-warnings",
            "--download-sections", section,
            "-o", output_template,
        ]
        if fmt is not None:
            cmd.extend(["-f", fmt])
        if extra_args:
            cmd.extend(extra_args)
        cmd.extend(_get_ytdlp_auth_args())
        cmd.extend(_get_ytdlp_network_args())
        cmd.append(f"https://youtu.be/{video_id}")
        return cmd

    def _run(cmd):
        return subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    # Primary attempt: native yt-dlp segment download with format selector
    try:
        _run(_build_cmd(format_selector))
        return _resolve_download_output_path(output_base)
    except subprocess.CalledProcessError as e:
        last_error = e
        error_text = (e.stderr or e.stdout or "").lower()

        # Bot check / sign-in errors: fail fast if already triggered in this session.
        if "sign in to confirm" in error_text or "confirm you're not a bot" in error_text:
            raise RuntimeError(
                "YouTube bot check blocked the download. "
                "Your cookies may be expired or missing. "
                "Update cookies.txt or set YTDLP_COOKIES_FROM_BROWSER, "
                "or wait a few minutes before retrying. "
                "If cookies expire after a few videos, try increasing INTER_CLIP_DELAY (e.g., export INTER_CLIP_DELAY=30)."
            ) from e

        if "requested format is not available" in error_text:
            if has_override:
                print(
                    "    ⚠️  Custom YTDLP_FORMAT is set but unavailable. "
                    "Bypassing it with fallback formats..."
                )

            # Fallback 1 & 2: simpler format selectors
            for fallback_fmt in ["best", "bestvideo+bestaudio/best"]:
                try:
                    _run(_build_cmd(fallback_fmt))
                    return _resolve_download_output_path(output_base)
                except subprocess.CalledProcessError as fallback_err:
                    last_error = fallback_err
                    print(
                        f"    Format fallback '{fallback_fmt}' failed: "
                        f"{fallback_err.stderr or fallback_err.stdout or 'unknown error'}"
                    )

            # Fallback 3: let yt-dlp choose format itself
            try:
                _run(_build_cmd())
                return _resolve_download_output_path(output_base)
            except subprocess.CalledProcessError as no_f_err:
                last_error = no_f_err
                print(
                    f"    No-format fallback failed: "
                    f"{no_f_err.stderr or no_f_err.stdout or 'unknown error'}"
                )

            # Fallback 4: Android client (often bypasses restrictions)
            try:
                _run(_build_cmd(extra_args=["--extractor-args", "youtube:player_client=android"]))
                return _resolve_download_output_path(output_base)
            except subprocess.CalledProcessError as android_err:
                last_error = android_err
                print(
                    f"    Android client fallback failed: "
                    f"{android_err.stderr or android_err.stdout or 'unknown error'}"
                )

            # Fallback 5: iOS client (another common bypass)
            try:
                _run(_build_cmd(extra_args=["--extractor-args", "youtube:player_client=ios"]))
                return _resolve_download_output_path(output_base)
            except subprocess.CalledProcessError as ios_err:
                last_error = ios_err
                print(
                    f"    iOS client fallback failed: "
                    f"{ios_err.stderr or ios_err.stdout or 'unknown error'}"
                )

            # Fallback 6: web_creator client (often works for restricted videos)
            try:
                _run(_build_cmd(extra_args=["--extractor-args", "youtube:player_client=web_creator"]))
                return _resolve_download_output_path(output_base)
            except subprocess.CalledProcessError as webc_err:
                last_error = webc_err
                print(
                    f"    Web Creator client fallback failed: "
                    f"{webc_err.stderr or webc_err.stdout or 'unknown error'}"
                )

            # Fallback 7: tv client (another option for restricted videos)
            try:
                _run(_build_cmd(extra_args=["--extractor-args", "youtube:player_client=tv"]))
                return _resolve_download_output_path(output_base)
            except subprocess.CalledProcessError as tv_err:
                last_error = tv_err
                print(
                    f"    TV client fallback failed: "
                    f"{tv_err.stderr or tv_err.stdout or 'unknown error'}"
                )

            # Fallback 8: download full video with default settings, then ffmpeg extract
            full_cmd = [
                sys.executable, "-m", "yt_dlp",
                "--quiet", "--no-warnings",
                "--no-post-overwrites",
                "-f", "best[ext=mp4]/best",
                "-o", output_template,
            ] + _get_ytdlp_auth_args() + _get_ytdlp_network_args() + [
                f"https://youtu.be/{video_id}"
            ]
            try:
                _run(full_cmd)
                downloaded = _resolve_download_output_path(output_base)
                if downloaded and os.path.exists(downloaded):
                    extracted = f"{output_base}_extracted.mp4"
                    extract_cmd = [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", str(start), "-to", str(end),
                        "-i", downloaded,
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                        "-c:a", "aac", "-b:a", "128k",
                        extracted,
                    ]
                    _run(extract_cmd)
                    try:
                        os.remove(downloaded)
                    except Exception:
                        pass
                    return extracted
            except subprocess.CalledProcessError as full_err:
                last_error = full_err
                err_detail = full_err.stdout or str(full_err)
                print(
                    f"    Full download + ffmpeg extract fallback failed: "
                    f"{err_detail}"
                )

            # Debug: list available formats to help user understand the failure
            print("\n🔍 Listing available formats for debugging...")
            _list_available_formats(video_id)

        raise RuntimeError(
            f"All download strategies failed for {video_id} segment {start}-{end}. "
            f"Last error: {last_error.stdout or str(last_error)}"
        ) from last_error


@retry_on_failure(max_retries=3, retry_delay=2, exceptions=(subprocess.CalledProcessError, Exception))
def get_duration(video_id):
    """
    Retrieve the total duration of a YouTube video in seconds.
    With retry mechanism for transient failures.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--get-duration",
    ] + _get_ytdlp_auth_args() + _get_ytdlp_network_args() + [
        f"https://youtu.be/{video_id}"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        time_parts = res.stdout.strip().split(":")

        if len(time_parts) == 2:
            return int(time_parts[0]) * 60 + int(time_parts[1])
        if len(time_parts) == 3:
            return (
                int(time_parts[0]) * 3600 +
                int(time_parts[1]) * 60 +
                int(time_parts[2])
            )
    except Exception as e:
        print(f"⚠️  Could not parse video duration ({e}), defaulting to 3600s.")

    return 3600


@retry_on_failure(max_retries=3, retry_delay=3, exceptions=(Exception,))
def get_video_metadata(video_id):
    """
    Retrieve yt-dlp JSON metadata once so it can be reused.
    With retry mechanism for transient failures.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--skip-download",
        "-J",
    ] + _get_ytdlp_auth_args() + _get_ytdlp_network_args() + [
        f"https://youtu.be/{video_id}"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except subprocess.CalledProcessError as e:
        err_text = (e.stderr or e.stdout or "").lower()
        print(f"⚠️  yt-dlp metadata fetch failed: {err_text[:500]}")
        if "sign in to confirm" in err_text or "confirm you're not a bot" in err_text:
            print("   → YouTube bot check. Wait a few minutes or use cookies.")
        elif "429" in err_text or "too many requests" in err_text:
            print("   → Rate limited by YouTube. Wait a few minutes before retrying.")
        elif "read timed out" in err_text or "connection timed out" in err_text or "timeout" in err_text:
            print("   → Connection timeout. YouTube is slow or unreachable.")
            print(f"     Current timeout: {YTDLP_SOCKET_TIMEOUT}s (yt-dlp internal may still use 20s)")
            print(f"     Try increasing timeout: export YTDLP_SOCKET_TIMEOUT=60")
            print(f"     Also try waiting 2-3 minutes before retrying (possible IP rate-limit).")
            if not YTDLP_PROXY:
                print(f"     If behind a proxy/firewall, set: export YTDLP_PROXY=http://proxy:port")
        return None
    except Exception as e:
        print(f"⚠️  Unexpected error fetching metadata: {e}")
        return None


def get_duration_from_metadata(metadata):
    """
    Retrieve total duration from yt-dlp metadata when available.
    """
    if not isinstance(metadata, dict):
        return None

    value = metadata.get("duration")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)

    return None


def get_channel_name(video_id):
    """
    Retrieve channel/uploader name from YouTube metadata.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--skip-download",
        "-J",
    ] + _get_ytdlp_auth_args() + _get_ytdlp_network_args() + [
        f"https://youtu.be/{video_id}"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        return (
            data.get("channel")
            or data.get("uploader")
            or data.get("uploader_id")
            or "Unknown Channel"
        )
    except Exception:
        return "Unknown Channel"


def get_channel_name_from_metadata(metadata):
    """
    Retrieve channel/uploader name from yt-dlp metadata.
    """
    if not isinstance(metadata, dict):
        return "Unknown Channel"

    return (
        metadata.get("channel")
        or metadata.get("uploader")
        or metadata.get("uploader_id")
        or "Unknown Channel"
    )


def _escape_drawtext_text(text):
    """
    Escape text for FFmpeg drawtext filter.
    """
    if text is None:
        return ""

    escaped = str(text)
    escaped = escaped.replace("\\", "\\\\")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace("%", "\\%")
    return escaped


def build_source_tag_filter(
    channel_name,
    interval_seconds,
    style="classic",
    scale=1.0,
    position="top-left",
):
    """
    Build FFmpeg filter that shows animated source tag on top-left.
    Supports style presets: classic, glass, minimal, neon.
    """
    interval = max(4.0, float(interval_seconds))
    scale = clamp_float(scale, 0.60, 1.60, 1.0)
    normalized_position = str(position or "top-left").strip().lower().replace("_", "-")
    if normalized_position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        normalized_position = "top-left"

    channel = _escape_drawtext_text(channel_name)

    preset = SOURCE_TAG_STYLES.get(style, SOURCE_TAG_STYLES["classic"])
    box_color = preset["box_color"]
    accent_color = preset["accent_color"]
    text_color = preset["text_color"]
    accent_icon = preset.get("accent_icon", ">")

    # Geometry follows Preview Lab baseline (280x497) then projected to 720x1280 render.
    ratio = PREVIEW_TO_RENDER_SCALE
    edge_offset = int(round(14 * ratio))
    pad_x = int(round(10 * ratio * scale))
    pad_y = int(round(7 * ratio * scale))
    text_size = max(14, int(round(10.88 * ratio * scale)))
    icon_box = max(26, int(round(18 * ratio * scale)))
    icon_font = max(16, int(round(10.2 * ratio * scale)))
    gap = max(8, int(round(6 * ratio * scale)))
    # 28 chars keeps most channel names readable in one line at baseline scale.
    text_box_width = max(260, int(round(28 * text_size * 0.58)))
    box_h = max(icon_box + pad_y * 2, text_size + pad_y * 2)
    box_w = pad_x * 2 + icon_box + gap + text_box_width

    y_top = edge_offset
    y_bottom = max(12, 1280 - box_h - edge_offset)
    box_y = y_bottom if "bottom" in normalized_position else y_top

    icon_x_offset = pad_x
    icon_y = box_y + max(0, int(round((box_h - icon_box) / 2)))
    icon_text_x_offset = icon_x_offset + max(2, int(round(icon_box * 0.24)))
    icon_text_y = icon_y + max(0, int(round((icon_box - icon_font) / 2)))
    source_x_offset = pad_x + icon_box + gap
    source_y = box_y + max(0, int(round((box_h - text_size) / 2)))

    # Smooth slide-in/slide-out timing per cycle:
    # 0.00-0.42s in, 0.42-2.40s hold, 2.40-2.82s out.
    is_right = "right" in normalized_position
    if is_right:
        x_hidden = "w+30"
        x_hold = f"w-{box_w + edge_offset}"
        x_expr = (
            f"if(lt(mod(t\\,{interval:.2f})\\,0.42)\\,"
            f"({x_hidden})-(({x_hidden})-({x_hold}))*sin((mod(t\\,{interval:.2f})/0.42)*PI/2)\\,"
            f"if(lt(mod(t\\,{interval:.2f})\\,2.40)\\,({x_hold})\\,"
            f"if(lt(mod(t\\,{interval:.2f})\\,2.82)\\,"
            f"({x_hold})+(({x_hidden})-({x_hold}))*sin(((mod(t\\,{interval:.2f})-2.40)/0.42)*PI/2)\\,({x_hidden}))))"
        )
    else:
        x_hidden = f"-{box_w + 30}"
        x_hold = str(edge_offset)
        x_expr = (
            f"if(lt(mod(t\\,{interval:.2f})\\,0.42)\\,"
            f"({x_hidden})+(({x_hold})-({x_hidden}))*sin((mod(t\\,{interval:.2f})/0.42)*PI/2)\\,"
            f"if(lt(mod(t\\,{interval:.2f})\\,2.40)\\,({x_hold})\\,"
            f"if(lt(mod(t\\,{interval:.2f})\\,2.82)\\,"
            f"({x_hold})-(({x_hold})-({x_hidden}))*sin(((mod(t\\,{interval:.2f})-2.40)/0.42)*PI/2)\\,({x_hidden}))))"
        )

    parts = ["format=yuv420p"]

    if style == "minimal":
        # Minimal mode still keeps one-line source text to mirror fast preview layout.
        parts.append(
            f"drawtext=text='Source\\: {channel}':x='{x_expr}+{source_x_offset}':"
            f"y={source_y}:fontsize={text_size}:fontcolor={text_color}:shadowcolor=black@0.45:shadowx=1:shadowy=1"
        )
    else:
        # Background box
        if box_color:
            parts.append(f"drawbox=x='{x_expr}':y={box_y}:w={box_w}:h={box_h}:color={box_color}:t=fill")

        # Accent icon square
        if accent_color:
            parts.append(
                f"drawbox=x='{x_expr}+{icon_x_offset}':y={icon_y}:"
                f"w={icon_box}:h={icon_box}:color={accent_color}:t=fill"
            )

        # Icon/play symbol
        if accent_icon:
            parts.append(
                f"drawtext=text='{_escape_drawtext_text(accent_icon)}':x='{x_expr}+{icon_text_x_offset}':"
                f"y={icon_text_y}:fontsize={icon_font}:fontcolor={text_color}"
            )

        # Channel/source line in one row to match Preview Lab.
        parts.append(
            f"drawtext=text='Source\\: {channel}':x='{x_expr}+{source_x_offset}':"
            f"y={source_y}:fontsize={text_size}:fontcolor={text_color}"
        )

    return ",".join(parts)


def _wrap_long_word(word, max_chars):
    """Chunk a very long token so wrapping stays stable."""
    chunks = []
    while len(word) > max_chars:
        chunks.append(word[:max_chars])
        word = word[max_chars:]
    if word:
        chunks.append(word)
    return chunks


def wrap_subtitle_text(text, max_chars_per_line):
    """Wrap subtitle text by character width while preserving readability."""
    if not text:
        return ""

    max_chars = clamp_int(max_chars_per_line, 16, 64, 30)
    normalized = " ".join(str(text).strip().split())
    if len(normalized) <= max_chars:
        return normalized

    words = []
    for token in normalized.split(" "):
        if len(token) > max_chars:
            words.extend(_wrap_long_word(token, max_chars))
        else:
            words.append(token)

    lines = []
    current = ""

    for word in words:
        if not current:
            current = word
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        lines.append(current)
        current = word

    if current:
        lines.append(current)

    return "\n".join(lines)


# ── Subtitle Translation (Argos Translate) ─────────────────────────────────

@lru_cache(maxsize=4)
def _get_argos_translator(from_lang, to_lang):
    """Get cached Argos translator for a language pair."""
    import argostranslate.translate
    return argostranslate.translate.get_translation_from_codes(from_lang, to_lang)


def install_translation_packages():
    """Download and install Argos language packages for en↔id."""
    try:
        import argostranslate.package
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        installed = argostranslate.package.get_installed_packages()

        for from_code, to_code in [("en", "id"), ("id", "en")]:
            if any(p.from_code == from_code and p.to_code == to_code for p in installed):
                continue
            pkg = next((p for p in available if p.from_code == from_code and p.to_code == to_code), None)
            if pkg:
                argostranslate.package.install_from_path(pkg.download())
                print(f"    Installed translation package {from_code} → {to_code}")
    except Exception as e:
        print(f"    Warning: could not install translation packages: {e}")


def _parse_srt_file(srt_path):
    """Parse an SRT file into a list of subtitle entries."""
    entries = []
    if not os.path.exists(srt_path):
        return entries

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        # First line is the index number
        # Second line is the timestamp
        # Remaining lines are the text
        index_line = lines[0].strip()
        if not index_line.isdigit():
            continue
        timestamp_line = lines[1].strip()
        text = "\n".join(lines[2:]).strip()
        if not text:
            continue
        entries.append({
            "index": int(index_line),
            "timestamp": timestamp_line,
            "text": text,
        })
    return entries


def _write_srt_file(srt_path, entries):
    """Write subtitle entries to an SRT file."""
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(entries, start=1):
            f.write(f"{i}\n")
            f.write(f"{entry['timestamp']}\n")
            f.write(f"{entry['text']}\n\n")


def translate_srt_file(input_srt, output_srt, target_lang, source_lang="auto"):
    """
    Translate an SRT file using Argos Translate.
    Returns (success: bool, detected_source_lang: str).
    """
    try:
        entries = _parse_srt_file(input_srt)
        if not entries:
            return False, ""

        # Detect source language if auto
        if source_lang == "auto":
            sample_text = " ".join(e["text"][:100] for e in entries[:5])
            # Whisper language codes: 'en', 'id', etc.
            # Argos uses the same ISO codes for these languages
            detected = sample_text  # Argos doesn't have auto-detect; use the sample as-is
            # Since Whisper already detects, caller should pass source_lang
            # If truly auto, we try both directions and pick best
            source_lang = "en"  # default assumption; caller should override

        # Skip if source == target
        if source_lang == target_lang:
            shutil.copy2(input_srt, output_srt)
            return True, source_lang

        translator = _get_argos_translator(source_lang, target_lang)
        if translator is None:
            print(f"  Translation package {source_lang} → {target_lang} not found.")
            return False, source_lang

        translated_entries = []
        for entry in entries:
            translated_text = translator.translate(entry["text"])
            translated_entries.append({
                "index": entry["index"],
                "timestamp": entry["timestamp"],
                "text": translated_text,
            })

        _write_srt_file(output_srt, translated_entries)
        return True, source_lang
    except Exception as e:
        print(f"  Failed to translate subtitle: {e}")
        return False, source_lang


def build_subtitle_force_style(style_key, font_size=None, bottom_margin=None):
    """Build subtitle force_style string from preset + per-job overrides."""
    base_style = SUBTITLE_STYLES.get(style_key, SUBTITLE_STYLES["modern"])

    parsed = {}
    ordered_keys = []
    for part in base_style.split(","):
        entry = part.strip()
        if not entry or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        parsed[key] = value.strip()
        ordered_keys.append(key)

    # Values are already in render pixels (720x1280).
    render_font = clamp_int(font_size, 12, 48, 28)
    render_margin = clamp_int(bottom_margin, 20, 200, 72)

    parsed["FontSize"] = str(render_font)
    parsed["MarginV"] = str(render_margin)

    if "FontSize" not in ordered_keys:
        ordered_keys.append("FontSize")
    if "MarginV" not in ordered_keys:
        ordered_keys.append("MarginV")

    return ",".join([f"{key}={parsed[key]}" for key in ordered_keys if key in parsed])


def _split_subtitle_segment(segment, max_words=None, max_duration=None):
    """
    Split a long subtitle segment into smaller timed chunks.
    Distributes words and time proportionally.
    """
    if max_words is None:
        max_words = SUBTITLE_MAX_WORDS_PER_ENTRY
    if max_duration is None:
        max_duration = SUBTITLE_MAX_DURATION_PER_ENTRY

    start = segment["start"]
    end = segment["end"]
    text = segment["text"]
    total_duration = end - start
    words = text.split()

    # Nothing to split
    if total_duration <= 0 or not words:
        return [segment]

    # Determine how many parts we need
    word_count = len(words)
    needed_by_words = max(1, (word_count + max_words - 1) // max_words)
    needed_by_duration = max(1, int(total_duration // max_duration) + (1 if total_duration % max_duration > 0 else 0))
    num_parts = max(needed_by_words, needed_by_duration)

    if num_parts <= 1:
        return [segment]

    # Try to respect sentence boundaries when splitting
    sentence_ends = []
    for i, w in enumerate(words):
        if w.endswith((".", "!", "?")):
            sentence_ends.append(i + 1)

    # If we have natural sentence breaks and they fit within max_words, use them
    if sentence_ends and num_parts <= len(sentence_ends) + 1:
        parts = []
        last_idx = 0
        for idx in sentence_ends:
            if idx - last_idx <= max_words and idx < word_count:
                parts.append(" ".join(words[last_idx:idx]))
                last_idx = idx
        if last_idx < word_count:
            parts.append(" ".join(words[last_idx:]))
        if len(parts) >= num_parts:
            num_parts = len(parts)
        else:
            # Fall back to even word distribution
            base = word_count // num_parts
            extra = word_count % num_parts
            parts = []
            idx = 0
            for i in range(num_parts):
                count = base + (1 if i < extra else 0)
                parts.append(" ".join(words[idx:idx + count]))
                idx += count
    else:
        # Even word distribution
        base = word_count // num_parts
        extra = word_count % num_parts
        parts = []
        idx = 0
        for i in range(num_parts):
            count = base + (1 if i < extra else 0)
            parts.append(" ".join(words[idx:idx + count]))
            idx += count

    # Distribute time proportionally
    split_segments = []
    part_duration = total_duration / num_parts
    for i, part_text in enumerate(parts):
        if not part_text.strip():
            continue
        part_start = start + i * part_duration
        part_end = start + (i + 1) * part_duration
        # Ensure minimum 0.3s per entry and no negative duration
        if part_end <= part_start:
            part_end = part_start + 0.3
        split_segments.append({
            "start": round(part_start, 2),
            "end": round(part_end, 2),
            "text": part_text,
        })

    return split_segments


def _normalize_subtitle_segments(segments):
    """
    Normalize subtitle segments to avoid overlap and duplicated repeated lines.
    """
    normalized = []

    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue

        try:
            start = float(segment.start)
            end = float(segment.end)
        except Exception:
            continue

        if end <= start:
            end = start + 0.5

        if normalized:
            prev = normalized[-1]

            # Merge consecutive identical text when timestamps are touching/overlapping.
            if text == prev["text"] and start <= (prev["end"] + 0.20):
                prev["end"] = max(prev["end"], end)
                continue

            # Shift start forward a bit if it overlaps previous segment.
            if start < prev["end"]:
                start = prev["end"] + 0.01
                if end <= start:
                    end = start + 0.5

        normalized.append({"start": start, "end": end, "text": text})

    return normalized


def generate_subtitle(video_file, subtitle_file, max_chars_per_line=30, model=None):
    """
    Generate subtitle file using Faster-Whisper for the given video.
    Auto-detects the spoken language. Returns (success, detected_language).
    """
    try:
        from faster_whisper import WhisperModel

        if model is None:
            print(f"  Loading Faster-Whisper model '{WHISPER_MODEL}'...")
            print(f"  (If this is first time, downloading ~{get_model_size(WHISPER_MODEL)}...)")
            model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

        print("  ✅ Model loaded. Transcribing audio (4-5x faster than standard Whisper)...")
        # Let Whisper auto-detect language instead of hardcoding "id"
        segments, info = model.transcribe(video_file)
        detected_language = (info.language or "en").strip().lower()
        print(f"  Detected language: {detected_language}")
        normalized_segments = _normalize_subtitle_segments(list(segments))

        # Split long entries to prevent wall-of-text on screen
        print("  Splitting long subtitle entries...")
        split_segments = []
        for seg in normalized_segments:
            split_segments.extend(_split_subtitle_segment(seg))
        normalized_segments = split_segments

        # Generate SRT format
        print("  Generating subtitle file...")
        with open(subtitle_file, "w", encoding="utf-8") as f:
            for i, segment in enumerate(normalized_segments, start=1):
                start_time = format_timestamp(segment["start"])
                end_time = format_timestamp(segment["end"])
                text = wrap_subtitle_text(segment["text"], max_chars_per_line)

                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")

        return True, detected_language
    except Exception as e:
        print(f"  Failed to generate subtitle: {str(e)}")
        return False, "en"


def format_timestamp(seconds):
    """
    Convert seconds to SRT timestamp format (HH:MM:SS,mmm)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def process_single_clip(
    video_id,
    item,
    index,
    total_duration,
    crop_mode="default",
    use_subtitle=False,
    use_source_tag=False,
    source_channel="Unknown Channel",
    source_interval=SOURCE_TAG_DEFAULT_INTERVAL,
    subtitle_style="modern",
    source_style="classic",
    video_quality="medium",
    video_title=None,
    subtitle_font_size=11,
    subtitle_bottom_margin=26,
    subtitle_max_chars=24,
    source_tag_scale=0.88,
    source_tag_position="top-right",
    progress_callback=None,
    translate_subtitle=False,
    translate_target="id",
    whisper_model=None,
):
    """
    Download, crop, and export a single vertical clip
    based on a heatmap segment.

    Args:
        crop_mode: "default", "split_left", "split_right", or "blur_center"
        use_subtitle: whether to generate and burn subtitle
        use_source_tag: whether to add animated source tag overlay
        source_channel: channel name used in source tag
        source_interval: seconds between source tag animations
        subtitle_style: preset key from SUBTITLE_STYLES
        source_style: preset key from SOURCE_TAG_STYLES
        video_quality: preset key from VIDEO_QUALITY_PRESETS
        video_title: custom title for output filename (sanitized)
        subtitle_font_size: per-job subtitle size override (px)
        subtitle_bottom_margin: distance from bottom (px)
        subtitle_max_chars: max chars per subtitle line
        source_tag_scale: source tag size multiplier
        source_tag_position: source tag corner position
        progress_callback: optional callback function(progress_percent, message) for live updates
        translate_subtitle: whether to translate the subtitle to another language
        translate_target: target language code for translation ("id" or "en")
    """
    def report_progress(percent, message):
        if progress_callback:
            try:
                progress_callback(percent, message)
            except Exception:
                pass  # Ignore callback errors
    start_original = item["start"]
    end_original = item["start"] + item["duration"]

    start = max(0, start_original - PADDING)
    end = min(end_original + PADDING, total_duration)

    # Ensure resulting clip is at least MIN_DURATION when timeline allows.
    min_dur = max(1.0, float(MIN_DURATION))
    max_dur = max(1.0, float(MAX_DURATION))
    if min_dur > max_dur:
        min_dur = max_dur

    current_len = end - start
    if current_len < min_dur:
        need = min_dur - current_len
        extend_before = min(start, need / 2)
        start -= extend_before
        need -= extend_before

        extend_after = min(total_duration - end, need)
        end += extend_after
        need -= extend_after

        if need > 0:
            extra_before = min(start, need)
            start -= extra_before
            need -= extra_before

        if need > 0:
            extra_after = min(total_duration - end, need)
            end += extra_after

    if end - start < 3:
        return False

    # Resolve quality preset
    quality = VIDEO_QUALITY_PRESETS.get(video_quality, VIDEO_QUALITY_PRESETS["medium"])
    q_crf = str(quality["crf"])
    q_preset = quality["preset"]

    # Build output filename
    if video_title:
        safe_title = sanitize_filename(video_title)
        base_name = f"{safe_title}_clip_{index}"
    else:
        base_name = f"clip_{index}"

    uid = uuid.uuid4().hex[:8]
    temp_base = f"temp_{index}_{uid}"
    cropped_file = f"temp_cropped_{index}_{uid}.mp4"
    source_file = f"temp_source_{index}_{uid}.mp4"
    masked_file = f"temp_masked_{index}_{uid}.mp4"
    subtitle_file = f"temp_{index}_{uid}.srt"
    translated_subtitle_file = f"temp_{index}_{uid}_translated.srt"
    output_file = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")
    raw_subtitle_output = os.path.join(OUTPUT_DIR, f"{base_name}.srt")
    raw_translated_subtitle_output = os.path.join(OUTPUT_DIR, f"{base_name}_{translate_target}.srt")

    print(
        f"[Clip {index}] Processing segment "
        f"({int(start)}s - {int(end)}s, padding {PADDING}s)"
    )

    # Step 1: Download video segment (with retry)
    report_progress(10, "Downloading video segment...")
    download_file = None
    try:
        download_file = download_video_segment(video_id, start, end, temp_base)
        if not download_file or not os.path.exists(download_file):
            print("Failed to download video segment.")
            report_progress(0, "Download failed")
            return False
        report_progress(25, "Video downloaded successfully")

        # Step 2: Crop video
        report_progress(35, "Cropping video...")

        if crop_mode == "default":
            vf = "scale=-2:1280,crop=720:1280:(iw-720)/2:(ih-1280)/2"
        elif crop_mode == "split_left":
            vf = (
                f"scale=-2:1280[scaled];"
                f"[scaled]split=2[s1][s2];"
                f"[s1]crop=720:{TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
                f"[s2]crop=720:{BOTTOM_HEIGHT}:0:ih-{BOTTOM_HEIGHT}[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
        elif crop_mode == "split_right":
            vf = (
                f"scale=-2:1280[scaled];"
                f"[scaled]split=2[s1][s2];"
                f"[s1]crop=720:{TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
                f"[s2]crop=720:{BOTTOM_HEIGHT}:iw-720:ih-{BOTTOM_HEIGHT}[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
        elif crop_mode == "blur_center":
            vf = (
                "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280,boxblur=20:10[bg];"
                "[0:v]setsar=1,scale=720:405[fg];"
                "[bg][fg]overlay=0:(H-h)/2[out]"
            )
        else:
            vf = "scale=-2:1280,crop=720:1280:(iw-720)/2:(ih-1280)/2"

        # Build FFmpeg crop command according to mode
        # Semicolons indicate a multi-input filtergraph that requires -filter_complex.
        if ";" in vf:
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", download_file,
                "-filter_complex", vf,
                "-map", "[out]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", q_preset,
                "-crf", q_crf,
                "-c:a", "aac", "-b:a", "128k",
                cropped_file,
            ]
        else:
            # Standard single-stream crop: just -vf and output codecs
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", download_file,
                "-vf", vf,
                "-c:v", "libx264",
                "-preset", q_preset,
                "-crf", q_crf,
                "-c:a", "aac", "-b:a", "128k",
                cropped_file,
            ]

        try:
            subprocess.run(cmd_crop, check=True, capture_output=True, text=True)
            report_progress(50, "Video cropped successfully")
        except subprocess.CalledProcessError as e:
            print(f"Crop failed: {e.stderr}")
            report_progress(0, "Crop failed")
            return False

        if download_file and os.path.exists(download_file):
            os.remove(download_file)
        _cleanup_temp_download(temp_base)
        final_input_file = cropped_file

        if use_source_tag:
            report_progress(55, "Adding animated source tag...")
            source_filter = build_source_tag_filter(
                source_channel,
                source_interval,
                style=source_style,
                scale=source_tag_scale,
                position=source_tag_position,
            )
            cmd_source = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", cropped_file,
                "-vf", source_filter,
                "-c:v", "libx264", "-preset", q_preset, "-crf", q_crf,
                "-c:a", "copy",
                source_file
            ]

            try:
                subprocess.run(cmd_source, check=True, capture_output=True, text=True)
                report_progress(60, "Source tag added")
            except subprocess.CalledProcessError:
                print("  Failed to add source tag, continuing without...")
                report_progress(60, "Source tag skipped")

            os.remove(cropped_file)
            final_input_file = source_file

        # Mask hardcoded source subtitles when enabled (independent of AI subtitle)
        if MASK_BUILTIN_SUBTITLE:
            report_progress(62, "Applying subtitle mask...")
            mask_ratio = min(max(BUILTIN_SUBTITLE_MASK_HEIGHT_RATIO, 0.05), 0.45)
            mask_filter = (
                f"drawbox=x=0:y=ih*(1-{mask_ratio:.4f}):"
                f"w=iw:h=ih*{mask_ratio:.4f}:"
                f"color={BUILTIN_SUBTITLE_MASK_COLOR}:t=fill"
            )
            cmd_mask = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", final_input_file,
                "-vf", mask_filter,
                "-c:v", "libx264", "-preset", q_preset, "-crf", q_crf,
                "-c:a", "copy",
                masked_file,
            ]

            try:
                subprocess.run(cmd_mask, check=True, capture_output=True, text=True)
                if os.path.exists(final_input_file):
                    os.remove(final_input_file)
                final_input_file = masked_file
                report_progress(65, "Subtitle mask applied")
            except subprocess.CalledProcessError:
                print("  Failed to apply subtitle mask, continuing without mask...")
                report_progress(65, "Subtitle mask skipped")

        # Generate and burn subtitle if enabled
        if use_subtitle:
            report_progress(67, "Generating subtitle with AI...")
            sub_success, detected_lang = generate_subtitle(
                final_input_file, subtitle_file, max_chars_per_line=subtitle_max_chars, model=whisper_model
            )
            if sub_success:
                report_progress(80, f"Subtitle generated (detected: {detected_lang})")

                # Determine which SRT to burn: original or translated
                srt_to_burn = subtitle_file
                translated_ok = False

                if translate_subtitle:
                    report_progress(82, "Installing translation packages...")
                    install_translation_packages()

                    if detected_lang == translate_target:
                        print(f"  Source language ({detected_lang}) same as target, skipping translation.")
                    else:
                        report_progress(84, f"Translating subtitle {detected_lang} → {translate_target}...")
                        translated_ok, _ = translate_srt_file(
                            subtitle_file, translated_subtitle_file, translate_target, detected_lang
                        )
                        if translated_ok:
                            srt_to_burn = translated_subtitle_file
                            report_progress(86, "Subtitle translated")
                        else:
                            report_progress(86, "Translation failed, using original subtitle")

                # Save raw subtitle(s)
                if SAVE_RAW_SUBTITLE and os.path.exists(subtitle_file):
                    try:
                        shutil.copy2(subtitle_file, raw_subtitle_output)
                        print(f"  Raw subtitle saved: {raw_subtitle_output}")
                    except Exception as copy_error:
                        print(f"  Failed to save raw subtitle: {str(copy_error)}")

                if translated_ok and os.path.exists(translated_subtitle_file):
                    try:
                        shutil.copy2(translated_subtitle_file, raw_translated_subtitle_output)
                        print(f"  Translated subtitle saved: {raw_translated_subtitle_output}")
                    except Exception as copy_error:
                        print(f"  Failed to save translated subtitle: {str(copy_error)}")

                report_progress(88, "Burning subtitle to video...")
                # Use the relative temp file name directly; it is guaranteed safe
                # because we control the filename (no spaces or special chars).
                subtitle_path = srt_to_burn.replace("\\", "/").replace(":", "\\:")

                sub_force_style = build_subtitle_force_style(
                    subtitle_style,
                    font_size=subtitle_font_size,
                    bottom_margin=subtitle_bottom_margin,
                )

                cmd_subtitle = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", final_input_file,
                    "-vf", f"subtitles='{subtitle_path}':force_style='{sub_force_style}'",
                    "-c:v", "libx264", "-preset", q_preset, "-crf", q_crf,
                    "-c:a", "copy",
                    output_file
                ]

                try:
                    subprocess.run(cmd_subtitle, check=True, capture_output=True, text=True)
                    report_progress(95, "Subtitle burned")
                    os.remove(final_input_file)
                except subprocess.CalledProcessError:
                    print("  Failed to burn subtitle, continuing with non-burned video...")
                    report_progress(95, "Subtitle burn failed, using raw video")
                    os.rename(final_input_file, output_file)

                # Cleanup temp subtitle files
                for f in [subtitle_file, translated_subtitle_file]:
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                        except Exception:
                            pass
            else:
                print("  Subtitle generation failed, continuing without subtitle...")
                report_progress(95, "Subtitle generation failed")
                os.rename(final_input_file, output_file)
        else:
            report_progress(90, "Finalizing video...")
            os.rename(final_input_file, output_file)

        report_progress(100, "Clip successfully generated!")
        print("Clip successfully generated.")
        return True

    except subprocess.CalledProcessError as e:
        # Cleanup temp files
        _cleanup_temp_download(temp_base)
        for f in [cropped_file, source_file, masked_file, subtitle_file, translated_subtitle_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        print(f"Failed to generate this clip.")
        print(f"Error details: {e.stderr if e.stderr else e.stdout}")
        return False
    except RuntimeError:
        # Re-raise bot-check / auth errors so the caller can stop processing
        # subsequent clips rather than wasting time on repeated failures.
        raise
    except Exception as e:
        # Cleanup temp files
        _cleanup_temp_download(temp_base)
        for f in [cropped_file, source_file, masked_file, subtitle_file, translated_subtitle_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        print(f"Failed to generate this clip.")
        print(f"Error: {str(e)}")
        return False


def main():
    """
    Main entry point of the application.
    """
    # Select crop mode
    print("\n=== Crop Mode ===")
    print("1. Default (center crop)")
    print("2. Split 1 (top: center, bottom: bottom-left (facecam))")
    print("3. Split 2 (top: center, bottom: bottom-right (facecam))")
    print("4. Blur Center (16:9 center with blurred top/bottom)")

    while True:
        choice = input("\nSelect crop mode (1-4): ").strip()
        if choice == "1":
            crop_mode = "default"
            crop_desc = "Default center crop"
            break
        elif choice == "2":
            crop_mode = "split_left"
            crop_desc = "Split crop (bottom-left facecam)"
            break
        elif choice == "3":
            crop_mode = "split_right"
            crop_desc = "Split crop (bottom-right facecam)"
            break
        elif choice == "4":
            crop_mode = "blur_center"
            crop_desc = "Blur center (16:9 center with blurred top/bottom)"
            break
        else:
            print("Invalid choice. Please enter 1, 2, 3, or 4.")

    print(f"Selected: {crop_desc}")

    # Ask for video quality
    print("\n=== Video Quality ===")
    for key, preset in VIDEO_QUALITY_PRESETS.items():
        print(f"{key}. {preset['label']}")
    quality_choice = input("Select quality preset (default medium): ").strip().lower()
    video_quality = quality_choice if quality_choice in VIDEO_QUALITY_PRESETS else "medium"
    print(f"Selected quality: {VIDEO_QUALITY_PRESETS[video_quality]['label']}")

    # Ask for source tag overlay
    print("\n=== Source Tag Overlay ===")
    source_choice = input("Show animated source label (YouTube + channel)? (y/n): ").strip().lower()
    use_source_tag = source_choice in ["y", "yes"]
    source_interval = SOURCE_TAG_DEFAULT_INTERVAL
    source_style = "classic"

    if use_source_tag:
        interval_input = input(
            f"Animation interval in seconds (default {SOURCE_TAG_DEFAULT_INTERVAL:.0f}): "
        ).strip()
        if interval_input:
            try:
                source_interval = max(4.0, float(interval_input))
            except ValueError:
                source_interval = SOURCE_TAG_DEFAULT_INTERVAL

        print("\nAvailable source tag styles: " + ", ".join(SOURCE_TAG_STYLES.keys()))
        style_input = input("Select source tag style (default classic): ").strip().lower()
        if style_input in SOURCE_TAG_STYLES:
            source_style = style_input

        print(f"✅ Source tag enabled (interval: {source_interval:.1f}s, style: {source_style})")
    else:
        print("❌ Source tag disabled")

    # Ask for subtitle
    print("\n=== Auto Subtitle ===")
    print(f"Available model: {WHISPER_MODEL} (~{get_model_size(WHISPER_MODEL)})")
    subtitle_choice = input("Add auto subtitle using Faster-Whisper? (y/n): ").strip().lower()
    use_subtitle = subtitle_choice in ["y", "yes"]
    subtitle_style = "modern"
    translate_subtitle = False
    translate_target = "id"

    if use_subtitle:
        print("\nAvailable subtitle styles: " + ", ".join(SUBTITLE_STYLES.keys()))
        style_input = input("Select subtitle style (default modern): ").strip().lower()
        if style_input in SUBTITLE_STYLES:
            subtitle_style = style_input

        trans_choice = input("Translate subtitle? (y/n): ").strip().lower()
        translate_subtitle = trans_choice in ["y", "yes"]
        if translate_subtitle:
            target_input = input("Target language code (default id): ").strip().lower()
            if target_input:
                translate_target = target_input

        print(f"✅ Subtitle enabled (style: {subtitle_style}, translate: {translate_subtitle})")
    else:
        print("❌ Subtitle disabled")

    # Ask for overlay preset
    print("\n=== Overlay Preset ===")
    for key, preset in OVERLAY_PRESETS.items():
        print(f"{key}. {preset['label']}")
    overlay_choice = input(f"Select overlay preset (default {DEFAULT_OVERLAY_PRESET}): ").strip().lower()
    overlay_preset = OVERLAY_PRESETS.get(overlay_choice, OVERLAY_PRESETS[DEFAULT_OVERLAY_PRESET])
    print(f"Selected overlay: {overlay_preset['label']}")

    print()

    # Check dependencies
    check_dependencies(install_whisper=use_subtitle)

    link = input("YouTube Link: ").strip()
    video_id = extract_video_id(link)

    if not video_id:
        print("Invalid YouTube link.")
        return

    print("Reading video metadata...")
    metadata = get_video_metadata(video_id)

    available, reason = check_video_availability(video_id, metadata)
    if not available:
        print(f"❌ Video unavailable: {reason}")
        return

    source_channel = "Unknown Channel"
    if use_source_tag:
        source_channel = get_channel_name_from_metadata(metadata)
        if source_channel == "Unknown Channel" and metadata is None:
            print("Channel metadata unavailable.")
        print(f"Source label channel: {source_channel}")

    # Extract duration from cached metadata; avoid redundant yt-dlp call when possible.
    total_duration = get_duration_from_metadata(metadata)
    if total_duration is None:
        print("  Metadata lacks duration, fetching with yt-dlp...")
        total_duration = get_duration(video_id)

    # Polite delay to avoid hammering YouTube between metadata and heatmap calls.
    time.sleep(1.5)

    heatmap_data = fetch_most_replayed(video_id)

    if not heatmap_data:
        heatmap_data = fetch_fallback_segments(video_id, total_duration, metadata)

    if not heatmap_data:
        print("No high-engagement segments found and fallback also failed.")
        return

    print(f"Found {len(heatmap_data)} high-engagement segments.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(
        f"Processing clips with {PADDING}s pre-padding "
        f"and {PADDING}s post-padding."
    )
    print(f"Clip duration target: min {MIN_DURATION}s, max {MAX_DURATION}s")
    print(f"Using crop mode: {crop_desc}")

    # Load Whisper model once if needed
    whisper_model = None
    if use_subtitle:
        try:
            from faster_whisper import WhisperModel
            print(f"Pre-loading Whisper model '{WHISPER_MODEL}'...")
            whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            print("✅ Whisper model ready.")
        except Exception as e:
            print(f"⚠️  Failed to preload Whisper model: {e}")
            whisper_model = None

    success_count = 0

    for idx, item in enumerate(heatmap_data):
        if success_count >= MAX_CLIPS:
            break

        # Delay between clips to avoid YouTube rate-limiting.
        if idx > 0 and INTER_CLIP_DELAY > 0:
            time.sleep(INTER_CLIP_DELAY)

        try:
            ok = process_single_clip(
                video_id,
                item,
                success_count + 1,
                total_duration,
                crop_mode=crop_mode,
                use_subtitle=use_subtitle,
                use_source_tag=use_source_tag,
                source_channel=source_channel,
                source_interval=source_interval,
                subtitle_style=subtitle_style,
                source_style=source_style,
                video_quality=video_quality,
                subtitle_font_size=overlay_preset["subtitle_font_size"],
                subtitle_bottom_margin=overlay_preset["subtitle_bottom_margin"],
                subtitle_max_chars=overlay_preset["subtitle_max_chars"],
                source_tag_scale=overlay_preset["source_tag_scale"],
                source_tag_position=overlay_preset["source_tag_position"],
                progress_callback=None,
                translate_subtitle=translate_subtitle,
                translate_target=translate_target,
                whisper_model=whisper_model,
            )
        except RuntimeError as exc:
            err_msg = str(exc)
            if "bot check" in err_msg.lower() or "sign in" in err_msg.lower() or "cookies" in err_msg.lower():
                print(f"\n⚠️  Stopped early: {err_msg}")
                break
            raise

        if ok:
            success_count += 1

    print(
        f"Finished processing. "
        f"{success_count} clip(s) successfully saved to '{OUTPUT_DIR}'."
    )


if __name__ == "__main__":
    main()