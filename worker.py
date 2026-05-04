import json
import os

from job_service import get_job, init_job_db, process_job, update_job
from queue_client import consume_messages


def _handle_queue_message(message):
    job_id = message.get("job_id")
    payload = message.get("payload")

    if not job_id:
        return

    if payload is None:
        record = get_job(job_id)
        payload = (record or {}).get("payload", {})

    if not payload:
        update_job(
            job_id,
            status="failed",
            progress=100.0,
            message="Job failed",
            error="Missing payload for queued job",
        )
        return

    process_job(job_id, payload)


if __name__ == "__main__":
    init_job_db()
    queue_name = os.getenv("RABBITMQ_QUEUE", "yt_heatmap_clipper_jobs")
    print(f"Worker listening on queue: {queue_name}")
    consume_messages(_handle_queue_message, queue_name=queue_name)
