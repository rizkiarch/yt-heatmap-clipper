import io
import os
from contextlib import redirect_stdout, redirect_stderr

from flask import Flask, render_template, request, send_from_directory, abort

import run as clipper

app = Flask(__name__)


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


@app.route("/", methods=["GET", "POST"])
def index():
    data = {
        "url": "",
        "crop_mode": "default",
        "use_subtitle": True,
    }
    logs = ""
    error = ""
    success = ""
    files = []

    if request.method == "POST":
        data["url"] = request.form.get("url", "").strip()
        data["crop_mode"] = request.form.get("crop_mode", "default")
        data["use_subtitle"] = request.form.get("use_subtitle") == "on"

        if data["crop_mode"] not in {"default", "split_left", "split_right"}:
            data["crop_mode"] = "default"

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

                    total_duration = clipper.get_duration(video_id)
                    heatmap_data = clipper.ambil_most_replayed(video_id)
                    if not heatmap_data:
                        heatmap_data = clipper.ambil_fallback_segments(video_id, total_duration)

                    if not heatmap_data:
                        raise RuntimeError(
                            "No high-engagement segments found and fallback also failed."
                        )

                    os.makedirs(clipper.OUTPUT_DIR, exist_ok=True)

                    success_count = 0
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
                        ):
                            success_count += 1

                    success = (
                        f"Finished. {success_count} clip(s) generated in '{clipper.OUTPUT_DIR}'."
                    )

                clip_files = sorted(
                    [f for f in os.listdir(clipper.OUTPUT_DIR) if f.startswith("clip_")]
                )
                files = clip_files
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
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
