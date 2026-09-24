"""Send the example task to the Celery worker and print its progress.

Proves that Redis, the worker and task results all work.
Run: python -m app.scripts.run_example_job   (or: make example-job)
"""

import time

from app.workers.tasks import example_task


def main(steps: int = 5, timeout_seconds: float = 60.0) -> None:
    """Queue the task, poll its state, print progress until it finishes."""
    result = example_task.delay(steps=steps, delay_seconds=1.0)
    print(f"Queued example task {result.id}")
    deadline = time.monotonic() + timeout_seconds
    last = None
    while not result.ready():
        if time.monotonic() > deadline:
            raise SystemExit("Timed out. Is the worker running? Check: make logs s=worker")
        info = result.info if isinstance(result.info, dict) else {}
        progress = info.get("progress", 0)
        if progress != last:
            print(f"  {result.state:<8} {progress:>3}%")
            last = progress
        time.sleep(0.3)
    print(f"Done: {result.get(timeout=5)}")


if __name__ == "__main__":
    main()
