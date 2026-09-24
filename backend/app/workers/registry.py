"""Which Celery task runs each job kind.

To add a job to a product:
1. write a task in `app/workers/tasks.py` with `base=JobTask` and a `job_id` argument;
2. add its kind and task name here;
3. start it from a service with `JobService.enqueue(kind, params)`.
"""

JOB_TASKS: dict[str, str] = {
    "example": "app.workers.tasks.example_task",
}
