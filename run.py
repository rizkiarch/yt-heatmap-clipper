import os
import re
import json
import sys
import subprocess
import requests
import shutil
from urllib.parse import urlparse, parse_qs
import warnings
warnings.filterwarnings("ignore")

OUTPUT_DIR = "clips"      # Directory where generated clips will be saved
MAX_DURATION = 160         # Maximum duration (in seconds) for each clip
MIN_DURATION = 60          # Minimum duration (in seconds) for each clip
MIN_SCORE = 0.30          # Minimum heatmap intensity score to be considered viral
MAX_CLIPS = 21           # Maximum number of clips to generate per video
MAX_WORKERS = 1           # Number of parallel workers (reserved for future concurrency)
PADDING = 10              # Extra seconds added before and after each detected segment
TOP_HEIGHT = 960          # Height for top section (center content) in split mode
BOTTOM_HEIGHT = 320       # Height for bottom section (facecam) in split mode (Total: 1280px)
USE_SUBTITLE = True       # Enable auto subtitle using Faster-Whisper (4-5x faster)
WHISPER_MODEL = "large-v3"   # Whisper model size: tiny, base, small, medium, large-v3
SAVE_RAW_SUBTITLE = True  # Save generated .srt subtitle file alongside output clip
SOURCE_TAG_DEFAULT_INTERVAL = 30.0  # Seconds between each source tag animation cycle


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


def cek_dependensi(install_whisper=False, update_ytdlp=True):
    """
    Ensure required dependencies are available.
    Automatically updates yt-dlp and checks FFmpeg availability.
    """
    if update_ytdlp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    if install_whisper:
        # Check if faster-whisper package is installed
        try:
            import faster_whisper
            print(f"✅ Faster-Whisper package installed.")
            
            # Check if selected model is cached
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
                stderr=subprocess.DEVNULL
            )
            print(f"✅ Faster-Whisper package installed successfully.")
            print(f"⚠️  Model '{WHISPER_MODEL}' (~{get_model_size(WHISPER_MODEL)}) will be downloaded on first use.\n")

    if not shutil.which("ffmpeg"):
        print("FFmpeg not found. Please install FFmpeg and ensure it is in PATH.")
        sys.exit(1)


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


def ambil_most_replayed(video_id):
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

    try:
        response = requests.get(url, headers=headers, timeout=20)
        html = response.text
    except Exception:
        print("Failed to fetch YouTube page.")
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


def ambil_fallback_segments(video_id, total_duration, metadata=None):
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


def get_duration(video_id):
    """
    Retrieve the total duration of a YouTube video in seconds.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--get-duration",
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
    except Exception:
        pass

    return 3600


def get_video_metadata(video_id):
    """
    Retrieve yt-dlp JSON metadata once so it can be reused.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--skip-download",
        "-J",
        f"https://youtu.be/{video_id}"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception:
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


def build_source_tag_filter(channel_name, interval_seconds):
    """
    Build FFmpeg filter that shows animated source tag on top-left.
    """
    interval = max(4.0, float(interval_seconds))
    channel = _escape_drawtext_text(channel_name)

    # Smooth slide-in/slide-out timing per cycle:
    # 0.00-0.42s in, 0.42-2.40s hold, 2.40-2.82s out.
    x_expr = (
        f"if(lt(mod(t\\,{interval:.2f})\\,0.42)\\,"
        f"-440+464*sin((mod(t\\,{interval:.2f})/0.42)*PI/2)\\,"
        f"if(lt(mod(t\\,{interval:.2f})\\,2.40)\\,24\\,"
        f"if(lt(mod(t\\,{interval:.2f})\\,2.82)\\,"
        f"24-464*sin(((mod(t\\,{interval:.2f})-2.40)/0.42)*PI/2)\\,-440)))"
    )

    return (
        "format=yuv420p,"
        f"drawbox=x='{x_expr}':y=56:w=5:h=70:color=red@0.95:t=fill,"
        f"drawbox=x='{x_expr}+10':y=52:w=425:h=78:color=black@0.42:t=fill,"
        f"drawbox=x='{x_expr}+24':y=74:w=32:h=32:color=red@0.95:t=fill,"
        f"drawtext=text='>':x='{x_expr}+35':y=78:fontsize=24:fontcolor=white,"
        f"drawtext=text='YouTube':x='{x_expr}+66':y=79:fontsize=18:fontcolor=white,"
        f"drawtext=text='Source\\: {channel}':x='{x_expr}+24':y=108:fontsize=20:fontcolor=white"
    )


def generate_subtitle(video_file, subtitle_file):
    """
    Generate subtitle file using Faster-Whisper for the given video.
    Returns True if successful, False otherwise.
    """
    try:
        from faster_whisper import WhisperModel
        
        print(f"  Loading Faster-Whisper model '{WHISPER_MODEL}'...")
        print(f"  (If this is first time, downloading ~{get_model_size(WHISPER_MODEL)}...)")
        # Use int8 for CPU efficiency, or "float16" for GPU
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        
        print("  ✅ Model loaded. Transcribing audio (4-5x faster than standard Whisper)...")
        segments, info = model.transcribe(video_file, language="id")
        
        # Generate SRT format
        print("  Generating subtitle file...")
        with open(subtitle_file, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                text = segment.text.strip()
                
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")
        
        return True
    except Exception as e:
        print(f"  Failed to generate subtitle: {str(e)}")
        return False


def format_timestamp(seconds):
    """
    Convert seconds to SRT timestamp format (HH:MM:SS,mmm)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def proses_satu_clip(
    video_id,
    item,
    index,
    total_duration,
    crop_mode="default",
    use_subtitle=False,
    use_source_tag=False,
    source_channel="Unknown Channel",
    source_interval=SOURCE_TAG_DEFAULT_INTERVAL
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
    """
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

    temp_file = f"temp_{index}.mp4"
    cropped_file = f"temp_cropped_{index}.mp4"
    source_file = f"temp_source_{index}.mp4"
    subtitle_file = f"temp_{index}.srt"
    output_file = os.path.join(OUTPUT_DIR, f"clip_{index}.mp4")
    raw_subtitle_output = os.path.join(OUTPUT_DIR, f"clip_{index}.srt")

    print(
        f"[Clip {index}] Processing segment "
        f"({int(start)}s - {int(end)}s, padding {PADDING}s)"
    )

    cmd_download = [
        sys.executable, "-m", "yt_dlp",
        "--force-ipv4",
        "--quiet", "--no-warnings",
        "--downloader", "ffmpeg",
        "--downloader-args",
        f"ffmpeg_i:-ss {start} -to {end} -hide_banner -loglevel error",
        "-f",
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "-o", temp_file,
        f"https://youtu.be/{video_id}"
    ]

    try:
        result = subprocess.run(
            cmd_download,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if not os.path.exists(temp_file):
            print("Failed to download video segment.")
            return False

        # Build video filter based on crop_mode
        # First, crop the video to cropped_file
        if crop_mode == "default":
            # Standard center crop - ambil dari tengah video
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", temp_file,
                "-vf", "scale=-2:1280,crop=720:1280:(iw-720)/2:(ih-1280)/2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k",
                cropped_file
            ]
        elif crop_mode == "split_left":
            # Split crop: 
            # - Top: konten game dari tengah-tengah video (960px)
            # - Bottom: facecam dari kiri bawah video asli (320px)
            vf = (
                f"scale=-2:1280[scaled];"
                f"[scaled]split=2[s1][s2];"
                f"[s1]crop=720:{TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
                f"[s2]crop=720:{BOTTOM_HEIGHT}:0:ih-{BOTTOM_HEIGHT}[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", temp_file,
                "-filter_complex", vf,
                "-map", "[out]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k",
                cropped_file
            ]
        elif crop_mode == "split_right":
            # Split crop: 
            # - Top: konten game dari tengah-tengah video (960px)
            # - Bottom: facecam dari kanan bawah video asli (320px)
            vf = (
                f"scale=-2:1280[scaled];"
                f"[scaled]split=2[s1][s2];"
                f"[s1]crop=720:{TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
                f"[s2]crop=720:{BOTTOM_HEIGHT}:iw-720:ih-{BOTTOM_HEIGHT}[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", temp_file,
                "-filter_complex", vf,
                "-map", "[out]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k",
                cropped_file
            ]
        elif crop_mode == "blur_center":
            # Keep the original 16:9 frame in the middle and fill top/bottom with blurred video.
            vf = (
                "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280,boxblur=20:10[bg];"
                "[0:v]setsar=1,scale=720:405[fg];"
                "[bg][fg]overlay=0:(H-h)/2[out]"
            )
            cmd_crop = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", temp_file,
                "-filter_complex", vf,
                "-map", "[out]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k",
                cropped_file
            ]

        print("  Cropping video...")
        result = subprocess.run(
            cmd_crop,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        os.remove(temp_file)

        final_input_file = cropped_file

        if use_source_tag:
            print("  Adding animated source tag...")
            source_filter = build_source_tag_filter(source_channel, source_interval)
            cmd_source = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", cropped_file,
                "-vf", source_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "copy",
                source_file
            ]

            result = subprocess.run(
                cmd_source,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            os.remove(cropped_file)
            final_input_file = source_file

        # Generate and burn subtitle if enabled
        if use_subtitle:
            print("  Generating subtitle...")
            if generate_subtitle(final_input_file, subtitle_file):
                if SAVE_RAW_SUBTITLE and os.path.exists(subtitle_file):
                    try:
                        # Keep a permanent raw subtitle copy before burn step.
                        shutil.copy2(subtitle_file, raw_subtitle_output)
                        print(f"  Raw subtitle saved: {raw_subtitle_output}")
                    except Exception as copy_error:
                        print(f"  Failed to save raw subtitle: {str(copy_error)}")

                print("  Burning subtitle to video...")
                # Get absolute path for subtitle file
                abs_subtitle_path = os.path.abspath(subtitle_file)
                # Escape for FFmpeg: replace \ with / and escape special chars
                subtitle_path = abs_subtitle_path.replace("\\", "/").replace(":", "\\:")
                
                cmd_subtitle = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", final_input_file,
                    "-vf", f"subtitles='{subtitle_path}':force_style='FontName=Arial,FontSize=12,Bold=1,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=40'",
                    # "-vf", f"subtitles='{subtitle_path}':force_style='FontName=Arial,FontSize=12,Bold=1,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=100'",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                    "-c:a", "copy",
                    output_file
                ]
                
                try:
                    result = subprocess.run(
                        cmd_subtitle,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    os.remove(final_input_file)
                except subprocess.CalledProcessError:
                    # If subtitle burning fails, keep processing with video only.
                    print("  Failed to burn subtitle, continuing with non-burned video...")
                    os.rename(final_input_file, output_file)

                if os.path.exists(subtitle_file):
                    os.remove(subtitle_file)
            else:
                # If subtitle generation failed, use cropped file as output
                print("  Subtitle generation failed, continuing without subtitle...")
                os.rename(final_input_file, output_file)
        else:
            # No subtitle, rename cropped file to output
            os.rename(final_input_file, output_file)

        print("Clip successfully generated.")
        return True

    except subprocess.CalledProcessError as e:
        # Cleanup temp files
        for f in [temp_file, cropped_file, source_file, subtitle_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        print(f"Failed to generate this clip.")
        print(f"Error details: {e.stderr if e.stderr else e.stdout}")
        return False
    except Exception as e:
        # Cleanup temp files
        for f in [temp_file, cropped_file, source_file, subtitle_file]:
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
    print("4. Blur Center (16:9 di tengah, atas-bawah blur)")
    
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

    # Ask for source tag overlay
    print("\n=== Source Tag Overlay ===")
    source_choice = input("Show animated source label (YouTube + channel) ? (y/n): ").strip().lower()
    use_source_tag = source_choice in ["y", "yes"]
    source_interval = SOURCE_TAG_DEFAULT_INTERVAL

    if use_source_tag:
        interval_input = input(
            f"Animation interval in seconds (default {SOURCE_TAG_DEFAULT_INTERVAL:.0f}): "
        ).strip()
        if interval_input:
            try:
                source_interval = max(4.0, float(interval_input))
            except ValueError:
                source_interval = SOURCE_TAG_DEFAULT_INTERVAL

        print(f"✅ Source tag enabled (interval: {source_interval:.1f}s)")
    else:
        print("❌ Source tag disabled")
    
    # Ask for subtitle
    print("\n=== Auto Subtitle ===")
    print(f"Available model: {WHISPER_MODEL} (~{get_model_size(WHISPER_MODEL)})")
    subtitle_choice = input("Add auto subtitle using Faster-Whisper? (y/n): ").strip().lower()
    use_subtitle = subtitle_choice in ["y", "yes"]
    
    if use_subtitle:
        print(f"✅ Subtitle enabled (Model: {WHISPER_MODEL}, Bahasa Indonesia)")
    else:
        print("❌ Subtitle disabled")
    
    print()
    
    # Check dependencies
    cek_dependensi(install_whisper=use_subtitle)

    link = input("Link YT: ").strip()
    video_id = extract_video_id(link)

    if not video_id:
        print("Invalid YouTube link.")
        return

    print("Reading video metadata...")
    metadata = get_video_metadata(video_id)

    source_channel = "Unknown Channel"
    if use_source_tag:
        source_channel = get_channel_name_from_metadata(metadata)
        if source_channel == "Unknown Channel":
            print("Channel metadata incomplete, trying fallback lookup...")
            source_channel = get_channel_name(video_id)
        print(f"Source label channel: {source_channel}")

    total_duration = get_duration_from_metadata(metadata) or get_duration(video_id)
    heatmap_data = ambil_most_replayed(video_id)

    if not heatmap_data:
        heatmap_data = ambil_fallback_segments(video_id, total_duration, metadata)

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

    success_count = 0

    for item in heatmap_data:
        if success_count >= MAX_CLIPS:
            break

        if proses_satu_clip(
            video_id,
            item,
            success_count + 1,
            total_duration,
            crop_mode,
            use_subtitle,
            use_source_tag,
            source_channel,
            source_interval
        ):
            success_count += 1

    print(
        f"Finished processing. "
        f"{success_count} clip(s) successfully saved to '{OUTPUT_DIR}'."
    )


if __name__ == "__main__":
    main()