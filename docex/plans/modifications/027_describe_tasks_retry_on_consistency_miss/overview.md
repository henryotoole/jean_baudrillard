# Mod 027 — Retry `describe_tasks` on eventual-consistency miss

## Problem

After ECS `RunTask` returns a task ARN, the immediately-following `describe_tasks` call can briefly return `tasks: []` due to ECS API eventual consistency — the task record exists but isn't yet visible to describe.

`ecs_wait_for_task` in `src/docex/aws/boto3_client.py` raises `ECSTaskFailed` on the very first empty response. The 0.11.0 elastic-prod release walk hit this: the migration task actually ran to completion (`exitCode = 0`, verified via `aws ecs describe-tasks` afterward) but docex bailed before the task became visible to its own poll.

```
error: describe_tasks returned no record for
'arn:aws:ecs:us-east-1:...:task/docex_smoke_elastic_prod/209a0bfa...'
```

The same task ARN, queried 5 seconds later, returned the full record with `lastStatus: STOPPED, exitCode: 0`.

## Scope

In scope:

- `src/docex/aws/boto3_client.py::ecs_wait_for_task`: when `describe_tasks` returns `tasks: []`, treat it as transient for a bounded number of attempts (e.g. up to 30 s of retries at the existing 5 s `poll_interval`) before raising. Once the task has been *seen at least once*, an empty response in subsequent polls retains the existing raise (that's a "task vanished" failure mode, semantically different).
- A unit test that mocks `describe_tasks` to return empty for the first call and a real record afterward; assert the wait completes successfully.

Out of scope:

- The broader question of "should docex retry every boto3 call on transient errors?" Boto3 already retries on most. The describe_tasks-after-RunTask consistency gap is the specific surface we know to hit.
- Polling intervals or task-wait timeout values (stay at the current 5 s / 600 s defaults).

## Design

Add a small "have we seen it yet?" guard:

```python
def ecs_wait_for_task(
    self, *, cluster: str, task_arn: str, timeout_s: int = 600
) -> int:
    ecs = self._client("ecs")
    deadline = time.monotonic() + timeout_s
    poll_interval = 5
    seen_once = False
    consistency_deadline = time.monotonic() + 30  # tolerate up to 30s of EC

    while True:
        resp = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
        tasks = resp.get("tasks", [])
        if not tasks:
            if seen_once or time.monotonic() > consistency_deadline:
                # Already observed once -> task vanished (real failure).
                # Or: never observed within the consistency window
                # -> something is wrong upstream.
                raise ECSTaskFailed(
                    f"describe_tasks returned no record for {task_arn!r}"
                )
            # Eventual-consistency window: retry without raising.
            time.sleep(poll_interval)
            continue
        seen_once = True
        # ... rest unchanged ...
```

The 30 s consistency budget is generous — observed lag is typically sub-second, and we don't want a real "task vanished" failure to take 30 s to surface.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `aws/boto3_client.py::ecs_wait_for_task` (add the consistency-window guard). |
| `tests/**` | Add a unit test mocking ecs.describe_tasks to return empty first, then populated. |

## What this mod does NOT do

- Does not change the overall timeout (600 s default).
- Does not change behavior once the task has been observed (failure modes after first-observation stay sharp).
- Does not retry on actual API errors — only on empty result sets.
