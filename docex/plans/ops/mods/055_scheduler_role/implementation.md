# Mod 055 — Implementation steps

Doctrine is landed (see overview § Doctrine status; full mechanism in
`doctrine/infrastructure/specifics/scheduler.md` — **read it first**). These steps
cover `docex` code + tests only. Repo root: `~/.claude/jean_baudrillard/docex`.

Read before starting: `tables/roles/web.yml` and `tables/roles/object_store.yml`
(role/engine + `fields:` shape), `src/docex/emit/hcl.py` (`render_task_definition`,
`render_ecs_service`, `_DESTINATION_RENDERERS`, `_RenderCtx`), `src/docex/emit/compose.py`
(`emit_compose`, `_sidecar_block`, the `configs:` block for otelcol, `_service_block`),
`src/docex/cicl/compile.py` (service iteration, env resolution, where `$[...]`
secret refs are produced), `src/docex/cicl/validate.py` (rule structure),
`src/docex/cicl/transfer.py` (`EMIT_DESTINATIONS`).

## 1. `tables/roles/scheduler.yml` (new bundled role)

Model on `web.yml`. Engine `container`, `foundation: both`.

```yml
roles:
  scheduler:
    description: "Core service run on a cron schedule (a job), not a long-running server."
    container:
      foundation: both
      emits:
        fixed: [compose_service]
        elastic: [task_definition, scheduled_task]   # NO ecs_service, NO target_group
      defaults:
        fixed: {}
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
      fields:
        # `schedule` is declared here so it is a recognized role-specific field
        # (validation rule 4 rejects it on other roles; `docex role scheduler`
        # surfaces it). Its VALUE needs cron translation, which is procedural —
        # the compiler special-cases it (step 4); these template bodies are
        # markers that route the (translated) value to the right destination.
        schedule:
          fixed: {}                 # consumed by the ofelia emitter (compose)
          elastic:
            target: scheduled_task   # consumed by render_scheduled_task
      provides: {}                   # a scheduler serves nothing; no parts
      env: {}
      naming: ecs
```

Verify against the loader's allowed-keys (`_ALLOWED_*` in `transfer.py`): if an
empty `fields.<f>: {}` or `provides: {}` trips strict validation, give them the
minimal shape the loader accepts (look at how `web`/`object_store` satisfy it).
The point is that `schedule` is a *declared* field for this engine.

## 2. `EMIT_DESTINATIONS` — register `scheduled_task`

`src/docex/cicl/transfer.py`, add `"scheduled_task"` to the `"elastic"` frozenset.

## 3. `src/docex/cicl/cron.py` (new) — cron translation

```python
"""5-field cron translation. Mod 055.

infra.yml carries a standard 5-field cron (min hour dom mon dow, UTC). Two
targets need different forms — see scheduler.md § Cron format."""
from __future__ import annotations

_DOW_NAMES = {...}  # optional: accept MON..SUN passthrough

def validate_five_field(expr: str) -> None:
    """Raise a clear error if expr is not a well-formed 5-field cron."""
    ...

def to_aws_cron(expr: str) -> str:
    """5-field -> AWS `cron(min hour dom mon dow year)`.
    - append year field `*`
    - if dow == '*': dow -> '?'   elif dom == '*': dom -> '?'
      (AWS forbids '*' in both day fields; exactly one must be '?')
    - remap NUMERIC dow 0-6 (0/7=Sun) -> 1-7 (1=Sun): n -> (n % 7) + 1
      (named days pass through unchanged)
    Returns the inner expression WITHOUT the `cron(...)` wrapper, or with —
    pick one and be consistent; render_scheduled_task wraps as needed."""
    ...

def to_ofelia_cron(expr: str) -> str:
    """5-field -> ofelia 6-field: prepend '0 ' (run at second 0). dow numbering
    matches standard cron, so no remap."""
    return "0 " + expr.strip()
```

Handle ranges/lists/steps (`1-5`, `*/15`, `1,3,5`) by operating on the field as a
whole where the numbering remap must descend into numeric tokens — keep it
simple but correct for the common forms; reject what you can't translate with a
clear error rather than mistranslating. Unit-test these (step 8).

## 4. `validate.py` — scheduler field rules

Add validation (compile-time): for any core service with `role == "scheduler"`:
- `schedule` is present and a non-empty string → else clear error.
- `command` is present (str or list) → else clear error.
- `schedule` value passes `cron.validate_five_field` (surface the translation
  error at compile, not at apply).

`schedule` on a **non**-scheduler service is already rejected by the existing
"role-specific field must be declared in the engine's `fields:`" rule (rule 4),
since only `scheduler/container` declares it — confirm this fires and add a test.

## 5. `compile.py` — carry schedule; recognize scheduler

- Ensure the service's `schedule` (a role-specific extra, captured by the model's
  `extra="allow"`) is carried onto the `CompiledService` (alongside how other
  role fields / `command` are carried). Add a typed accessor if it helps the
  emitters (`svc.schedule`).
- The compiler already sets `command` on the body (compile.py ~628/648) — that
  path serves both web and scheduler.
- No web-host derivation for scheduler (it's never on `web`; `_web_hosts` already
  returns `[]` for non-web — fine).

## 6. `emit/hcl.py` — scheduled_task renderer + sidecar omission

**6a. Omit the OTel sidecar for one-shot tasks.** In `render_task_definition`,
the second (sidecar) container must be skipped when the service does not also
emit `ecs_service` (i.e. it's a one-shot like scheduler). Gate the sidecar
append on `"ecs_service" in svc.emits.get("elastic", [])`. This keeps the rule
principled ("sidecar pairs with long-running services only") and is what
scheduler.md commits to.

**6b. `render_scheduled_task`.** New renderer; register in
`_DESTINATION_RENDERERS["scheduled_task"]`. Emits, per scheduler service `<svc>`:

```hcl
resource "aws_iam_role" "<svc>_scheduler" {
  name               = "<svc-global>_scheduler"   # iam policy naming
  assume_role_policy = jsonencode({ ... Principal: { Service: "scheduler.amazonaws.com" } ... })
}
resource "aws_iam_role_policy" "<svc>_scheduler" {
  role   = aws_iam_role.<svc>_scheduler.id
  policy = jsonencode({ Statement = [
    { Effect="Allow", Action="ecs:RunTask",
      Resource = aws_ecs_task_definition.<svc>.arn },
    { Effect="Allow", Action="iam:PassRole",
      Resource = [ data.terraform_remote_state.project.outputs.task_execution_role_arn ] },
  ]})
}
resource "aws_scheduler_schedule" "<svc>" {
  name = "<svc-global>"
  flexible_time_window { mode = "OFF" }
  schedule_expression          = "cron(<to_aws_cron>)"
  schedule_expression_timezone = "UTC"
  target {
    arn      = aws_ecs_cluster.cluster.arn
    role_arn = aws_iam_role.<svc>_scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.<svc>.arn
      launch_type         = "FARGATE"
      task_count          = 1
      network_configuration {
        subnets          = [data.terraform_remote_state.project.outputs.primary_private_subnet_id]
        security_groups  = [aws_security_group.<net>.id, ...]   # the svc's non-web nets, like render_ecs_service
        assign_public_ip = false
      }
    }
  }
}
```

Mirror `render_ecs_service`'s network block exactly (same `primary_private_subnet_id`
+ per-net SG refs). Use the `iam`/`ecs` naming policies consistently with how the
rest of hcl.py forms names (look at how `render_ecs_service`/`render_task_definition`
get `svc.global_name` and how IAM names are formed elsewhere — e.g. the project
task-execution role uses the `iam` policy). Apply tags via the standard tag block
the other renderers use.

Check whether the env's ECS cluster resource (`aws_ecs_cluster.cluster`) is always
emitted when there is at least one scheduler but zero web/ecs_service services — a
scheduler-only env still needs the cluster for RunTask. If the cluster is
currently emitted only when an `ecs_service` exists, fix the cluster-emission
condition to also fire when any `scheduled_task` is emitted.

## 7. `emit/compose.py` — ofelia container + INI for scheduler services

In `emit_compose`, detect scheduler services (`svc.role == "scheduler"`, or
`"compose_service"`-with-no-web + a scheduler marker — prefer an explicit
`svc.role` check). For each:

- Do **not** emit a normal long-running service block for the job itself.
- Emit one compose service `<project_dns_label>-<env>-<svc>-scheduler`:
  - `image: mcuadros/ofelia:<digest>` — add a pinned digest constant near
    `OTEL_COLLECTOR_IMAGE` (call it `OFELIA_IMAGE`).
  - `container_name`, `restart: unless-stopped`, `logging: *default-logging`,
    `labels: [docex.project=<label>]` (no traefik labels).
  - `volumes`: `/var/run/docker.sock:/var/run/docker.sock:ro`.
  - `configs:` referencing the rendered INI (mirror the otelcol `configs:`
    mechanism — `_sidecar_block` + the top-level `configs:` declaration).
  - `network_mode`/`networks`: ofelia needs the docker socket, not the job's
    network; it can be on the default or the env internal net. The JOB's network
    is set in the INI `network=`. Keep ofelia simple (no special network needs).
- Render the INI to `infra/output/<env>/ofelia-<svc>.ini` and declare it in the
  top-level `configs:` block (one config per scheduler service). INI shape per
  scheduler.md § Fixed:
  ```
  [job-run "<svc>"]
  schedule = <to_ofelia_cron(schedule)>
  image = <the same image ref compile derived for this svc>
  network = <project>-<env>-<first non-web network>   # the job's net
  delete = true
  environment = ["KEY=VALUE", ...]        # NON-secret resolved env only
  command = sh -c '. /run/job.env && exec <command...>'
  volume = ["<env-file path>:/run/job.env:ro"]
  ```

**Env/secret split (step-by-step):** the compiled service's resolved `env` dict
holds values that are either literals or `$[VAR]` secret refs. Partition:
- Values matching the `$[...]` runtime-ref form → **secrets**. Do NOT inline.
  They arrive via the sourced `.env` (the command wrapper). The keys still need
  to exist in `.env`/`example.env`, which the existing secrets emit already
  handles for the service's env.
- Everything else (literals, doctrine-injected `OTEL_*`/`PROJECT_VERSION`,
  magic-refs that resolved to literals like `DATABASE_HOST`) → **inline** into
  the INI `environment` list as `KEY=value`.
- The env-file path: use the same path the env's compose stack uses. For
  dev/test that is the project's `infra/secrets/<env>.env` mounted into the job.
  Confirm what path is correct/available at job-run time on the host and mirror
  the migrate one-off's choice; if the cleanest available is the operator's
  `infra/secrets/<env>.env`, mount that. Document the chosen path in a comment.
- `command`: accept str or list (model allows both). Build the wrapped form
  `sh -c '. /run/job.env && exec <cmd>'` where `<cmd>` is the original command
  joined/quoted safely.

Look at how `_sidecar_block`/the otelcol `configs:` are wired so the ofelia INI
delivery matches that established pattern exactly (a rendered file under
`infra/output/<env>/` + a `configs:` entry + a `configs:` mount on the service).

## 8. Tests

- **`tests/.../test_cron.py`** (new): `to_aws_cron` (`* * * * *` → `* * ? * *`-ish
  with year; numeric dow remap `0`→`1`, `6`→`7`; dom-`*`/dow-set case →
  dom→`?`); `to_ofelia_cron` prepends `0 `; `validate_five_field` rejects 4/6-field
  and garbage.
- **Fixed emit** (`test_compose_emitter.py` or a new file): a `scheduler` service
  produces an ofelia service (image `mcuadros/ofelia`, docker.sock mount, a
  `[job-run]` INI with the translated schedule, `delete=true`, the command
  wrapper, env split: a secret env key NOT inlined, a non-secret key inlined),
  and does NOT produce a normal long-running container for the job. Other
  services in the same env are unaffected.
- **Elastic emit** (`test_hcl_emitter.py` or similar): a `scheduler` service emits
  `aws_scheduler_schedule` (correct `cron(...)`), the invocation IAM role + policy
  (RunTask on the task def, PassRole on exec role), a `task_definition` with NO
  second (sidecar) container and NO `ecs_service`/`target_group`. Also assert a
  long-running `web` service in the same project STILL gets its sidecar (the
  omission is scoped to one-shot tasks).
- **Validation** (`test_validate.py`): scheduler without `schedule` → error;
  scheduler without `command` → error; `schedule` on a `web` service → error
  (rule 4); a malformed cron → error.
- A small **compile fixture**: an `infra.yml` with one scheduler service compiling
  cleanly on both foundations (extend an existing compile-test fixture or add a
  minimal one).

## 9. Verify

- `pytest` (unit) green. Integration not required (no new docker/AWS/git boundary
  is unit-reachable; the renderers are pure string emit). Ensure new deps (none
  expected beyond stdlib) are fine.
- `python -m docex compile` against a scratch project with a scheduler service on
  each foundation, eyeballing `infra/output/<env>/` for the ofelia INI (fixed) and
  the `aws_scheduler_schedule` (elastic). Do NOT modify the committed smoke
  projects' output; if you add a scheduler to a smoke project to test, revert it
  afterward (or use a throwaway temp project).

Report: files changed/created, test counts, the compile spot-check result, and any
inaccuracy in this plan you had to deviate from (especially around the empty
`fields:`/`provides:` loader strictness, the cluster-emission condition, and the
fixed env-file path choice — those are the three places most likely to need a
judgment call).
