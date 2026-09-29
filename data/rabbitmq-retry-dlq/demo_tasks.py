"""
Two demo tasks to exercise both paths through the queue:

- flaky_task: fails `fail_times` attempts, then succeeds. Proves the retry
  path works and a task can recover.
- always_fails: always raises. Proves a task that never succeeds ends up
  in the dead-letter queue after MAX_RETRIES, instead of retrying forever.
"""
import logging

from taskqueue.worker import task

logger = logging.getLogger("demo_tasks")


@task("flaky_task")
def flaky_task(payload: dict, retry_count: int) -> None:
    fail_times = payload.get("fail_times", 0)
    if retry_count < fail_times:
        raise RuntimeError(f"simulated failure (attempt {retry_count + 1}, need {fail_times} failures)")
    logger.info("flaky_task %r processed successfully after %d prior failures", payload["id"], retry_count)


@task("always_fails")
def always_fails(payload: dict, retry_count: int) -> None:
    raise RuntimeError(f"task {payload['id']} is designed to always fail")
