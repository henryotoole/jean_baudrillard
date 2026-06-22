# Mod 014 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Implement ECS Service Connect for intra-env service discovery on elastic. Emit one `aws_service_discovery_http_namespace` per env named `<project>_<env>`. Every `aws_ecs_service` gains a `service_connect_configuration` block; services with a declared port also register a `service {}` sub-block (discovery name = global name). Every container `portMappings` entry gains a `name` field (required by AWS for `port_name` referencing).

After this mod, a `web` core service magic-ref'ing `${backing_services.sidecar.host}` resolves to `proj_stage_sidecar` (the global name), and Service Connect's injected Envoy sidecar routes the traffic to sidecar's tasks. No transfer-table changes — the existing `provides.host.elastic: "${global_service_name}"` template already produces the right value.

The doctrine edits for this mod are already landed in `shape.md`. No further doctrine edits.

## Step 1 — Add the namespace resource to `main.tf.j2`

File: `src/docex/emit/templates/main.tf.j2`. Insert a new section after the ECS cluster (lines 174-181) and before the Services section (line 183). Use the existing section-comment style:

```jinja
# ---------------------------------------------------------------------------
# Service discovery — ECS Service Connect over a Cloud Map HTTP namespace.
# Per shape.md § Elastic-Foundation, one namespace per env. Services
# register themselves via service_connect_configuration on aws_ecs_service.
# ---------------------------------------------------------------------------
resource "aws_service_discovery_http_namespace" "env" {
  name        = "{{ project }}_{{ env }}"
  description = "ECS Service Connect namespace for {{ project }} {{ env }}"
  tags = {
    project    = "{{ project }}"
    env        = "{{ env }}"
    managed_by = "doctrine"
  }
}
```

No new Jinja context variable required — `project` and `env` are already in the render context.

## Step 2 — Extend `render_task_definition` to add `name` to port mappings

File: `src/docex/emit/hcl.py`. Around line 254-257 in `render_task_definition`:

Current:
```python
if svc.port is not None:
    container_def["portMappings"] = [
        {"containerPort": svc.port, "protocol": "tcp"}
    ]
```

New:
```python
if svc.port is not None:
    container_def["portMappings"] = [
        {
            "containerPort": svc.port,
            "protocol": "tcp",
            # Mod 014: name = short service name, referenced by
            # aws_ecs_service.service_connect_configuration.service.port_name.
            "name": svc.name,
        }
    ]
```

The migration task definition (the `_migrate` sub-emission later in the same function) has a different container — it doesn't take a port. No change needed there.

## Step 3 — Extend `render_ecs_service` with `service_connect_configuration`

File: `src/docex/emit/hcl.py`. The function is at line 328-352. After the `network_configuration` block and before (or after) the `load_balancer` block, add Service Connect configuration:

```python
def render_ecs_service(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit one ``aws_ecs_service``. References ``aws_lb_target_group``
    if the service also emits ``target_group`` (web-network services).
    Every service participates in the env's Service Connect namespace
    so intra-env name resolution works — services with a declared port
    register as discoverable; services without participate as clients
    only. Mod 014.
    """
    nets = list(svc.networks)
    out: list[str] = []
    out.append(f'resource "aws_ecs_service" "{svc.name}" {{')
    out.append(f'  name            = "{svc.global_name}"')
    out.append( '  cluster         = aws_ecs_cluster.cluster.id')
    out.append(f'  task_definition = aws_ecs_task_definition.{svc.name}.arn')
    out.append( '  launch_type     = "FARGATE"')
    out.append( '  desired_count   = 1')
    out.append("  network_configuration {")
    out.append("    subnets         = data.terraform_remote_state.project.outputs.private_subnet_ids")
    sg_refs = ", ".join(f"aws_security_group.{n}.id" for n in sorted(nets))
    out.append(f"    security_groups = [{sg_refs}]")
    out.append("  }")
    # Mod 014: Service Connect. Every service participates so it can
    # resolve peers. Services with a port also register a `service {}`
    # block so peers can resolve them.
    out.append("  service_connect_configuration {")
    out.append("    enabled   = true")
    out.append("    namespace = aws_service_discovery_http_namespace.env.arn")
    if svc.port is not None:
        out.append("    service {")
        out.append(f'      port_name      = "{svc.name}"')
        out.append(f'      discovery_name = "{svc.global_name}"')
        out.append("      client_alias {")
        out.append(f"        port     = {svc.port}")
        out.append(f'        dns_name = "{svc.global_name}"')
        out.append("      }")
        out.append("    }")
    out.append("  }")
    if "web" in nets and "target_group" in svc.emits.get("elastic", []):
        out.append("  load_balancer {")
        out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
        out.append(f'    container_name   = "{svc.name}"')
        out.append(f'    container_port   = {svc.port or 80}')
        out.append("  }")
    out.append("}")
    return "\n".join(out)
```

## Step 4 — Unit tests for the namespace emission

File: `tests/unit/test_hcl_emitter.py` (or wherever the existing emit-end-to-end tests live; locate the existing test that compiles a fixture and inspects `main.tf` content).

Add a test asserting the namespace appears:

```python
def test_service_connect_namespace_emitted_per_env():
    """Mod 014: one aws_service_discovery_http_namespace per env, named
    `<project>_<env>`."""
    # Compile the existing elastic fixture (mirror the pattern used in
    # neighboring tests in this file).
    ...
    main_tf = <the rendered main.tf for stage>
    assert 'resource "aws_service_discovery_http_namespace" "env"' in main_tf
    assert 'name        = "docex_smoke_elastic_stage"' in main_tf  # or whichever project name the fixture uses
```

If the test file uses a helper like `_compile_and_render_env(...)`, reuse it. Match the existing test style.

## Step 5 — Unit tests for the per-ECS-service Service Connect block

In `tests/unit/test_emit_dispatch.py` (created by Mod 013), add tests:

```python
def test_ecs_service_emits_service_connect_block_enabled():
    """Every aws_ecs_service has service_connect_configuration with enabled=true."""
    svc = _svc()
    rendered = render_ecs_service(svc, _ctx())
    assert "service_connect_configuration {" in rendered
    assert "enabled   = true" in rendered
    assert "namespace = aws_service_discovery_http_namespace.env.arn" in rendered


def test_ecs_service_with_port_registers_service_block():
    """A service with a declared port gets a `service {}` block inside SC config."""
    svc = _svc(port=80)
    rendered = render_ecs_service(svc, _ctx())
    assert 'port_name      = "sidecar"' in rendered
    assert 'discovery_name = "proj_stage_sidecar"' in rendered
    assert "client_alias {" in rendered
    assert 'dns_name = "proj_stage_sidecar"' in rendered
    assert "port     = 80" in rendered


def test_ecs_service_without_port_has_no_service_block():
    """A service without a port (e.g., a port-less worker) participates as a
    client only — no inner `service {}` block."""
    svc = _svc(name="worker", port=None)
    rendered = render_ecs_service(svc, _ctx())
    assert "service_connect_configuration {" in rendered
    assert "enabled   = true" in rendered
    # No inner service block — the `service {}` sub-block specifically
    # registers the task as discoverable; worker has nothing to register.
    assert "service {" not in rendered
    assert "client_alias {" not in rendered
    assert "discovery_name" not in rendered


def test_task_definition_port_mapping_has_name_field():
    """Port mappings carry `name = <short_service_name>` so Service Connect's
    port_name reference resolves."""
    svc = _svc(port=8080)
    rendered = render_task_definition(svc, _ctx())
    # The container_def is JSON-encoded via _hcl_value; look for the name in
    # the rendered output of the portMappings array.
    assert '"name": "sidecar"' in rendered
    assert '"containerPort": 8080' in rendered
```

## Step 6 — Existing test updates

Any existing test that asserts the exact text of an `aws_ecs_service` block or task definition's `portMappings` may need adjustment to accommodate:
- The new `service_connect_configuration` block on every ECS service.
- The new `"name": "<svc.name>"` field on every port mapping.

For tests that do substring presence checks (e.g., `assert 'resource "aws_ecs_service"' in rendered`), no change. For tests that do equality checks against full rendered strings, update the expected text or relax the assertion. Don't suppress assertions — adjust them to be correct against the new output.

Likely 3-5 tests need touching. Check `tests/unit/test_hcl_emitter.py` and `tests/unit/test_emit_dispatch.py`.

## Step 7 — Snapshot-equivalence sanity check

Run a compile of the existing elastic fixture (mirror what Mod 013's hand-off did — `tests/fixtures/sample_project_elastic` or similar) and visually inspect:
- One `aws_service_discovery_http_namespace.env` resource at the env tier.
- Every `aws_ecs_service` has `service_connect_configuration { enabled = true; namespace = ...; service { port_name = <name>; discovery_name = <global_name>; client_alias { port = ...; dns_name = ... } } }` (the inner `service {}` block only for services with a port).
- Every container `portMappings` entry has `"name": "<svc.name>"`.

No other unexpected changes to the emitted `main.tf` — non-Service-Connect blocks (target groups, listener rules, SGs, RDS, etc.) should be unchanged.

## Step 8 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/integration/test_compile.py -q
```

All must pass.

## Step 9 — Leave everything uncommitted

No git commits. Design-context LLM reviews before commit.

## Hand-off report

In ≤200 words:

- Files changed (group: hcl.py, main.tf.j2, tests).
- Test pass counts.
- Confirmation that the elastic fixture's `main.tf` emits the namespace + Service Connect blocks correctly. Name the fixture you compiled.
- Pre-existing tests that needed adjustment — count + what kind of change.
- Any decision beyond implementation.md, especially around:
  - The exact placement of `service_connect_configuration` within `render_ecs_service` (relative to `network_configuration` and `load_balancer`).
  - Test-fixture conventions in `tests/unit/test_emit_dispatch.py` (whether `_svc(port=...)` worked cleanly or needed extension).
- Anything that smelled off.

## Out of scope

- Service Connect traffic features: retries, timeouts, mTLS, circuit breakers. Future tuning mod if needed.
- Cloud Map private DNS namespace (the alternative service-discovery mechanism). Service Connect over an HTTP namespace is the choice.
- Envoy sidecar resource overhead in the doctrine's resource sizing prose. Worth a future doctrine note but not in this mod.
- Cross-env service discovery. A service in `stage` cannot resolve a service in `prod` — each env has its own namespace. By design.
- Service Connect on fixed. Docker network DNS already resolves names there; no work needed.
