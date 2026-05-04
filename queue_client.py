import json
import os
import time

try:
    import pika
except Exception:
    pika = None


DEFAULT_QUEUE = os.getenv("RABBITMQ_QUEUE", "yt_heatmap_clipper_jobs")


def _get_rabbitmq_url():
    return os.getenv("RABBITMQ_URL", "").strip()


def publish_job_message(message, queue_name=None):
    """
    Publish one job message to RabbitMQ queue.
    Returns (ok, error_message).
    """
    if pika is None:
        return False, "pika package is not installed"

    rabbitmq_url = _get_rabbitmq_url()
    if not rabbitmq_url:
        return False, "RABBITMQ_URL is not configured"

    q_name = queue_name or DEFAULT_QUEUE

    try:
        params = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=q_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=q_name,
            body=json.dumps(message, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        connection.close()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def consume_messages(callback, queue_name=None, retry_seconds=5):
    """
    Keep consuming RabbitMQ messages and pass decoded JSON message to callback.
    Callback signature: callback(message_dict)
    """
    if pika is None:
        raise RuntimeError("pika package is not installed")

    rabbitmq_url = _get_rabbitmq_url()
    if not rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL is not configured")

    q_name = queue_name or DEFAULT_QUEUE

    while True:
        connection = None
        try:
            params = pika.URLParameters(rabbitmq_url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=q_name, durable=True)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    callback(payload)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    # Do not lose job message when callback fails.
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=q_name, on_message_callback=on_message)
            channel.start_consuming()
        except KeyboardInterrupt:
            if connection and connection.is_open:
                connection.close()
            break
        except Exception:
            if connection and connection.is_open:
                connection.close()
            time.sleep(max(1, int(retry_seconds)))
