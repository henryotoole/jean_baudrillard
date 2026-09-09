# Mod 006 — Implementation Steps

Read `overview.md` in this folder first. You are running in a fresh context. Everything you need is captured here. Work through the steps in order. Run tests at the end. Leave all changes uncommitted.

## Scope

Two small, independent fixes that bundle into one mod cycle:

- **Fix A**: emit allow-all egress on every per-network SG in `main.tf.j2`. Today Terraform's `aws_security_group` with no egress clause denies all egress, which broke Fargate's reach to SSM during the elastic D.7 walk.
- **Fix B**: extend the postgres engine's `reserved_names` list to include `db`, `template0`, `template1` so compile catches RDS-reserved DBName collisions instead of `tofu apply` doing it.

Both fixes share a theme — the doctrine already declares the intended behavior; mod 006 wires it up.

## Step 1 — Fix A: SG egress in `main.tf.j2`

File: `src/docex/emit/templates/main.tf.j2`.

The per-network SG block (around lines 50-83) currently looks like:

```jinja
{% for short in networks_sorted -%}
resource "aws_security_group" "{{ short }}" {
  name        = "{{ project }}_{{ env }}_{{ short }}"
  description = "{{ short }} network for {{ project }} {{ env }}"
  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id
  tags = {
    project    = "{{ project }}"
    env        = "{{ env }}"
    network    = "{{ short }}"
    managed_by = "doctrine"
  }
}
{% if short == "web" %}
...
{% endif %}
{% endfor %}
```

Add an `egress { ... }` block inside the SG resource, matching the ALB SG's existing form:

```jinja
resource "aws_security_group" "{{ short }}" {
  name        = "{{ project }}_{{ env }}_{{ short }}"
  description = "{{ short }} network for {{ project }} {{ env }}"
  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    project    = "{{ project }}"
    env        = "{{ env }}"
    network    = "{{ short }}"
    managed_by = "doctrine"
  }
}
```

A brief inline comment above the `egress` block is fine — keep it terse:

```
# All-egress matches the AWS default for a fresh SG; Terraform's
# aws_security_group otherwise denies egress when no block is given.
# Defense-in-depth via per-network egress restriction is deferred —
# see infrastructure.md § Deferred.
```

Do NOT touch the ALB SG (which already has the right egress). Do NOT touch the per-network ingress rules (`aws_security_group_rule.{short}_ingress_from_alb` and `aws_security_group_rule.{short}_self_ingress`).

## Step 2 — Fix B: extend postgres reserved_names

File: `tables/roles/relational_db.yml`.

Find the `reserved_names:` block under `roles.relational_db.postgres`. It already includes `database`, `postgres`, `admin`, `master`, `root`, `public`, `rdsadmin`, and a long list of SQL keywords.

Append (grouped with the existing RDS/admin block, alphabetical within the group) these three entries:

- `db`
- `template0`
- `template1`

Sketch (existing list shown for context — only the three additions are new):

```yaml
reserved_names:
  # Common RDS/admin collisions:
  - database
  - db                # NEW (mod 006): RDS rejects "db" as a DBName for the postgres engine.
  - postgres
  - admin
  - master
  - root
  - public
  - rdsadmin
  - template0         # NEW (mod 006): postgres-internal template DB; RDS won't let it be the initial DBName.
  - template1         # NEW (mod 006): same.
  # SQL-standard reserved keywords that postgres also reserves:
  - all
  ...
```

The inline comments above are illustrative — the actual file just lists the names. Don't introduce stylistic noise; mirror the existing comment cadence in the file.

## Step 3 — Update doctrine prose

File: `doctrine/infrastructure/specifics/networks.md`.

Under § Implementation by Name (right after the `web` / `internal` sub-sections), add a short subsection:

```markdown
#### Egress

Every project-emitted SG on the elastic foundation carries an
allow-all egress rule (`0.0.0.0/0`, all ports, all protocols). This
matches the AWS-side default for a freshly-created SG; Terraform's
`aws_security_group` resource otherwise denies egress when no `egress`
block is specified, which would prevent Fargate tasks from reaching
SSM, ECR, and other AWS service endpoints they need to start.

Constraining egress per network — restricting traffic to specific
AWS service endpoints or to other project SGs — is deferred. See
[infrastructure.md § Deferred](../infrastructure.md#deferred) rule 6.
```

Mirror the existing prose tone (terse, definitive, cross-referenced).

No change needed to `transfer_tables.md` for Fix B — the `reserved_names` mechanism is already documented and the list is just data.

## Step 4 — Tests

### 4a. Snapshot/integration: every emitted SG has egress

Find the existing integration test that compiles `test_projects/elastic` or the sample project and asserts on the env `main.tf` content (likely `tests/integration/test_compile.py`). Add an assertion: for each env (`dev` excluded since `dev` is fixed-foundation and uses compose), the env `main.tf` contains exactly 3 occurrences of `egress {` — one for the web SG, one for the internal SG, one for the ALB SG.

Sketch:

```python
def test_every_sg_has_egress(...):
    for env in ("stage", "prod"):
        tf = (out_dir / env / "main.tf").read_text()
        assert tf.count("egress {") == 3, (
            f"expected 3 egress blocks in {env}/main.tf "
            "(web, internal, alb), got {tf.count('egress {')}"
        )
```

Adjust to the existing test file's conventions (fixtures, helpers).

### 4b. Unit: reserved_names catches `db` at compile time

Find the existing test (`tests/unit/test_validate.py` or similar) that exercises `reserved_names` validation. Add a case: a `infra.yml` declaring `backing_services.db` with `role: relational_db, engine: postgres` causes compile to raise the validation error pointing at the reserved-name collision.

If no such test exists yet, write one. Use the existing fixture project as the base; swap the backing service name to `db`.

## Step 5 — Run the test suite

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/    # all green
python3 -m pytest tests/         # all green (208 + the new test(s))
```

Existing snapshot tests may break if they depended on no-egress-block content. Read each diff, confirm it matches the new template, and update the snapshot fixture.

## Step 6 — Leave uncommitted

Per the mod process, the design-context LLM reviews the diff before commit. Do NOT run `git commit`.

## Hand-off report

In ≤200 words, summarize:
- Files changed.
- Test results (pass count, any snapshot updates).
- Any decisions made beyond what's in this file.

## Out of scope

- Rebuilding the `docex` image or repinning consumers (cut-time steps).
- Re-running the D.7 elastic walk (operator does this after the cut).
- Constraining egress to specific destinations (`infrastructure.md § Deferred`).
- Expanding `reserved_names` beyond `db`, `template0`, `template1` (speculative additions risk false-positives).
