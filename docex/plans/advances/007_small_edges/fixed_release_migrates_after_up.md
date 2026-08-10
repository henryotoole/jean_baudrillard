# The fixed release playbook starts the stack *before* migrating

**Found:** advance 006, the fixed smoke walk (section C), by observing timestamps
rather than reading the template. Longstanding — the offending task predates mod
099. **Not caused by advance 006.**

## The divergence

[`migrations.md § Stage and Prod on Fixed Foundation`](../../../../doctrine/infrastructure/specifics/migrations.md)
makes three claims about ordering:

1. migration is placed between "render configs" and "start the new stack";
2. during it, "the **old** service containers are still running and serving traffic";
3. "if any migration fails, the playbook aborts **before `docker compose up -d`** runs
   the new stack. Old containers continue serving."

**All three are false.** In `emit/templates/playbook.yml.j2` the task named *"Pull all
images"* is a `community.docker.docker_compose_v2` call with **`state: present`** —
which brings the stack **up**. So the real ordering is **up → migrate**, and the later
"Bring up the stack" task is a near no-op: it reported `ok` and never `changed` across
all three releases of the walk.

## The evidence, from the walk rather than from the template

- prod `appdb` volume created 18:20:39; `appdb`, `api-web`, `api-worker-1` and
  `api-clock` all have `StartedAt` **18:20:40.5** — simultaneous.
- postgres reported "ready to accept connections" only at 18:20:52.
- the clock's first fire, 18:21:01, raised
  `psycopg2.errors.UndefinedTable: relation "jobs" does not exist`.
- the migration then landed, and the 18:22:01 fire succeeded.

## Why it matters more than a log line

- **The documented abort guarantee is void.** A failed migration now leaves the *new*
  code already up and serving against an *unmigrated* schema — precisely the scenario
  the documented ordering exists to prevent.
- It creates **new code against old schema**, which is the direction the
  [backward-compatibility requirement](../../../../doctrine/infrastructure/specifics/migrations.md#backward-compatibility-requirement)
  does **not** cover. That rule obliges a migration to be compatible with the
  *previous* application version; it says nothing about new code meeting a schema that
  has not moved yet.
- **The symptom is cosmetically identical to documented elastic first-release
  behaviour.** D.11 tells a walker to expect one failed clock fire on a cold elastic
  schema, so an operator who has walked elastic reads the fixed failure as normal.
  C.9 carries no such note — correctly — and that *absence* is what caught this.

## Why nothing caught it

`tests/unit/test_ansible_emitter.py` asserts only that all three compose sites carry
the right `project_name`. **No test asserts that the pull task is a pull.** The
emitted YAML is valid, ansible is happy, the release succeeds, and every artifact
looks right — the defect lives entirely in the *meaning* of one module argument.

## The fix, and why it was deliberately not made before the 1.7.0 cut

Likely one line: `community.docker.docker_compose_v2_pull` for that task, or
`ansible.builtin.command: docker compose pull`. Plus the test that would have caught
it — assert the pull task does not carry a state that brings services up.

**It was not fixed before the cut on purpose.** The fixed smoke walk had just
validated the release path end to end, including three releases, a rollback and a
dry-run. Changing that path afterwards would mean cutting 1.7.0 on a release path no
walk has exercised — and a re-walk is the single most expensive step in this process.
Shipping a **documented** divergence is safer than shipping an **unvalidated** fix.

So this brief is the deliverable, and `migrations.md` carries an explicit
known-divergence note pointing here, so the rule of record stops promising a
guarantee the executor does not keep.

## For whoever takes it

The fix and its walk should land together. Verify by the same method that found it —
compare `StartedAt` across the stack against the migration's completion time, and
assert the clock's first fire does *not* raise `UndefinedTable` on a first release.
A green playbook proves nothing here; the ordering is only visible in timestamps.
