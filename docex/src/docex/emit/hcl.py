"""Emit a per-env ``main.tf`` for elastic-foundation envs.

The HCL is rendered via Jinja2 from a template. Per service, the
emitter dispatches by the engine's declared elastic emit destinations
(``engine.emits.elastic``), not by engine name and not by ``is_core``.
Each destination has a dedicated per-destination renderer; the
``_DESTINATION_RENDERERS`` table picks the right one. See Mod 013.

Phase 4 hardening still applies:

- Block-attribute formatting (no inline-semicolon blocks in the
  Jinja template — fixed via ``main.tf.j2``).
- Fargate ``(cpu, memory)`` pair validation (fixed via
  :mod:`docex.cicl.fargate` and the compiler's ``_resources_to_elastic``).
- Ephemeral storage floor 21 GiB / ceiling 200 GiB (same).
- ``$[VAR]`` → ECS ``secrets[]`` block, not literal ``environment[]``
  entries. A core service env value that is a bare ``$[REF]`` becomes
  a ``secrets[]`` entry named after the *consumer's* env key, whose
  ``valueFrom`` points at ``/<project>/<env>/<REF>`` in SSM Parameter
  Store. Naming by the consumer's key (not ``REF``) keeps the
  container's env-var surface identical to the fixed/compose side.
- RDS password / username sourced from ``data "aws_ssm_parameter"``
  rather than emitted as a literal ``"$[POSTGRES_PASSWORD]"``. Handled
  by ``_substitute_body_ssm_refs`` and visible to every renderer.
- Listener-rule ``host_header.values`` set to per-service hosts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from docex import ELASTIC_REGION, OTEL_COLLECTOR_IMAGE
from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.substitute import HCLLiteral
from docex.emit.otelcol import render_otelcol_config
from docex.naming import NamingPolicies, NamingPolicy, apply_policy


_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Match a runtime-ref token ``$[VAR]`` inside a value string. Used to
# detect (and extract) which entries on a core service's env block must
# move to the secrets[] block, plus the SSM substitution in backing
# service bodies.
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


def _hcl_value(value: Any, indent: int = 2) -> str:
    """Format a Python value as HCL syntax.

    Strings: quoted, unless wrapped in ``HCLLiteral``.
    Numbers/bools: emitted as-is.
    Lists/dicts: HCL block/list syntax.
    """
    pad = " " * indent
    if isinstance(value, HCLLiteral):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    if isinstance(value, str):
        # Escape backslashes, double-quotes, HCL interpolation `$`,
        # and control whitespace. Order matters:
        #   1. Backslash-replace MUST go first so subsequent
        #      replacements don't double-escape their own backslashes.
        #   2. `$$` doubling (mod 026) escapes HCL's own template-
        #      interpolation syntax. HCL parses `$${...}` back to a
        #      literal `${...}` in the string value, which is what
        #      otelcol's env: config provider expects in the
        #      OTEL_CONFIG_YAML payload. HCLLiteral-wrapped values
        #      bypass this branch entirely so legitimate HCL
        #      expressions stay un-escaped.
        #   3. Newline / CR / tab escape (mod 025) — HCL's quoted-
        #      string grammar rejects literal whitespace control
        #      chars; emitted as `\n` etc.
        esc = (
            value.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("$", "$$")
                 .replace("\n", "\\n")
                 .replace("\r", "\\r")
                 .replace("\t", "\\t")
        )
        return f'"{esc}"'
    if isinstance(value, list):
        parts = [_hcl_value(v, indent + 2) for v in value]
        return "[" + ", ".join(parts) + "]"
    if isinstance(value, dict):
        lines = ["{"]
        for k in sorted(value.keys()):
            v = value[k]
            lines.append(f"{pad}  {k} = {_hcl_value(v, indent + 2)}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    return f'"{value}"'


def _hcl_block_body(body: dict[str, Any], indent: int = 2) -> str:
    """Render a dict as HCL block body (no surrounding braces).

    Keys whose value is a dict are emitted as ``key = {...}`` (HCL
    attribute syntax), not ``key {...}`` (HCL block syntax). The two
    are equivalent for most resources but block syntax is reserved for
    well-known sub-resources like ``ephemeral_storage``. Phase 1's
    HCL emit prefers attribute form for safety.
    """
    pad = " " * indent
    lines: list[str] = []
    for k in sorted(body.keys()):
        v = body[k]
        lines.append(f"{pad}{k} = {_hcl_value(v, indent)}")
    return "\n".join(lines)


def _ssm_arn_literal(project: str, env: str, var: str) -> HCLLiteral:
    """Return an HCL literal for the SSM ARN of a per-env secret.

    Uses ``data.aws_caller_identity.current.account_id`` so the
    compile stage does not need AWS credentials to resolve the account
    ID; OpenTofu resolves it at apply time.
    """
    # NOTE: the leading ``"`` and trailing ``"`` are part of the
    # returned literal — it's a JSON string inside an HCL ``jsonencode``,
    # with HCL interpolation embedded via ``${...}``.
    return HCLLiteral(
        f'"arn:aws:ssm:{ELASTIC_REGION}:${{data.aws_caller_identity.current.account_id}}'
        f':parameter/{project}/{env}/{var}"'
    )


def _ssm_data_name(svc_name: str, key: str) -> str:
    """Form a deterministic data-source name for an SSM-backed value.

    Hyphens in service names are converted to underscores because HCL
    identifiers don't permit hyphens. ``key`` (an env-var name like
    ``POSTGRES_PASSWORD``) is downcased for readability.
    """
    safe = svc_name.replace("-", "_")
    return f"{safe}_{key.lower()}"


# ---------------------------------------------------------------------------
# Dispatch context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RenderCtx:
    """Shared state passed to every per-destination renderer.

    Each renderer takes ``(svc, ctx)``; the ctx carries what the
    bulk-emit loop has already resolved (project name, env name, ALB
    naming policy, ALB listener priority per web service,
    observability backend URL for the paired OTel sidecar).
    """

    project: str
    env: str
    alb_policy: NamingPolicy
    priorities: dict[str, int]  # service_name -> ALB listener_rule.priority
    # Mod 018: sidecar exporter target. Defaults to empty for unit tests
    # constructing a ctx by hand; real compiles thread it through from
    # `compiled.observability_backend_url`.
    observability_backend_url: str = ""


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------


def _substitute_body_ssm_refs(
    body: dict[str, Any], project: str, env: str, svc_name: str
) -> tuple[dict[str, Any], list[str]]:
    """Walk a service body, translating each ``$[VAR]`` token into an
    HCL reference to a ``data "aws_ssm_parameter"`` block.

    Returns the substituted body and the list of data-source HCL strings
    to emit alongside the resource blocks. Lifted from the previous
    ``render_backing`` so every per-destination renderer sees the same
    substituted body — a value that is a bare ``$[VAR]`` becomes
    ``data.aws_ssm_parameter.<svc>_<var>.value``, and a data block is
    emitted at ``/<project>/<env>/<VAR>``.
    """
    data_sources: list[str] = []
    seen_keys: set[str] = set()

    def maybe_substitute(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        m = _RUNTIME_REF_RE.fullmatch(value)
        if m is None:
            return value
        key = m.group(1)
        if key not in seen_keys:
            seen_keys.add(key)
            ds_name = _ssm_data_name(svc_name, key)
            data_sources.append(
                f'data "aws_ssm_parameter" "{ds_name}" {{\n'
                f'  name            = "/{project}/{env}/{key}"\n'
                f'  with_decryption = true\n'
                f'}}'
            )
        ds_name = _ssm_data_name(svc_name, key)
        return HCLLiteral(f"data.aws_ssm_parameter.{ds_name}.value")

    return {k: maybe_substitute(v) for k, v in body.items()}, data_sources


def _container_env_entries(
    env: dict[str, Any], project: str, env_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition a service's env block into ``environment[]`` and
    ``secrets[]`` entries for an ECS container definition.

    Plain strings and HCLLiteral (``@``-pass-through) values become
    ``environment[]`` entries. A value that is a bare ``$[REF]`` token
    becomes a ``secrets[]`` entry whose ``valueFrom`` points at the
    underlying SSM parameter (named by the *consumer's* key, keeping
    parity with the compose side).
    """
    env_entries: list[dict[str, Any]] = []
    secret_entries: list[dict[str, Any]] = []
    for k in sorted(env):
        v = env[k]
        if isinstance(v, HCLLiteral):
            # @-pass-through (e.g. RDS endpoint). Embed as an HCL
            # interpolation inside the JSON string.
            env_entries.append({"name": k, "value": HCLLiteral(f'"${{{str(v)}}}"')})
            continue
        if isinstance(v, str):
            m = _RUNTIME_REF_RE.fullmatch(v)
            if m is not None:
                secret_entries.append({
                    "name": k,
                    "valueFrom": _ssm_arn_literal(project, env_name, m.group(1)),
                })
                continue
            env_entries.append({"name": k, "value": v})
            continue
        env_entries.append({"name": k, "value": str(v)})
    return env_entries, secret_entries


# ---------------------------------------------------------------------------
# Per-destination renderers
# ---------------------------------------------------------------------------


def render_task_definition(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit one ``aws_ecs_task_definition``, plus a ``_migrate`` variant
    for schema-owning core services.

    Shared between core services and container-backing services — the
    is_core gate applies only to the migration sub-emission and the
    fact that backing services arrive with ``svc.env == {}`` (so
    PROJECT_VERSION and other doctrine-injected env vars naturally
    skip them).
    """
    body = dict(svc.body)
    cpu = body.get("cpu", "256")
    memory = body.get("memory", "512")
    ephemeral = body.get("ephemeral_storage")

    env_entries, secret_entries = _container_env_entries(svc.env, ctx.project, ctx.env)

    container_def: dict[str, Any] = {
        "name": svc.name,
        "image": body.get("image", ""),
        "essential": True,
    }
    if svc.port is not None:
        container_def["portMappings"] = [
            {
                "containerPort": svc.port,
                "protocol": "tcp",
                # WHY: Service Connect requires a named port mapping —
                # aws_ecs_service.service_connect_configuration.service.port_name
                # dereferences this. Mod 014.
                "name": svc.name,
            }
        ]
    if env_entries:
        container_def["environment"] = env_entries
    if secret_entries:
        container_def["secrets"] = secret_entries

    # Mod 015: persistent storage wiring. When the engine declares
    # `persistent_storage`, mount the per-service EFS at the declared path
    # inside the container. Volume name is the doctrine-fixed handle "data".
    task_volumes: list[dict[str, Any]] = []
    if svc.persistent_storage:
        mount_path = svc.persistent_storage["mount_path"]
        container_def["mountPoints"] = [{
            "sourceVolume": "data",
            "containerPath": mount_path,
            "readOnly": False,
        }]
        task_volumes.append({
            "name": "data",
            "file_system_id": HCLLiteral(f"aws_efs_file_system.{svc.name}.id"),
            "transit_encryption": "ENABLED",
        })

    # Mod 018: paired OTel Collector sidecar for every core service. Shares
    # the task netns (ECS task containers always do), config embedded as a
    # literal YAML in OTEL_CONFIG_YAML so no file mount is needed, API key
    # delivered via ECS secrets[] from SSM. Backing services (and the
    # migration task below) don't get sidecars — they emit no
    # application-origin signals.
    # Mod 024: dependsOn condition is START rather than HEALTHY because
    # the otel/opentelemetry-collector image is built FROM scratch and
    # has no probe tool (wget/curl/shell absent). A HEALTHY condition
    # would block the core container indefinitely. The OTel SDK's
    # default batch queue (2048 spans, 5 s flush) absorbs anything
    # emitted in the brief sidecar-start → OTLP-listening window.
    sidecar_def: dict[str, Any] | None = None
    if svc.is_core:
        container_def["dependsOn"] = [
            {"containerName": f"{svc.name}-otelcol", "condition": "START"},
        ]
        sidecar_def = {
            "name": f"{svc.name}-otelcol",
            "image": OTEL_COLLECTOR_IMAGE,
            "essential": False,
            "command": ["--config=env:OTEL_CONFIG_YAML"],
            "cpu": 102,        # 0.1 vCPU in Fargate units
            "memory": 128,
            "environment": [
                {"name": "OTEL_CONFIG_YAML",
                 "value": render_otelcol_config(ctx.env)},
                {"name": "OBSERVABILITY_BACKEND_URL",
                 "value": ctx.observability_backend_url},
            ],
            "secrets": [
                {"name": "TELEMETRY_API_KEY",
                 "valueFrom": _ssm_arn_literal(
                     ctx.project, ctx.env, "TELEMETRY_API_KEY")},
            ],
        }

    project_tag = svc.body.get("tags", {}).get("project", "")
    env_tag = svc.body.get("tags", {}).get("env", "")

    out: list[str] = []
    out.append(f'resource "aws_ecs_task_definition" "{svc.name}" {{')
    out.append(f'  family                   = "{svc.global_name}"')
    out.append( '  requires_compatibilities = ["FARGATE"]')
    out.append( '  network_mode             = "awsvpc"')
    out.append(f'  cpu                      = "{cpu}"')
    out.append(f'  memory                   = "{memory}"')
    # Fargate requires execution_role_arn for ECR image pulls and SSM
    # secret decryption. The role is provisioned at the project tier
    # so every env in the project shares one role identity.
    out.append( '  execution_role_arn       = data.terraform_remote_state.project.outputs.task_execution_role_arn')
    if ephemeral:
        out.append("  ephemeral_storage {")
        out.append(f"    size_in_gib = {ephemeral.get('size_in_gib', 21)}")
        out.append("  }")
    # Mod 015: EFS volume blocks for stateful container-backing services.
    for vol in task_volumes:
        out.append("  volume {")
        out.append(f'    name = "{vol["name"]}"')
        out.append("    efs_volume_configuration {")
        # file_system_id is an HCLLiteral — emit unquoted.
        out.append(f'      file_system_id     = {vol["file_system_id"]}')
        out.append(f'      transit_encryption = "{vol["transit_encryption"]}"')
        out.append("    }")
        out.append("  }")
    out.append("  container_definitions = jsonencode([")
    out.append(f"    {_hcl_value(container_def, indent=4)},")
    if sidecar_def is not None:
        out.append(f"    {_hcl_value(sidecar_def, indent=4)},")
    out.append("  ])")
    out.append(
        f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
        f'service = "{svc.name}", role = "{svc.role}", '
        f'managed_by = "doctrine" }}'
    )
    out.append("}")

    # Migration task definition: same image as main, but command runs
    # /service/migrate.sh. Emitted only for core services that own a
    # backing database schema. Backing services never own schemas, so
    # this sub-emission is implicitly skipped for them. No sidecar is
    # paired here: migration is one-shot, emits no application-origin
    # telemetry signals (Mod 018).
    if svc.is_core and svc.schema_owned_by_db:
        out.append("")
        # WHY: `-migrate` suffix (mod 030) — task family is a data-plane
        # resolvable ECS identifier, so the joiner uses the unified hyphen.
        mig_family = f"{svc.global_name}-migrate"
        mig_container = {
            "name": svc.name,
            "image": body.get("image", ""),
            "essential": True,
            "command": ["/service/migrate.sh"],
        }
        if env_entries:
            mig_container["environment"] = env_entries
        if secret_entries:
            mig_container["secrets"] = secret_entries
        out.append(f'resource "aws_ecs_task_definition" "{svc.name}_migrate" {{')
        out.append(f'  family                   = "{mig_family}"')
        out.append( '  requires_compatibilities = ["FARGATE"]')
        out.append( '  network_mode             = "awsvpc"')
        out.append(f'  cpu                      = "{cpu}"')
        out.append(f'  memory                   = "{memory}"')
        out.append( '  execution_role_arn       = data.terraform_remote_state.project.outputs.task_execution_role_arn')
        out.append("  container_definitions = jsonencode([")
        out.append(f"    {_hcl_value(mig_container, indent=4)},")
        out.append("  ])")
        out.append(
            f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
            f'service = "{svc.name}", role = "migrate", '
            f'managed_by = "doctrine" }}'
        )
        out.append("}")

    return "\n".join(out)


def render_ecs_service(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit one ``aws_ecs_service``. References ``aws_lb_target_group``
    if the service also emits ``target_group`` (web-network services).
    Every service participates in the env's Service Connect namespace so
    intra-env name resolution works — services with a declared port
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
    # WHY: single-element subnet list pins ECS task placement to the primary
    # AZ per cicl.md § Simplifications. ALB+RDS+EFS still span both AZs to
    # satisfy AWS's multi-AZ subnet-group requirements; workloads do not.
    out.append("    subnets         = [data.terraform_remote_state.project.outputs.primary_private_subnet_id]")
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


def render_target_group(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_lb_target_group`` + ``aws_lb_listener_rule`` for a
    web-network service. The dispatcher only calls this when
    ``web in svc.networks`` (per ``_destination_applicable``).
    """
    # ALB target-group names disallow underscores, so the name is
    # policy-translated regardless of the engine's own naming.
    tg_name = apply_policy(f"{svc.global_name}_tg", ctx.alb_policy)
    priority = ctx.priorities.get(svc.name, 100)

    out: list[str] = []
    out.append(f'resource "aws_lb_target_group" "{svc.name}" {{')
    out.append(f'  name        = "{tg_name}"')
    out.append(f'  port        = {svc.port or 80}')
    out.append( '  protocol    = "HTTP"')
    out.append( '  target_type = "ip"')
    out.append( '  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id')
    tg_extras = svc.target_extras.get("target_group", {})
    hc = tg_extras.get("health_check")
    if hc:
        out.append("  health_check {")
        # Python dicts preserve insertion order, so iteration matches the
        # field-translation declaration order from the transfer table.
        for k, v in hc.items():
            if isinstance(v, str):
                out.append(f'    {k} = "{v}"')
            else:
                out.append(f'    {k} = {v}')
        out.append("  }")
    out.append("}")
    out.append("")
    out.append(f'resource "aws_lb_listener_rule" "{svc.name}" {{')
    out.append( '  listener_arn = data.terraform_remote_state.project.outputs.alb_https_listener_arn')
    out.append(f'  priority     = {priority}')
    out.append( '  action {')
    out.append( '    type             = "forward"')
    out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
    out.append( '  }')
    out.append( '  condition {')
    out.append( '    host_header {')
    # Per-service host(s): <service>.<env>.<project>.<apex_domain>, plus
    # the bare <env>.<project>.<apex_domain> for the
    # domain_default_service; prod's default service also picks up
    # <project>.<apex_domain>.
    hosts_hcl = ", ".join(f'"{h}"' for h in svc.web_hosts)
    out.append(f'      values = [{hosts_hcl}]')
    out.append( '    }')
    out.append( '  }')
    out.append("}")
    return "\n".join(out)


def render_rds_instance(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_db_instance`` + ``aws_db_subnet_group`` for an
    RDS-backed backing service (currently: postgres engine).
    """
    body = dict(svc.body)
    # Doctrine invariant: `identifier` maps to RDS's `identifier` field.
    body["identifier"] = body.pop("identifier", svc.global_name)
    # Strip keys we don't emit on aws_db_instance.
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)

    nets = list(svc.networks)
    body.pop("networks", None)
    if nets:
        body["vpc_security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["db_subnet_group_name"] = HCLLiteral(
            f"aws_db_subnet_group.{svc.name}.name"
        )

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_db_instance" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    if nets:
        out.append("")
        out.append(f'resource "aws_db_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    return "\n".join(out)


def render_elasticache_cluster(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_elasticache_cluster`` + ``aws_elasticache_subnet_group``."""
    body = dict(svc.body)
    body["cluster_id"] = body.pop("identifier", svc.global_name)
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)

    nets = list(svc.networks)
    body.pop("networks", None)
    if nets:
        body["security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["subnet_group_name"] = HCLLiteral(
            f"aws_elasticache_subnet_group.{svc.name}.name"
        )

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_elasticache_cluster" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    if nets:
        out.append("")
        out.append(f'resource "aws_elasticache_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    return "\n".join(out)


def render_s3_bucket(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_s3_bucket``. No subnet group / SG — S3 is a regional
    service with its own access controls, not a VPC resource.
    """
    body = dict(svc.body)
    body["bucket"] = body.pop("identifier", svc.global_name)
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)
    body.pop("networks", None)

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_s3_bucket" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    return "\n".join(out)


def render_efs_file_system(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_efs_file_system`` + per-private-subnet
    ``aws_efs_mount_target`` for a stateful container-backing service.
    Emits ``aws_efs_backup_policy`` only when the service's
    ``target_extras["efs_file_system"]["enabled"]`` is truthy
    (project-opt-in via ``backups: true`` in infra.yml). Mod 015.
    """
    # WHY: Mount targets attach to the service's non-`web` SGs. The
    # `internal` SG's self-ingress rule already covers NFS port 2049
    # for tasks on that SG. EFS never lives on the public `web` plane.
    sg_nets = [n for n in sorted(svc.networks) if n != "web"]
    sg_refs = ", ".join(f"aws_security_group.{n}.id" for n in sg_nets)

    project_tag = svc.body.get("tags", {}).get("project", "")
    env_tag = svc.body.get("tags", {}).get("env", "")

    out: list[str] = []
    out.append(f'resource "aws_efs_file_system" "{svc.name}" {{')
    out.append(f'  creation_token   = "{svc.global_name}"')
    out.append( '  encrypted        = true')
    out.append( '  performance_mode = "generalPurpose"')
    out.append( '  throughput_mode  = "bursting"')
    out.append(
        f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
        f'service = "{svc.name}", role = "{svc.role}", '
        f'managed_by = "doctrine" }}'
    )
    out.append("}")

    # AWS Backup default plan — project-opt-in via the `backups` field.
    backups_extras = svc.target_extras.get("efs_file_system", {})
    if backups_extras.get("enabled"):
        out.append("")
        out.append(f'resource "aws_efs_backup_policy" "{svc.name}" {{')
        out.append(f'  file_system_id = aws_efs_file_system.{svc.name}.id')
        out.append("  backup_policy {")
        out.append('    status = "ENABLED"')
        out.append("  }")
        out.append("}")

    # One mount target per private subnet so tasks in any AZ can mount.
    out.append("")
    out.append(f'resource "aws_efs_mount_target" "{svc.name}" {{')
    out.append( '  count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)')
    out.append(f'  file_system_id  = aws_efs_file_system.{svc.name}.id')
    out.append( '  subnet_id       = data.terraform_remote_state.project.outputs.private_subnet_ids[count.index]')
    out.append(f'  security_groups = [{sg_refs}]')
    out.append("}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_DESTINATION_RENDERERS: dict[str, Callable[[CompiledService, _RenderCtx], str]] = {
    "task_definition": render_task_definition,
    "ecs_service": render_ecs_service,
    "target_group": render_target_group,
    "rds_instance": render_rds_instance,
    "elasticache_cluster": render_elasticache_cluster,
    "s3_bucket": render_s3_bucket,
    "efs_file_system": render_efs_file_system,  # Mod 015
}


def _destination_applicable(dest: str, svc: CompiledService) -> bool:
    """Check whether ``dest`` is conditionally emittable for ``svc``.

    Currently only ``target_group`` has a condition — it requires the
    service to be on the ``web`` network. The doctrine doesn't forbid
    an engine from declaring ``target_group`` even when no actual
    service of that engine would be web-routed; the gate just keeps
    the emit aligned with runtime reachability.
    """
    if dest == "target_group":
        return "web" in svc.networks
    return True


def render_service(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Render every elastic destination the service's engine declares.

    Data sources (SSM substitutions) come first, then the per-destination
    resource blocks in the order the engine declared them.
    """
    substituted_body, data_sources = _substitute_body_ssm_refs(
        svc.body, ctx.project, ctx.env, svc.name
    )
    svc_view = replace(svc, body=substituted_body)

    parts: list[str] = []
    if data_sources:
        parts.extend(data_sources)
        parts.append("")  # blank line between data sources and resources

    emits_elastic = svc.emits.get("elastic", [])
    for dest in emits_elastic:
        if not _destination_applicable(dest, svc):
            continue
        renderer = _DESTINATION_RENDERERS.get(dest)
        if renderer is None:
            # Should be impossible after Mod 012's load-time validation
            # (unknown destinations are rejected then). Defensive.
            parts.append(
                f"# unknown destination {dest!r} for service {svc.name!r}; no HCL emitted"
            )
            continue
        parts.append(renderer(svc_view, ctx))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Top-level emitters
# ---------------------------------------------------------------------------


def _hcl_id(service_name: str) -> str:
    """Normalize a service name into a valid HCL identifier.

    Service names may use hyphens, but tofu resource/output identifiers
    cannot — the bracket form would be required to dereference them,
    which complicates downstream HCL. We normalize to underscores so the
    same name works in `aws_ecr_repository.<id>` and
    `outputs.ecr_repository_<id>_url`.
    """
    return service_name.replace("-", "_")


def emit_hcl_project(
    *,
    project: str,
    project_version: str,
    apex_domain: str,
    core_service_names: list[str],
    naming_policies: NamingPolicies,
    out_path: Path,
) -> None:
    """Emit the project-tier ``main.tf``.

    One copy per project (NOT per env). Backs every elastic env via
    ``data "terraform_remote_state" "project"``. The state lives under
    ``key = "project/terraform.tfstate"`` in the same S3 backend the
    bootstrap creates. The bootstrap runs ``tofu apply`` against this
    HCL before any env-tier apply can succeed.
    """
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template("project.tf.j2")
    svc_entries = [
        {"name": name, "hcl_id": _hcl_id(name)}
        for name in sorted(core_service_names)
    ]
    # Resolve every structural-resource name through its policy before
    # the template runs — policies live in transfer tables, template
    # stays free of identifier logic.
    s3_p = naming_policies.get("s3")
    ddb_p = naming_policies.get("ddb")
    iam_p = naming_policies.get("iam")
    ssm_p = naming_policies.get("ssm_path")
    alb_p = naming_policies.get("alb")

    # WHY: ECR repo names are structural — `${project}/${service}` with each
    # segment verbatim and `/` as joiner. The single-separator policy
    # machinery cannot express this shape; per transfer_tables.md
    # "How structural emitters reference a policy", ECR joins the small set
    # of structural emit sites that bypass the policy table.
    ecr_repo_names = {
        name: f"{project}/{name}"
        for name in core_service_names
    }
    rendered = tpl.render(
        project=project,
        project_version=project_version,
        apex_domain=apex_domain,
        region=ELASTIC_REGION,
        core_service_names=svc_entries,
        state_bucket=apply_policy(f"{project}_tofu_state", s3_p),
        state_lock_table=apply_policy(f"{project}_tofu_locks", ddb_p),
        task_execution_role_name=apply_policy(
            f"{project}_task_execution", iam_p
        ),
        task_execution_policy_name=apply_policy(
            f"{project}_task_execution", iam_p
        ),
        ecr_repo_names=ecr_repo_names,
        ssm_path_project=apply_policy(project, ssm_p),
        alb_name=apply_policy(f"{project}_alb", alb_p),
        alb_sg_name=apply_policy(f"{project}_alb_sg", alb_p),
    )
    out_path.write_text(rendered)


def emit_hcl(
    compiled: CompiledEnv,
    out_path: Path,
    *,
    naming_policies: NamingPolicies,
) -> None:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template("main.tf.j2")

    # Order: backing services first, then core services. Alphabetical
    # within each group. Purely cosmetic (tofu builds its own DAG), but
    # keeps the emitted main.tf readable and matches the pre-Mod-013 layout.
    backing = sorted(
        (s for s in compiled.services.values() if not s.is_core),
        key=lambda s: s.name,
    )
    core = sorted(
        (s for s in compiled.services.values() if s.is_core),
        key=lambda s: s.name,
    )
    services_ordered = backing + core

    # ALB listener rules need a unique priority per web-network core service.
    # Mod 038: stage and prod share the project-tier ALB's HTTPS listener,
    # so priorities are banded by env to keep their rule namespaces
    # collision-free: stage in [1000, 4999], prod in [5000, 9999]. Within
    # each band, services are assigned deterministically by sorted name.
    _ENV_PRIORITY_BASE = {"stage": 1000, "prod": 5000}
    _web_core = [s for s in core if "web" in s.networks]
    _base = _ENV_PRIORITY_BASE.get(compiled.env, 100)
    priorities = {s.name: _base + i for i, s in enumerate(_web_core)}

    s3_p = naming_policies.get("s3")
    ddb_p = naming_policies.get("ddb")
    alb_p = naming_policies.get("alb")
    ecs_p = naming_policies.get("ecs")

    ctx = _RenderCtx(
        project=compiled.project,
        env=compiled.env,
        alb_policy=alb_p,
        priorities=priorities,
        observability_backend_url=compiled.observability_backend_url,
    )

    def _render(svc: CompiledService) -> str:
        return render_service(svc, ctx)

    rendered = tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        apex_domain=compiled.apex_domain,
        subdomain=compiled.subdomain,
        region=ELASTIC_REGION,
        networks_sorted=sorted(compiled.networks),
        services=services_ordered,
        render_service=_render,
        state_bucket=apply_policy(
            f"{compiled.project}_tofu_state", s3_p
        ),
        state_lock_table=apply_policy(
            f"{compiled.project}_tofu_locks", ddb_p
        ),
        ecs_cluster_name=apply_policy(
            f"{compiled.project}_{compiled.env}", ecs_p
        ),
    )
    out_path.write_text(rendered)
