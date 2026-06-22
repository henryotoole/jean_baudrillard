# Implementation — Mod 043 — Service Connect Private DNS

## Context for fresh-context implementer

You are executing mod 043. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`shape.md § Elastic-Foundation`](../../../../doctrine/infrastructure/shape.md#elastic-foundation) — the service_discovery row, especially the resolution semantics "from inside the namespace" vs "from elsewhere in the master VPC".

## Operator decisions

None required — scope is fully prescribed by the doctrine.

## Step-by-step plan

### Step 1 — Flip the namespace resource type in `main.tf.j2`

Edit `src/docex/emit/templates/main.tf.j2` lines ~108–122. Replace the existing `aws_service_discovery_http_namespace.env` block with:

```hcl
# ---------------------------------------------------------------------------
# Service discovery — ECS Service Connect over a Cloud Map PRIVATE DNS
# namespace. Per shape.md § Elastic-Foundation, one namespace per env,
# associated with the master VPC. Auto-creates a Route53 private hosted
# zone resolvable VPC-wide so EC2-traefik (mod 044) and other non-ECS
# consumers can reach services by name. ECS tasks inside the namespace
# resolve by discoveryName alone via the Envoy sidecar; consumers
# outside the namespace use the FQDN form <discoveryName>.<namespace>.
# ---------------------------------------------------------------------------
resource "aws_service_discovery_private_dns_namespace" "env" {
  name        = "{{ project }}-{{ env }}"
  vpc         = data.terraform_remote_state.project.outputs.vpc_id
  description = "ECS Service Connect namespace for {{ project }} {{ env }}"
  tags = {
    project    = "{{ project }}"
    env        = "{{ env }}"
    managed_by = "doctrine"
  }
}
```

Key changes:
- Resource type: `http_namespace` → `private_dns_namespace`.
- New `vpc` field referencing the master VPC ID via remote-state output.
- Updated comment block.

### Step 2 — Update the namespace reference in `hcl.py`

Edit `src/docex/emit/hcl.py:460`:

```python
# Before:
out.append("    namespace = aws_service_discovery_http_namespace.env.arn")

# After:
out.append("    namespace = aws_service_discovery_private_dns_namespace.env.arn")
```

### Step 3 — Verify no other references

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn 'aws_service_discovery_http_namespace\|service_discovery_http' src/ tests/
```

After steps 1 and 2, any remaining hits are bugs to fix. Likely all in test files asserting the old resource type — flip mechanically.

### Step 4 — Tests

#### `tests/integration/test_compile.py`

Find existing namespace assertions:

```bash
grep -n 'aws_service_discovery\|service_connect' tests/integration/test_compile.py
```

For each:
- Resource type assertion: `aws_service_discovery_http_namespace` → `aws_service_discovery_private_dns_namespace`.
- Add an assertion that the new `vpc = data.terraform_remote_state.project.outputs.vpc_id` field is present.
- Add an assertion that the `name = "<project>-<env>"` form is preserved.

#### `tests/unit/test_hcl_emitter.py`

Per-service `service_connect_configuration.namespace` assertion — flip resource type.

### Step 5 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 6 — Sanity sweep

```bash
# Old resource type gone
grep -rn 'aws_service_discovery_http_namespace\|service_discovery_http' src/ tests/

# New resource type present
grep -rn 'aws_service_discovery_private_dns_namespace' src/ tests/
```

First sweep: zero hits in `src/`; in `tests/` only as negative assertions if any. Second: hits in template + hcl.py + test files asserting the new shape.

## Out of scope

- **No `provides.host.elastic` changes.**
- **No EC2-traefik resources** — mod 044.
- **No master VPC changes** — mod 041 already added `vpc_id` to project-tier outputs.
- **No `test_projects/{fixed,elastic}/` edits.**

## Done criteria

- [ ] `aws_service_discovery_http_namespace.env` replaced with `aws_service_discovery_private_dns_namespace.env` in `main.tf.j2`.
- [ ] `vpc = data.terraform_remote_state.project.outputs.vpc_id` field added.
- [ ] Comment block updated to mention private DNS + VPC-wide DNS resolution.
- [ ] `hcl.py:460` namespace ARN reference uses the new resource type.
- [ ] Tests updated; assertions on both resource type and `vpc` field present.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.
- [ ] Sanity sweeps clean — zero hits on old resource type in `src/`.

Working tree dirty when finished. Do not commit.
