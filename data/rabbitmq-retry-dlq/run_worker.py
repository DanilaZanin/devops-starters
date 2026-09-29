import logging
import os

import demo_tasks  # noqa: F401 - registers the task handlers
from taskqueue.worker import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    run(os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"))
