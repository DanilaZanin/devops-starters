"""Settings and broker object names. Everything comes from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 5672
    user: str = "orders_app"
    password: str = ""
    vhost: str = "/"
    # Prepended to every exchange/queue name. Tests use a unique prefix per run
    # so they never touch the queues of a consumer that is running in compose.
    prefix: str = ""
    max_retries: int = 3
    retry_delay_ms: int = 3000
    # Seconds to wait before a message is put back after a failed publish.
    requeue_pause_s: float = 0.5
    # Touched by the consumer loop; the container healthcheck reads its mtime.
    heartbeat_file: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.environ.get("RABBITMQ_HOST", cls.host),
            port=int(os.environ.get("RABBITMQ_PORT", cls.port)),
            user=os.environ.get("RABBITMQ_USER", cls.user),
            password=os.environ.get("RABBITMQ_PASSWORD", cls.password),
            vhost=os.environ.get("RABBITMQ_VHOST", cls.vhost),
            max_retries=int(os.environ.get("MAX_RETRIES", cls.max_retries)),
            retry_delay_ms=int(os.environ.get("RETRY_DELAY_MS", cls.retry_delay_ms)),
            heartbeat_file=os.environ.get("HEARTBEAT_FILE") or None,
        )

    @property
    def main_exchange(self) -> str:
        return f"{self.prefix}orders.x"

    @property
    def main_queue(self) -> str:
        return f"{self.prefix}orders"

    @property
    def retry_exchange(self) -> str:
        return f"{self.prefix}orders.retry.x"

    @property
    def retry_queue(self) -> str:
        return f"{self.prefix}orders.retry"

    @property
    def dead_exchange(self) -> str:
        return f"{self.prefix}orders.dead.x"

    @property
    def dead_queue(self) -> str:
        return f"{self.prefix}orders.dead"
