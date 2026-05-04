import os
import subprocess
import sys
import tempfile
import threading
from io import BytesIO

from flask import Flask, render_template, request, send_from_directory, abort, jsonify, send_file, redirect, url_for

import run as clipper
from job_service import (
    build_history_entries,
    create_job,
    delete_history_entry,
    get_job,
    init_job_db,
    process_job,
    rename_history_entry,
)
from queue_client import publish_job_message

app = Flask(__name__)

ASYNC_ENABLED = os.getenv("ASYNC_ENABLED", "1") == "1"
ASYNC_FALLBACK_SYNC = os.getenv("ASYNC_FALLBACK_SYNC", "1") == "1"
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "yt_heatmap_clipper_jobs")

init_job_db()


def _start_local_background_job(job_id, payload):
    worker = threading.Thread(target=process_job, args=(job_id, payload), daemon=True)
    worker.start()


def _resolve_overlay_preset(preset_name):
    key = (preset_name or "").strip().lower()
    if key in clipper.OVERLAY_PRESETS:
        return key, clipper.OVERLAY_PRESETS[key]
    if key == "custom":
        return "custom", clipper.OVERLAY_PRESETS[clipper.DEFAULT_OVERLAY_PRESET]
    fallback_key = clipper.DEFAULT_OVERLAY_PRESET
    return fallback_key, clipper.OVERLAY_PRESETS[fallback_key]


def _build_payload_from_form(form):
    overlay_preset_key, overlay_defaults = _resolve_overlay_preset(form.get("overlay_preset"))

    payload = {
        "url": (form.get("url", "") or "").strip(),
        "crop_mode": form.get("crop_mode", "default"),
        "use_subtitle": form.get("use_subtitle") == "on",
        "use_source_tag": form.get("use_source_tag") == "on",
        "subtitle_style": form.get("subtitle_style", "modern"),
        "source_style": form.get("source_style", "classic"),
        "video_quality": form.get("video_quality", "medium"),
        "video_title": (form.get("video_title", "") or "").strip(),
        "overlay_preset": overlay_preset_key,
        "subtitle_font_size": clipper.clamp_int(
            form.get("subtitle_font_size", overlay_defaults["subtitle_font_size"]),
            9,
            24,
            overlay_defaults["subtitle_font_size"],
        ),
        "subtitle_bottom_margin": clipper.clamp_int(
            form.get("subtitle_bottom_margin", overlay_defaults["subtitle_bottom_margin"]),
            8,
            120,
            overlay_defaults["subtitle_bottom_margin"],
        ),
        "subtitle_max_chars": clipper.clamp_int(
            form.get("subtitle_max_chars", overlay_defaults["subtitle_max_chars"]),
            16,
            64,
            overlay_defaults["subtitle_max_chars"],
        ),
        "source_tag_scale": clipper.clamp_float(
            form.get("source_tag_scale", overlay_defaults["source_tag_scale"]),
            0.60,
            1.60,
            overlay_defaults["source_tag_scale"],
        ),
        "source_tag_position": (form.get("source_tag_position") or overlay_defaults["source_tag_position"]).strip().lower(),
    }

    try:
        payload["source_interval"] = max(4.0, float(form.get("source_interval", 30)))
    except (ValueError, TypeError):
        payload["source_interval"] = clipper.SOURCE_TAG_DEFAULT_INTERVAL

    if payload["crop_mode"] not in {"default", "split_left", "split_right", "blur_center"}:
        payload["crop_mode"] = "default"
    if payload["subtitle_style"] not in clipper.SUBTITLE_STYLES:
        payload["subtitle_style"] = "modern"
    if payload["source_style"] not in clipper.SOURCE_TAG_STYLES:
        payload["source_style"] = "classic"
    if payload["video_quality"] not in clipper.VIDEO_QUALITY_PRESETS:
        payload["video_quality"] = "medium"
    if payload["source_tag_position"] not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        payload["source_tag_position"] = overlay_defaults["source_tag_position"]

    return payload


def _extract_video_stream_url(video_id):
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "-g",
        f"https://youtu.be/{video_id}",
    ]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""


def _build_preview_crop_command(stream_url, crop_mode, seek_seconds, output_file):
    seek_value = f"{float(seek_seconds):.3f}"

    if crop_mode == "split_left":
        vf = (
            f"scale=-2:1280[scaled];"
            f"[scaled]split=2[s1][s2];"
            f"[s1]crop=720:{clipper.TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
            f"[s2]crop=720:{clipper.BOTTOM_HEIGHT}:0:ih-{clipper.BOTTOM_HEIGHT}[bottom];"
            f"[top][bottom]vstack=inputs=2[out]"
        )
        return [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", seek_value,
            "-i", stream_url,
            "-filter_complex", vf,
            "-map", "[out]",
            "-frames:v", "1",
            "-q:v", "2",
            output_file,
        ]

    if crop_mode == "split_right":
        vf = (
            f"scale=-2:1280[scaled];"
            f"[scaled]split=2[s1][s2];"
            f"[s1]crop=720:{clipper.TOP_HEIGHT}:(iw-720)/2:(ih-1280)/2[top];"
            f"[s2]crop=720:{clipper.BOTTOM_HEIGHT}:iw-720:ih-{clipper.BOTTOM_HEIGHT}[bottom];"
            f"[top][bottom]vstack=inputs=2[out]"
        )
        return [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", seek_value,
            "-i", stream_url,
            "-filter_complex", vf,
            "-map", "[out]",
            "-frames:v", "1",
            "-q:v", "2",
            output_file,
        ]

    if crop_mode == "blur_center":
        vf = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,boxblur=20:10[bg];"
            "[0:v]setsar=1,scale=720:405[fg];"
            "[bg][fg]overlay=0:(H-h)/2[out]"
        )
        return [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", seek_value,
            "-i", stream_url,
            "-filter_complex", vf,
            "-map", "[out]",
            "-frames:v", "1",
            "-q:v", "2",
            output_file,
        ]

    # default
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", seek_value,
        "-i", stream_url,
        "-vf", "scale=-2:1280,crop=720:1280:(iw-720)/2:(ih-1280)/2",
        "-frames:v", "1",
        "-q:v", "2",
        output_file,
    ]


# ── Static / utility routes ──────────────────────────────────────────────────

@app.route("/clips/<path:filename>")
def serve_clip(filename):
    # Prevent path traversal and return clear 404 only for truly missing files.
    if ".." in filename or filename.startswith("/"):
        abort(404)

    full_path = os.path.join(clipper.OUTPUT_DIR, filename)
    if not os.path.exists(full_path):
        abort(404)

    return send_from_directory(clipper.OUTPUT_DIR, filename, as_attachment=False)


@app.route("/favicon.ico")
def favicon():
    # Browser requests this automatically; avoid noisy 404 logs.
    return "", 204


# ── API: Video Info ──────────────────────────────────────────────────────────

@app.route("/api/video-info")
def api_video_info():
    """Fetch video metadata (title, channel, thumbnail, duration, view count) via yt-dlp."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    video_id = clipper.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    metadata = clipper.get_video_metadata(video_id)
    if not metadata:
        return jsonify({"error": "Could not fetch video metadata"}), 500

    return jsonify({
        "video_id": video_id,
        "title": metadata.get("title", ""),
        "channel": (
            metadata.get("channel")
            or metadata.get("uploader")
            or metadata.get("uploader_id")
            or "Unknown Channel"
        ),
        "thumbnail": metadata.get("thumbnail", ""),
        "duration": metadata.get("duration", 0),
        "view_count": metadata.get("view_count", 0),
        "description": (metadata.get("description") or "")[:500],
    })


# ── API: Heatmap ─────────────────────────────────────────────────────────────

@app.route("/api/heatmap")
def api_heatmap():
    """Return heatmap data as JSON for visual timeline graph in the UI."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    video_id = clipper.extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    heatmap_data = clipper.ambil_most_replayed(video_id)
    total_duration = clipper.get_duration(video_id)

    if not heatmap_data:
        metadata = clipper.get_video_metadata(video_id)
        if metadata:
            total_duration = clipper.get_duration_from_metadata(metadata) or total_duration
        heatmap_data = clipper.ambil_fallback_segments(video_id, total_duration, metadata)

    return jsonify({
        "video_id": video_id,
        "total_duration": total_duration,
        "segments": heatmap_data or [],
    })


# ── API: Clip History ────────────────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    """List previously generated clips with metadata and subtitle text."""
    return jsonify(build_history_entries())


@app.route("/api/history/<filename>", methods=["DELETE"])
def api_delete_clip(filename):
    """Delete a specific generated clip."""
    ok, message = delete_history_entry(filename)
    return jsonify({"ok": bool(ok), "message": message}), (200 if ok else 404)


@app.route("/api/history/rename", methods=["POST"])
def api_rename_clip():
    payload = request.get_json(silent=True) or {}
    filename = (payload.get("filename") or "").strip()
    new_title = (payload.get("new_title") or "").strip()

    ok, message, new_filename = rename_history_entry(filename, new_title)
    return jsonify({
        "ok": bool(ok),
        "message": message,
        "filename": filename,
        "new_filename": new_filename,
    }), (200 if ok else 400)


# ── API: Background Jobs ─────────────────────────────────────────────────────

@app.route("/api/jobs/submit", methods=["POST"])
def api_jobs_submit():
    payload = _build_payload_from_form(request.form)
    if not payload["url"]:
        return jsonify({"error": "YouTube URL is required."}), 400

    job_id = create_job(payload)
    mode = "local-thread"
    queue_error = ""

    if ASYNC_ENABLED:
        queued, queue_error = publish_job_message(
            {
                "job_id": job_id,
                "payload": payload,
            },
            queue_name=RABBITMQ_QUEUE,
        )
        if queued:
            mode = "rabbitmq"
        elif ASYNC_FALLBACK_SYNC:
            _start_local_background_job(job_id, payload)
        else:
            return jsonify({
                "error": f"RabbitMQ publish failed: {queue_error}",
                "job_id": job_id,
            }), 503
    else:
        if ASYNC_FALLBACK_SYNC:
            _start_local_background_job(job_id, payload)

    return jsonify({
        "job_id": job_id,
        "mode": mode,
        "queue_error": queue_error,
    }), 202


@app.route("/api/jobs/<job_id>")
def api_jobs_status(job_id):
    item = get_job(job_id)
    if not item:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(item)


@app.route("/api/preview/frame", methods=["POST"])
def api_preview_frame():
    payload = _build_payload_from_form(request.form)
    if not payload["url"]:
        return jsonify({"error": "YouTube URL is required."}), 400

    video_id = clipper.extract_video_id(payload["url"])
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL."}), 400

    metadata = clipper.get_video_metadata(video_id)
    source_channel = clipper.get_channel_name_from_metadata(metadata) if metadata else "Unknown Channel"
    duration = (clipper.get_duration_from_metadata(metadata) if metadata else None) or clipper.get_duration(video_id)

    seek_default = 12.0
    try:
        seek_raw = float(request.form.get("preview_time", seek_default))
    except (TypeError, ValueError):
        seek_raw = seek_default

    preview_subtitle_text = (
        (request.form.get("preview_subtitle_text", "") or "").strip()
    )[:240]
    if not preview_subtitle_text:
        preview_subtitle_text = "Ini contoh subtitle untuk preview ukuran dan posisi overlay."

    max_seek = max(0.5, float(duration) - 0.5)
    seek_seconds = clipper.clamp_float(seek_raw, 0.0, max_seek, seek_default)

    stream_url = _extract_video_stream_url(video_id)
    if not stream_url:
        return jsonify({"error": "Failed to resolve video stream URL for preview."}), 502

    with tempfile.TemporaryDirectory(prefix="preview_frame_") as temp_dir:
        frame_base = os.path.join(temp_dir, "frame_base.jpg")
        frame_source = os.path.join(temp_dir, "frame_source.jpg")
        frame_subtitle = os.path.join(temp_dir, "frame_subtitle.jpg")
        sample_srt = os.path.join(temp_dir, "sample_preview.srt")

        cmd_frame = _build_preview_crop_command(stream_url, payload["crop_mode"], seek_seconds, frame_base)
        try:
            subprocess.run(cmd_frame, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            return jsonify({"error": "Failed to capture preview frame from source video."}), 500

        current_frame = frame_base

        if payload["use_source_tag"]:
            source_filter = clipper.build_source_tag_filter(
                source_channel,
                payload["source_interval"],
                style=payload["source_style"],
                scale=payload["source_tag_scale"],
                position=payload["source_tag_position"],
            )
            cmd_source = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", current_frame,
                "-vf", source_filter,
                "-frames:v", "1",
                "-q:v", "2",
                frame_source,
            ]
            try:
                subprocess.run(cmd_source, check=True, capture_output=True, text=True)
                current_frame = frame_source
            except subprocess.CalledProcessError:
                pass

        if payload["use_subtitle"]:
            wrapped = clipper.wrap_subtitle_text(preview_subtitle_text, payload["subtitle_max_chars"])
            with open(sample_srt, "w", encoding="utf-8") as f:
                f.write("1\n")
                f.write("00:00:00,000 --> 00:00:20,000\n")
                f.write(f"{wrapped}\n")

            subtitle_style = clipper.build_subtitle_force_style(
                payload["subtitle_style"],
                font_size=payload["subtitle_font_size"],
                bottom_margin=payload["subtitle_bottom_margin"],
            )
            subtitle_path = os.path.abspath(sample_srt).replace("\\", "/").replace(":", "\\:")
            cmd_subtitle = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", current_frame,
                "-vf", f"subtitles='{subtitle_path}':force_style='{subtitle_style}'",
                "-frames:v", "1",
                "-q:v", "2",
                frame_subtitle,
            ]
            try:
                subprocess.run(cmd_subtitle, check=True, capture_output=True, text=True)
                current_frame = frame_subtitle
            except subprocess.CalledProcessError:
                pass

        with open(current_frame, "rb") as f:
            image_bytes = f.read()

    return send_file(
        BytesIO(image_bytes),
        mimetype="image/jpeg",
        as_attachment=False,
        download_name="preview.jpg",
        max_age=0,
    )


def _build_default_context():
    overlay_key, overlay_defaults = _resolve_overlay_preset(clipper.DEFAULT_OVERLAY_PRESET)
    data = {
        "url": "",
        "crop_mode": "default",
        "use_subtitle": True,
        "use_source_tag": False,
        "subtitle_style": "modern",
        "source_style": "classic",
        "source_interval": clipper.SOURCE_TAG_DEFAULT_INTERVAL,
        "video_quality": "medium",
        "video_title": "",
        "overlay_preset": overlay_key,
        "subtitle_font_size": overlay_defaults["subtitle_font_size"],
        "subtitle_bottom_margin": overlay_defaults["subtitle_bottom_margin"],
        "subtitle_max_chars": overlay_defaults["subtitle_max_chars"],
        "source_tag_scale": overlay_defaults["source_tag_scale"],
        "source_tag_position": overlay_defaults["source_tag_position"],
        "preview_time": 12,
        "preview_subtitle_text": "Ini contoh subtitle untuk preview ukuran dan posisi overlay.",
    }
    history = build_history_entries()
    return {
        "data": data,
        "history": history,
        "async_enabled": ASYNC_ENABLED,
        "subtitle_styles": list(clipper.SUBTITLE_STYLES.keys()),
        "source_styles": list(clipper.SOURCE_TAG_STYLES.keys()),
        "quality_presets": clipper.VIDEO_QUALITY_PRESETS,
        "overlay_presets": clipper.OVERLAY_PRESETS,
    }


# ── Page routes ──────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    ctx = _build_default_context()
    return render_template("dashboard.html", **ctx)


@app.route("/workspace", methods=["GET"])
def workspace():
    ctx = _build_default_context()
    return render_template("workspace.html", **ctx)


@app.route("/social-account", methods=["GET"])
def social_account():
    ctx = _build_default_context()
    return render_template("social_account.html", **ctx)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
