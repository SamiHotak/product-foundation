"""Start the example job and print its progress from the database.

Proves that Postgres, Redis, the worker and the job status table all work together.
Run: python -m app.scripts.run_example_job   (or: make example-job)
"""

import time

from sqlalchemy import select

from app.db.session import sync_session
from app.models.organization import Organization
from app.repositories.jobs import SyncJobRepository
from app.workers.dispatch import send_job


def main(steps: int = 5, timeout_seconds: float = 60.0) -> None:
    """Create a job row, queue the task, poll the row until it finishes."""
    params = {"steps": steps, "fail": False}
    with sync_session() as session:
        org = session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
        if org is None:
            raise SystemExit(
                "No workspace yet. Sign up in the app first: http://localhost:3000/signup"
            )
        job_id = (
            SyncJobRepository(session)
            .create(kind="example", params=params, organization_id=org.id)
            .id
        )
    send_job(job_id, "example", params)
    print(f"Queued example job {job_id}")

    deadline = time.monotonic() + timeout_seconds
    last: tuple[str, int] | None = None
    while True:
        with sync_session() as session:
            job = SyncJobRepository(session).get(job_id)
            assert job is not None
            state = (job.status.value, job.progress)
            if state != last:
                print(f"  {job.status.value:<8} {job.progress:>3}%  {job.message or ''}")
                last = state
            if job.status.is_finished:
                print(f"Finished: {job.status.value}. {job.error or job.result}")
                return
        if time.monotonic() > deadline:
            raise SystemExit("Timed out. Is the worker running? Check: make logs s=worker")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
