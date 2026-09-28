"""Which Celery task runs each job kind.

To add a job to a product:
1. write a task in `app/workers/tasks.py` with `base=JobTask` and a `job_id` argument;
2. add its kind and task name here;
3. start it from a service with `JobService.enqueue(kind, params)`;
4. if the plan should limit it, add it to JOB_USAGE_METRIC (counted when it is queued).
"""

JOB_TASKS: dict[str, str] = {
    "example": "app.workers.tasks.example_task",
    "data_export": "app.workers.tasks.data_export",
}

# Jobs only the person who started them can see (not the rest of the workspace,
# and not API keys). Use it for personal things like "export my data".
PRIVATE_JOB_KINDS: frozenset[str] = frozenset({"data_export"})

# Job kinds that count towards a monthly plan limit (app/core/plans.py -> PlanLimits).
# Never meter GDPR jobs like "data_export": people must always get their data.
JOB_USAGE_METRIC: dict[str, str] = {"example": "jobs_per_month"}
