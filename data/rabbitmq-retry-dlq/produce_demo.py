import os

from taskqueue import connect, publish_task, setup_topology

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def main():
    conn = connect(RABBITMQ_URL)
    channel = conn.channel()
    setup_topology(channel)

    # will fail twice, then succeed on the 3rd attempt (within MAX_RETRIES=3)
    publish_task(channel, "flaky_task", {"id": "job-1", "fail_times": 2})

    # will fail every attempt and end up in the dead-letter queue
    publish_task(channel, "always_fails", {"id": "job-2"})

    print("published job-1 (flaky_task) and job-2 (always_fails)")
    conn.close()


if __name__ == "__main__":
    main()
