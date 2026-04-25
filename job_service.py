import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr

import run as clipper

DB_FILE = os.path.join(clipper.OUTPUT_DIR, "jobs.db")
MANIFEST_FILE = os.path.join(clipper.OUTPUT_DIR, "manifest.json")

_MANIFEST_LOCK = threading.Lock()


def _connect():
    os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_job_db():
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                message TEXT,
                error TEXT,
                result_json TEXT,
                payload_json TEXT NOT NULL,
                logs TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_job(payload):
    job_id = str(uuid.uuid4())
    now = time.time()

    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, status, progress, message, error, result_json,
                payload_json, logs, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "queued",
                0.0,
                "Queued",
                "",
                "",
                json.dumps(payload, ensure_ascii=False),
                "",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return job_id


def update_job(job_id, **fields):
    if not fields:
        return

    fields["updated_at"] = time.time()

    assignments = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values())
    values.append(job_id)

    conn = _connect()
    try:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE job_id = ?", values)
        conn.commit()
    finally:
        conn.close()


def get_job(job_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    item = dict(row)
    payload_json = item.get("payload_json") or "{}"
    result_json = item.get("result_json") or "{}"

    try:
        item["payload"] = json.loads(payload_json)
    except Exception:
        item["payload"] = {}

    try:
        item["result"] = json.loads(result_json) if result_json else {}
    except Exception:
        item["result"] = {}

    item.pop("payload_json", None)
    item.pop("result_json", None)
    return item


def _load_manifest():
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def _save_manifest(data):
    os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _add_manifest_entry(entry):
    with _MANIFEST_LOCK:
        manifest = _load_manifest()
        manifest.append(entry)
        _save_manifest(manifest)


def build_history_entries():
    with _MANIFEST_LOCK:
        manifest = _load_manifest()

    result = []
    seen_filenames = set()
    for entry in reversed(manifest):
        filename = entry.get("filename", "")
        if not filename:
            continue
        if filename in seen_filenames:
            continue

        video_path = os.path.join(clipper.OUTPUT_DIR, filename)
        if not os.path.exists(video_path):
            continue

        srt_name = filename.rsplit(".", 1)[0] + ".srt"
        srt_path = os.path.join(clipper.OUTPUT_DIR, srt_name)
        subtitle_text = ""

        if os.path.exists(srt_path):
            try:
                with open(srt_path, "r", encoding="utf-8") as f:
                    subtitle_text = f.read()
            except Exception:
                subtitle_text = ""

        row = dict(entry)
        row["file_size"] = os.path.getsize(video_path)
        row["subtitle_filename"] = srt_name
        row["subtitle_text"] = subtitle_text
        result.append(row)
        seen_filenames.add(filename)

    return result


def delete_history_entry(filename):
    if not filename or ".." in filename or "/" in filename:
        return False, "Invalid filename"

    video_path = os.path.join(clipper.OUTPUT_DIR, filename)
    if not os.path.exists(video_path):
        return False, "File not found"

    srt_path = os.path.join(clipper.OUTPUT_DIR, filename.rsplit(".", 1)[0] + ".srt")

    if os.path.exists(video_path):
        os.remove(video_path)
    if os.path.exists(srt_path):
        os.remove(srt_path)

    with _MANIFEST_LOCK:
        manifest = _load_manifest()
        manifest = [x for x in manifest if x.get("filename") != filename]
        _save_manifest(manifest)

    return True, "Deleted"


def _next_available_filename(candidate):
    if not os.path.exists(os.path.join(clipper.OUTPUT_DIR, candidate)):
        return candidate

    base, ext = os.path.splitext(candidate)
    count = 2
    while True:
        alt = f"{base}_{count}{ext}"
        if not os.path.exists(os.path.join(clipper.OUTPUT_DIR, alt)):
            return alt
        count += 1


def rename_history_entry(filename, new_title):
    if not filename or ".." in filename or "/" in filename:
        return False, "Invalid filename", ""
    if not new_title or not str(new_title).strip():
        return False, "New title is required", ""
    if not filename.lower().endswith(".mp4"):
        return False, "Only .mp4 entries can be renamed", ""

    old_video_path = os.path.join(clipper.OUTPUT_DIR, filename)
    if not os.path.exists(old_video_path):
        return False, "File not found", ""

    safe_title = clipper.sanitize_filename(str(new_title).strip())
    if not safe_title:
        return False, "Invalid title after sanitization", ""

    old_base = filename[:-4]
    match = re.search(r"(_clip_\d+)$", old_base)
    clip_suffix = match.group(1) if match else "_clip_1"

    new_filename = f"{safe_title}{clip_suffix}.mp4"
    if new_filename != filename:
        new_filename = _next_available_filename(new_filename)

    new_video_path = os.path.join(clipper.OUTPUT_DIR, new_filename)

    old_srt = filename[:-4] + ".srt"
    new_srt = new_filename[:-4] + ".srt"
    old_srt_path = os.path.join(clipper.OUTPUT_DIR, old_srt)
    new_srt_path = os.path.join(clipper.OUTPUT_DIR, new_srt)

    try:
        if new_filename != filename:
            os.replace(old_video_path, new_video_path)
            if os.path.exists(old_srt_path):
                os.replace(old_srt_path, new_srt_path)

        with _MANIFEST_LOCK:
            manifest = _load_manifest()
            for entry in manifest:
                if entry.get("filename") == filename:
                    entry["filename"] = new_filename
                    entry["video_title"] = str(new_title).strip()
            _save_manifest(manifest)
    except Exception as exc:
        return False, str(exc), ""

    return True, "Renamed", new_filename


def _validate_job_payload(payload):
    overlay_preset = (payload.get("overlay_preset") or clipper.DEFAULT_OVERLAY_PRESET).strip().lower()
    if overlay_preset not in clipper.OVERLAY_PRESETS and overlay_preset != "custom":
        overlay_preset = clipper.DEFAULT_OVERLAY_PRESET
    fallback_key = overlay_preset if overlay_preset in clipper.OVERLAY_PRESETS else clipper.DEFAULT_OVERLAY_PRESET
    overlay_defaults = clipper.OVERLAY_PRESETS[fallback_key]

    data = {
        "url": (payload.get("url") or "").strip(),
        "crop_mode": payload.get("crop_mode") or "default",
        "use_subtitle": bool(payload.get("use_subtitle", True)),
        "use_source_tag": bool(payload.get("use_source_tag", False)),
        "subtitle_style": payload.get("subtitle_style") or "modern",
        "source_style": payload.get("source_style") or "classic",
        "video_quality": payload.get("video_quality") or "medium",
        "video_title": (payload.get("video_title") or "").strip(),
        "overlay_preset": overlay_preset,
        "subtitle_font_size": clipper.clamp_int(
            payload.get("subtitle_font_size", overlay_defaults["subtitle_font_size"]),
            9,
            24,
            overlay_defaults["subtitle_font_size"],
        ),
        "subtitle_bottom_margin": clipper.clamp_int(
            payload.get("subtitle_bottom_margin", overlay_defaults["subtitle_bottom_margin"]),
            8,
            120,
            overlay_defaults["subtitle_bottom_margin"],
        ),
        "subtitle_max_chars": clipper.clamp_int(
            payload.get("subtitle_max_chars", overlay_defaults["subtitle_max_chars"]),
            16,
            64,
            overlay_defaults["subtitle_max_chars"],
        ),
        "source_tag_scale": clipper.clamp_float(
            payload.get("source_tag_scale", overlay_defaults["source_tag_scale"]),
            0.60,
            1.60,
            overlay_defaults["source_tag_scale"],
        ),
        "source_tag_position": str(
            payload.get("source_tag_position", overlay_defaults["source_tag_position"])
        ).strip().lower(),
    }

    try:
        data["source_interval"] = max(4.0, float(payload.get("source_interval", 30)))
    except Exception:
        data["source_interval"] = clipper.SOURCE_TAG_DEFAULT_INTERVAL

    if data["crop_mode"] not in {"default", "split_left", "split_right", "blur_center"}:
        data["crop_mode"] = "default"
    if data["subtitle_style"] not in clipper.SUBTITLE_STYLES:
        data["subtitle_style"] = "modern"
    if data["source_style"] not in clipper.SOURCE_TAG_STYLES:
        data["source_style"] = "classic"
    if data["video_quality"] not in clipper.VIDEO_QUALITY_PRESETS:
        data["video_quality"] = "medium"
    if data["source_tag_position"] not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        data["source_tag_position"] = overlay_defaults["source_tag_position"]

    if not data["url"]:
        raise ValueError("YouTube URL is required")

    return data


def process_job(job_id, payload):
    """
    Process one job from payload and persist status/result.
    """
    buffer = io.StringIO()

    try:
        data = _validate_job_payload(payload)
        update_job(job_id, status="processing", progress=3.0, message="Checking dependencies", error="")

        with redirect_stdout(buffer), redirect_stderr(buffer):
            clipper.cek_dependensi(
                install_whisper=data["use_subtitle"],
                update_ytdlp=False,
            )

            video_id = clipper.extract_video_id(data["url"])
            if not video_id:
                raise ValueError("Invalid YouTube URL.")

            update_job(job_id, progress=8.0, message="Fetching video metadata")
            metadata = clipper.get_video_metadata(video_id)
            source_channel = (
                clipper.get_channel_name_from_metadata(metadata)
                if metadata else "Unknown Channel"
            )

            total_duration = (
                clipper.get_duration_from_metadata(metadata)
                if metadata else None
            ) or clipper.get_duration(video_id)

            update_job(job_id, progress=14.0, message="Reading heatmap data")
            heatmap_data = clipper.ambil_most_replayed(video_id)
            if not heatmap_data:
                heatmap_data = clipper.ambil_fallback_segments(video_id, total_duration, metadata)

            if not heatmap_data:
                raise RuntimeError("No high-engagement segments found and fallback also failed.")

            os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)

            title_for_output = data["video_title"]
            if not title_for_output and metadata:
                title_for_output = (metadata.get("title") or "").strip()

            generated_files = []
            success_count = 0
            target_count = min(len(heatmap_data), clipper.MAX_CLIPS)

            for item in heatmap_data:
                if success_count >= clipper.MAX_CLIPS:
                    break

                clip_index = success_count + 1
                ok = clipper.proses_satu_clip(
                    video_id,
                    item,
                    clip_index,
                    total_duration,
                    data["crop_mode"],
                    data["use_subtitle"],
                    data["use_source_tag"],
                    source_channel,
                    data["source_interval"],
                    data["subtitle_style"],
                    data["source_style"],
                    data["video_quality"],
                    title_for_output or None,
                    data["subtitle_font_size"],
                    data["subtitle_bottom_margin"],
                    data["subtitle_max_chars"],
                    data["source_tag_scale"],
                    data["source_tag_position"],
                )

                if ok:
                    success_count += 1
                    if title_for_output:
                        safe_title = clipper.sanitize_filename(title_for_output)
                        filename = f"{safe_title}_clip_{success_count}.mp4"
                    else:
                        filename = f"clip_{success_count}.mp4"

                    generated_files.append(filename)

                    _add_manifest_entry({
                        "job_id": job_id,
                        "filename": filename,
                        "source_url": data["url"],
                        "video_title": title_for_output or ((metadata or {}).get("title") or ""),
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "duration": item.get("duration", 0),
                        "crop_mode": data["crop_mode"],
                        "subtitle_style": data["subtitle_style"],
                        "source_style": data["source_style"],
                        "video_quality": data["video_quality"],
                        "overlay_preset": data["overlay_preset"],
                        "subtitle_font_size": data["subtitle_font_size"],
                        "subtitle_bottom_margin": data["subtitle_bottom_margin"],
                        "subtitle_max_chars": data["subtitle_max_chars"],
                        "source_tag_scale": data["source_tag_scale"],
                        "source_tag_position": data["source_tag_position"],
                    })

                progress = 20.0 + (clip_index / max(1, target_count)) * 75.0
                update_job(
                    job_id,
                    progress=min(95.0, progress),
                    message=f"Processing clip {clip_index}/{target_count}",
                )

            if success_count == 0:
                raise RuntimeError("Failed to generate any clip.")

            result = {
                "files": generated_files,
                "count": success_count,
            }

            update_job(
                job_id,
                status="completed",
                progress=100.0,
                message=f"Finished: {success_count} clip(s)",
                error="",
                result_json=json.dumps(result, ensure_ascii=False),
            )

    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            progress=100.0,
            message="Job failed",
            error=str(exc),
        )
    finally:
        logs = buffer.getvalue()
        if logs:
            update_job(job_id, logs=logs[-100000:])
