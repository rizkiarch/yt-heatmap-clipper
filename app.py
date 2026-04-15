import io
import os
import json
import time
from contextlib import redirect_stdout, redirect_stderr

from flask import Flask, render_template, request, send_from_directory, abort, jsonify

import run as clipper

app = Flask(__name__)

MANIFEST_FILE = os.path.join(clipper.OUTPUT_DIR, "manifest.json")


def _load_manifest():
    """Load clip history manifest from disk."""
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_manifest(data):
    """Save clip history manifest to disk."""
    os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _add_to_manifest(entry):
    """Append a clip entry to the manifest."""
    manifest = _load_manifest()
    manifest.append(entry)
    _save_manifest(manifest)


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
    """List previously generated clips with metadata."""
    manifest = _load_manifest()
    # Verify files still exist
    valid = []
    for entry in manifest:
        fpath = os.path.join(clipper.OUTPUT_DIR, entry.get("filename", ""))
        if os.path.exists(fpath):
            entry["file_size"] = os.path.getsize(fpath)
            valid.append(entry)
    return jsonify(valid)


@app.route("/api/history/<filename>", methods=["DELETE"])
def api_delete_clip(filename):
    """Delete a specific generated clip."""
    if ".." in filename or "/" in filename:
        abort(404)

    fpath = os.path.join(clipper.OUTPUT_DIR, filename)
    if os.path.exists(fpath):
        os.remove(fpath)

    # Also remove corresponding .srt if exists
    srt_path = fpath.rsplit(".", 1)[0] + ".srt"
    if os.path.exists(srt_path):
        os.remove(srt_path)

    # Update manifest
    manifest = _load_manifest()
    manifest = [e for e in manifest if e.get("filename") != filename]
    _save_manifest(manifest)

    return jsonify({"ok": True})


# ── Main page + processing ───────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
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
    }
    logs = ""
    error = ""
    success = ""
    files = []

    if request.method == "POST":
        data["url"] = request.form.get("url", "").strip()
        data["crop_mode"] = request.form.get("crop_mode", "default")
        data["use_subtitle"] = request.form.get("use_subtitle") == "on"
        data["use_source_tag"] = request.form.get("use_source_tag") == "on"
        data["subtitle_style"] = request.form.get("subtitle_style", "modern")
        data["source_style"] = request.form.get("source_style", "classic")
        data["video_quality"] = request.form.get("video_quality", "medium")
        data["video_title"] = request.form.get("video_title", "").strip()

        try:
            data["source_interval"] = max(4.0, float(request.form.get("source_interval", 30)))
        except (ValueError, TypeError):
            data["source_interval"] = 30.0

        # Validate crop mode
        valid_crop_modes = {"default", "split_left", "split_right", "blur_center"}
        if data["crop_mode"] not in valid_crop_modes:
            data["crop_mode"] = "default"

        # Validate presets
        if data["subtitle_style"] not in clipper.SUBTITLE_STYLES:
            data["subtitle_style"] = "modern"
        if data["source_style"] not in clipper.SOURCE_TAG_STYLES:
            data["source_style"] = "classic"
        if data["video_quality"] not in clipper.VIDEO_QUALITY_PRESETS:
            data["video_quality"] = "medium"

        if not data["url"]:
            error = "YouTube URL is required."
        else:
            buffer = io.StringIO()
            try:
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    clipper.cek_dependensi(
                        install_whisper=data["use_subtitle"],
                        update_ytdlp=False,
                    )

                    video_id = clipper.extract_video_id(data["url"])
                    if not video_id:
                        raise ValueError("Invalid YouTube URL.")

                    # Fetch metadata for channel name + duration
                    metadata = clipper.get_video_metadata(video_id)
                    source_channel = clipper.get_channel_name_from_metadata(metadata) if metadata else "Unknown Channel"

                    total_duration = (
                        clipper.get_duration_from_metadata(metadata) if metadata else None
                    ) or clipper.get_duration(video_id)

                    heatmap_data = clipper.ambil_most_replayed(video_id)
                    if not heatmap_data:
                        heatmap_data = clipper.ambil_fallback_segments(video_id, total_duration, metadata)

                    if not heatmap_data:
                        raise RuntimeError(
                            "No high-engagement segments found and fallback also failed."
                        )

                    os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)

                    success_count = 0
                    generated_files = []
                    for item in heatmap_data:
                        if success_count >= clipper.MAX_CLIPS:
                            break

                        if clipper.proses_satu_clip(
                            video_id,
                            item,
                            success_count + 1,
                            total_duration,
                            data["crop_mode"],
                            data["use_subtitle"],
                            data["use_source_tag"],
                            source_channel,
                            data["source_interval"],
                            data["subtitle_style"],
                            data["source_style"],
                            data["video_quality"],
                            data["video_title"] or None,
                        ):
                            success_count += 1

                            # Determine output filename
                            if data["video_title"]:
                                safe_title = clipper.sanitize_filename(data["video_title"])
                                fname = f"{safe_title}_clip_{success_count}.mp4"
                            else:
                                fname = f"clip_{success_count}.mp4"

                            generated_files.append(fname)

                            # Add to manifest
                            _add_to_manifest({
                                "filename": fname,
                                "source_url": data["url"],
                                "video_title": data["video_title"] or metadata.get("title", "") if metadata else "",
                                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "duration": item.get("duration", 0),
                                "crop_mode": data["crop_mode"],
                                "subtitle_style": data["subtitle_style"],
                                "source_style": data["source_style"],
                                "video_quality": data["video_quality"],
                            })

                    success = (
                        f"Finished. {success_count} clip(s) generated in '{clipper.OUTPUT_DIR}'."
                    )

                files = generated_files if generated_files else sorted(
                    [f for f in os.listdir(clipper.OUTPUT_DIR) if f.endswith(".mp4")]
                )
            except Exception as exc:
                error = str(exc)
            finally:
                logs = buffer.getvalue()

    return render_template(
        "index.html",
        data=data,
        logs=logs,
        error=error,
        success=success,
        files=files,
        subtitle_styles=list(clipper.SUBTITLE_STYLES.keys()),
        source_styles=list(clipper.SOURCE_TAG_STYLES.keys()),
        quality_presets=clipper.VIDEO_QUALITY_PRESETS,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
