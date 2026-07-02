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
from docex.emit.tags import render_hcl_tags, standard_tags
from docex.naming import NamingPolicies, NamingPolicy, apply_policy


_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Match a runtime-ref token ``$[VAR]`` inside a value string. Used to
# detect (and extract) which entries on a core service's env block must
# move to the secrets[] block, plus the SSM substitution in backing
# service bodies.
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")

# A bare HCL identifier: letters/underscore start, then letters/digits/
# underscore/hyphen. Object keys not matching this must be quoted (a dot
# would otherwise be parsed as a resource-reference traversal). Used by
# _hcl_value's dict branch.
_HCL_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


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
            # HCL object keys that aren't bare identifiers must be quoted, or
            # HCL parses them as a resource-reference traversal. Identifiers
            # permit [A-Za-z0-9_-] (hyphens OK — e.g. `awslogs-group`); a dot
            # is not allowed, so the traefik.* dockerLabels keys (Mod 070) get
            # quoted here. Bare-identifier keys stay unquoted, preserving the
            # existing emit shape everywhere else.
            key = k if _HCL_IDENT_RE.fullmatch(k) else _hcl_value(k)
            lines.append(f"{pad}  {key} = {_hcl_value(v, indent + 2)}")
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


def _log_configuration(
    project: str, env: str, svc_name: str, stream_prefix: str
) -> dict[str, Any]:
    """Build an ``awslogs`` ``logConfiguration`` for an ECS container.

    All three container kinds in a service's task definitions (app, OTel
    sidecar, ``_migrate``) share one per-(env, service) CloudWatch log
    group, distinguished only by ``awslogs-stream-prefix``.

    WHY ``project`` (raw, underscore-preserving): the log-group ``name``
    prefix ``/<project>/<env>/`` must match the task-execution role's IAM
    ``log-group:/<ssm_path_project>/<env>/*`` scope. The ``ssm_path``
    naming policy preserves underscores (matching the SSM ARN prefix in
    :func:`_ssm_arn_literal`), so the group name must use the same raw
    project form — *not* the dns-label form. ``awslogs-create-group`` is
    deliberately omitted: the role lacks ``CreateLogGroup``; tofu owns the
    group (see ``aws_cloudwatch_log_group`` emitted alongside).
    """
    return {
        "logDriver": "awslogs",
        "options": {
            "awslogs-group": HCLLiteral(
                f"aws_cloudwatch_log_group.{svc_name}.name"
            ),
            "awslogs-region": ELASTIC_REGION,
            "awslogs-stream-prefix": stream_prefix,
        },
    }


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
    # Mod 055: IAM naming policy, used to name the per-scheduler-service
    # EventBridge-Scheduler invocation role. Optional with a None default so
    # unit tests constructing a ctx by hand keep working; real compiles
    # thread it through from the transfer tables' naming policies.
    iam_policy: NamingPolicy | None = None
    # Mod 018: sidecar exporter target. Defaults to empty for unit tests
    # constructing a ctx by hand; real compiles thread it through from
    # `compiled.observability_backend_url`.
    observability_backend_url: str = ""
    # Mod 044: reverse-proxy variant. Controls env-tier emission of
    # ALB-specific resources (listener rules). Defaults to "alb" so unit
    # tests constructing a ctx by hand keep the legacy emit shape.
    reverse_proxy: str = "alb"


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
        # Mod 052 (Gap E): Class-2 diagnostic stdout/stderr → CloudWatch.
        "logConfiguration": _log_configuration(
            ctx.project, ctx.env, svc.name, "app"
        ),
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

    # Mod 070: on the ec2_traefik path, the project traefik discovers routes
    # from these container labels via its ECS provider (the elastic analog of
    # the fixed docker provider). No labels on the alb path — it routes via
    # listener rules. Web-network core services with a port only.
    if (
        ctx.reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip")
        and "web" in svc.networks
        and svc.port is not None
        and svc.web_hosts
    ):
        key = f"{svc.name}-{ctx.env}"
        rule = " || ".join(f"Host(`{h}`)" for h in svc.web_hosts)
        container_def["dockerLabels"] = {
            "traefik.enable": "true",
            f"traefik.http.routers.{key}.rule": rule,
            f"traefik.http.routers.{key}.entrypoints": "websecure",
            f"traefik.http.routers.{key}.tls.certresolver": "doctrine",
            f"traefik.http.routers.{key}.service": key,
            f"traefik.http.services.{key}.loadbalancer.server.port": str(svc.port),
        }

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
    # Mod 055: the sidecar pairs only with long-running services — those
    # that also emit `ecs_service`. A one-shot task (scheduler RunTask, and
    # implicitly the `_migrate` task below) has no place for it: nothing
    # stays up to share the netns and flush the batch, and a non-essential
    # sidecar on a RunTask just lingers after the job exits. Consistent
    # with the fixed side, where the one-off job container has no sidecar.
    has_ecs_service = "ecs_service" in svc.emits.get("elastic", [])
    sidecar_def: dict[str, Any] | None = None
    if svc.is_core and has_ecs_service:
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
            # Mod 052 (Gap E): the sidecar's own stdout/stderr (startup,
            # crashes, the dev `debug` exporter dump) → the shared group.
            "logConfiguration": _log_configuration(
                ctx.project, ctx.env, svc.name, "otelcol"
            ),
        }

    # Mod 060: shape_name distinguishes the per-service tier; the task
    # definition's own resources (log group, task-def, _migrate) carry
    # core_service/backing_service per `svc.is_core`.
    td_shape = "core_service" if svc.is_core else "backing_service"

    out: list[str] = []
    # Mod 052 (Gap E): one CloudWatch log group per (env, service). The
    # app container, the OTel sidecar, and the `_migrate` container all
    # write here, distinguished by `awslogs-stream-prefix`. The `name`'s
    # `/<project>/<env>/` prefix uses the raw (underscore-preserving)
    # project form so it falls under the task-execution role's IAM
    # `log-group:/<ssm_path_project>/<env>/*` scope (the `ssm_path`
    # naming policy preserves underscores — see _log_configuration).
    out.append(f'resource "aws_cloudwatch_log_group" "{svc.name}" {{')
    out.append(f'  name              = "/{ctx.project}/{ctx.env}/{svc.name}"')
    out.append( '  retention_in_days = 30')
    out.append(render_hcl_tags(standard_tags(
        "environment", shape_name=td_shape, descriptor="logs",
        project=ctx.project, env=ctx.env, service=svc.name, role=svc.role,
    )))
    out.append("}")
    out.append("")
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
    out.append(render_hcl_tags(standard_tags(
        "environment", shape_name=td_shape, descriptor="task-def",
        project=ctx.project, env=ctx.env, service=svc.name, role=svc.role,
    )))
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
            # Mod 052 (Gap E): migration stdout is the headline Class-2
            # case — a failing `migrate.sh` was previously invisible.
            "logConfiguration": _log_configuration(
                ctx.project, ctx.env, svc.name, "migrate"
            ),
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
        out.append(render_hcl_tags(standard_tags(
            "environment", shape_name="core_service",
            descriptor="migrate-task-def",
            project=ctx.project, env=ctx.env, service=svc.name, role=svc.role,
        )))
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
    # Mod 071: the ECS cluster is project-tier (stage + prod both always
    # exist), referenced via the project remote state by env.
    out.append(f'  cluster         = data.terraform_remote_state.project.outputs.ecs_cluster_{ctx.env}_arn')
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
    out.append("    namespace = aws_service_discovery_private_dns_namespace.env.arn")
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
    # Mod 044: only emit the ALB-target-group attachment when the project's
    # reverse-proxy variant emits the target group resource. EC2-traefik
    # routes via Service Connect, so there is no target group to bind to.
    if (
        "web" in nets
        and "target_group" in svc.emits.get("elastic", [])
        and ctx.reverse_proxy == "alb"
    ):
        out.append("  load_balancer {")
        out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
        out.append(f'    container_name   = "{svc.name}"')
        out.append(f'    container_port   = {svc.port or 80}')
        out.append("  }")
    # Mod 060: the ECS service's envinfra tags ride on `svc.body["tags"]`,
    # populated at compile time with shape_name=core_service / descriptor
    # ecs-svc (see compile._apply_elastic_invariants).
    out.append(render_hcl_tags(svc.body.get("tags", {})))
    out.append("}")
    return "\n".join(out)


def render_target_group(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_lb_target_group`` + ``aws_lb_listener_rule`` for a
    web-network service. The dispatcher only calls this when
    ``web in svc.networks`` (per ``_destination_applicable``).

    Mod 044: ``aws_lb_listener_rule`` is ALB-specific. Mod 070: EC2-traefik
    routes via the traefik ECS provider, which reads each task's traefik.*
    dockerLabels (see render_task_definition) — listener rules don't apply
    there. We still emit the target group: ECS services with a
    ``load_balancer { ... }`` reference it, and even when traefik is the
    front door the target-group resource is harmless (no ALB attaches to
    it). Future cleanup mod can prune.
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
    # The AWS `name` above is a hash-truncatable identifier; the full
    # descriptive name lives in the standard envinfra Name tag.
    out.append(render_hcl_tags(standard_tags(
        "environment",
        shape_name="core_service",
        descriptor="ALB-TG",
        project=ctx.project,
        env=ctx.env,
        service=svc.name,
        role=svc.role,
    )))
    out.append("}")
    if ctx.reverse_proxy == "alb":
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

    out: list[str] = []
    out.append(f'resource "aws_efs_file_system" "{svc.name}" {{')
    out.append(f'  creation_token   = "{svc.global_name}"')
    out.append( '  encrypted        = true')
    out.append( '  performance_mode = "generalPurpose"')
    out.append( '  throughput_mode  = "bursting"')
    out.append(render_hcl_tags(standard_tags(
        "environment", shape_name="backing_service", descriptor="EFS",
        project=ctx.project, env=ctx.env, service=svc.name, role=svc.role,
    )))
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


def render_scheduled_task(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit the EventBridge-Scheduler trigger for a ``scheduler`` service:
    an ``aws_scheduler_schedule`` invoking ECS ``RunTask`` on the reused
    task definition, plus a per-service scheduler-invocation IAM role and
    its inline policy. Mod 055.

    No ``ecs_service`` is emitted — a scheduler runs nothing continuously.
    The schedule's ``schedule_expression`` is the translated 6-field AWS
    cron form; the network placement mirrors :func:`render_ecs_service`
    (primary private subnet + the service's non-``web`` SGs).
    """
    from docex.cicl.cron import to_aws_cron_expression

    if svc.schedule is None:
        # Defensive: validation guarantees a scheduler service has a
        # schedule, so this is unreachable in a successful compile.
        return f"# scheduler service {svc.name!r} has no schedule; no HCL emitted"

    schedule_expr = to_aws_cron_expression(svc.schedule)
    role_name = (
        apply_policy(f"{svc.global_name}_scheduler", ctx.iam_policy)
        if ctx.iam_policy is not None
        else f"{svc.global_name}_scheduler"
    )

    # A scheduler is never on `web`; place the RunTask on its non-web SGs,
    # exactly as render_ecs_service places the long-running service.
    nets = sorted(n for n in svc.networks if n != "web")
    sg_refs = ", ".join(f"aws_security_group.{n}.id" for n in nets)

    out: list[str] = []
    # Invocation role: trusted by EventBridge Scheduler, granting RunTask
    # on this service's task-def family and PassRole on the project task-
    # execution role (so the spawned task can pull images / read SSM).
    out.append(f'resource "aws_iam_role" "{svc.name}_scheduler" {{')
    out.append(f'  name = "{role_name}"')
    out.append("  assume_role_policy = jsonencode({")
    out.append('    Version = "2012-10-17"')
    out.append("    Statement = [{")
    out.append('      Effect    = "Allow"')
    out.append('      Principal = { Service = "scheduler.amazonaws.com" }')
    out.append('      Action    = "sts:AssumeRole"')
    out.append("    }]")
    out.append("  })")
    out.append(render_hcl_tags(standard_tags(
        "environment", shape_name="core_service", descriptor="scheduler-role",
        project=ctx.project, env=ctx.env, service=svc.name, role=svc.role,
    )))
    out.append("}")
    out.append("")
    out.append(f'resource "aws_iam_role_policy" "{svc.name}_scheduler" {{')
    out.append(f'  name = "{role_name}"')
    out.append(f'  role = aws_iam_role.{svc.name}_scheduler.id')
    out.append("  policy = jsonencode({")
    out.append('    Version = "2012-10-17"')
    out.append("    Statement = [")
    out.append("      {")
    out.append('        Effect   = "Allow"')
    out.append('        Action   = "ecs:RunTask"')
    out.append(f"        Resource = aws_ecs_task_definition.{svc.name}.arn")
    out.append("      },")
    out.append("      {")
    out.append('        Effect   = "Allow"')
    out.append('        Action   = "iam:PassRole"')
    out.append(
        "        Resource = [data.terraform_remote_state.project.outputs"
        ".task_execution_role_arn]"
    )
    out.append("      },")
    out.append("    ]")
    out.append("  })")
    out.append("}")
    out.append("")
    out.append(f'resource "aws_scheduler_schedule" "{svc.name}" {{')
    out.append(f'  name = "{svc.global_name}"')
    out.append("  flexible_time_window {")
    out.append('    mode = "OFF"')
    out.append("  }")
    out.append(f'  schedule_expression          = "{schedule_expr}"')
    out.append('  schedule_expression_timezone = "UTC"')
    out.append("  target {")
    # Mod 071: project-tier cluster, referenced via the project remote state.
    out.append(f"    arn      = data.terraform_remote_state.project.outputs.ecs_cluster_{ctx.env}_arn")
    out.append(f"    role_arn = aws_iam_role.{svc.name}_scheduler.arn")
    out.append("    ecs_parameters {")
    out.append(
        f"      task_definition_arn = aws_ecs_task_definition.{svc.name}.arn"
    )
    out.append('      launch_type         = "FARGATE"')
    out.append("      task_count          = 1")
    out.append("      network_configuration {")
    out.append(
        "        subnets          = [data.terraform_remote_state.project"
        ".outputs.primary_private_subnet_id]"
    )
    out.append(f"        security_groups  = [{sg_refs}]")
    out.append("        assign_public_ip = false")
    out.append("      }")
    out.append("    }")
    out.append("  }")
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
    "scheduled_task": render_scheduled_task,  # Mod 055
}


def _destination_applicable(dest: str, svc: CompiledService, ctx: _RenderCtx | None = None) -> bool:
    """Check whether ``dest`` is conditionally emittable for ``svc``.

    ``target_group`` requires the service to be on the ``web`` network.
    The doctrine doesn't forbid an engine from declaring ``target_group``
    even when no actual service of that engine would be web-routed; the
    gate just keeps the emit aligned with runtime reachability.

    Mod 044: ``target_group`` is additionally suppressed when the
    project's ``reverse_proxy`` is one of the ``ec2_traefik_*`` variants —
    those projects don't have an ALB to attach the target group to.
    Mod 070: traefik reaches ECS tasks via its ECS provider (polling task
    ENIs, routing off dockerLabels), so no target group is required.
    """
    if dest == "target_group":
        if "web" not in svc.networks:
            return False
        if ctx is not None and ctx.reverse_proxy != "alb":
            return False
        return True
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
        if not _destination_applicable(dest, svc, ctx):
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
    reverse_proxy: str | None = None,
    traefik_acme_email: str | None = None,
) -> None:
    """Emit the project-tier ``main.tf``.

    One copy per project (NOT per env). Backs every elastic env via
    ``data "terraform_remote_state" "project"``. The state lives under
    ``key = "project/terraform.tfstate"`` in the same S3 backend the
    bootstrap creates. The bootstrap runs ``tofu apply`` against this
    HCL before any env-tier apply can succeed.

    ``reverse_proxy`` selects between the doctrine's elastic reverse-proxy
    variants (mod 044). ``"alb"`` (the doctrine default when the project
    leaves the field unset) emits the ALB resource set plus ACM certs;
    ``"ec2_traefik_eip"`` / ``"ec2_traefik_pip"`` emit a single EC2 instance
    running traefik. See doctrine ``projinfra/ec2_traefik.md``.
    """
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    # Mod 060: templates call standard_tags() instead of hand-writing the
    # three doctrine tag blocks (cicl.md § Naming and Tagging).
    env.globals["standard_tags"] = standard_tags
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
    ecs_p = naming_policies.get("ecs")
    # Mod 046: the project subdomain (Route53 zone, ACM cert domain_name + SANs)
    # is a DNS hostname — its project segment must be DNS-labeled. AWS rejects
    # underscores in zone names and ACM cert domain names; an underscored
    # project name (e.g. `docex_smoke_elastic`) must render as
    # `docex-smoke-elastic.<apex_domain>` here.
    http_host_p = naming_policies.get("http_host")
    project_subdomain = f"{apply_policy(project, http_host_p)}.{apex_domain}"

    # WHY: ECR repo names are structural — `${project}/${service}` with each
    # segment verbatim and `/` as joiner. The single-separator policy
    # machinery cannot express this shape; per transfer_tables.md
    # "How structural emitters reference a policy", ECR joins the small set
    # of structural emit sites that bypass the policy table.
    ecr_repo_names = {
        name: f"{project}/{name}"
        for name in core_service_names
    }
    # WHY: ``reverse_proxy`` defaults to "alb" — the doctrine's default
    # when the project leaves the CICL field unset (see cicl.md § Reverse
    # Proxy and mod 031's `_validate_reverse_proxy_field`). Centralising
    # the default here keeps every downstream branch in the template free
    # of `or "alb"` handling.
    rp = reverse_proxy or "alb"

    # Mod 071: the two ECS clusters (stage + prod) are project-tier — every
    # elastic project gets both, on both reverse_proxy paths. Named per the
    # `ecs` naming policy and keyed by env so the cluster resources, outputs,
    # the traefik IAM ArnEquals condition, and the user_data provider list all
    # reference the same rendered names. (Was the mod-070 `traefik_ecs_clusters`
    # list, which only the ec2_traefik path consumed; making the clusters
    # project-tier fixes bug 8 — the traefik ECS provider treats a missing
    # listed cluster as fatal for the entire refresh, so both must pre-exist.)
    ecs_clusters = {
        "stage": apply_policy(f"{project}_stage", ecs_p),
        "prod": apply_policy(f"{project}_prod", ecs_p),
    }

    # Render the EC2-traefik user_data script ahead of the HCL template so
    # the rendered shell is available as a single literal injected into
    # `aws_instance.project_traefik.user_data`. Skipped on the ALB path
    # because the template's ALB branch never references it.
    traefik_user_data = ""
    if rp in ("ec2_traefik_eip", "ec2_traefik_pip"):
        # WHY: ACME registration email — LE needs *something*; use a
        # project-derived placeholder when the operator hasn't supplied
        # one. A real follow-up mod can surface this via infra.yml.
        acme_email = traefik_acme_email or f"docex@{apex_domain}"
        ud_tpl = env.get_template("ec2_traefik_user_data.sh.j2")
        traefik_user_data = ud_tpl.render(
            project=project,
            project_subdomain=project_subdomain,
            apex_domain=apex_domain,
            reverse_proxy=rp,
            traefik_acme_email=acme_email,
            traefik_region=ELASTIC_REGION,
            ecs_clusters=ecs_clusters,
        )
        # WHY: the user_data is injected into an HCL heredoc in
        # project.tf.j2, and HCL heredocs interpolate ${...}/%{...}. The
        # rendered script is pure bash — every ${VAR} is a shell expansion,
        # none are HCL refs — so escape both interpolation triggers. OpenTofu
        # un-escapes $${ -> ${ and %%{ -> %{ when evaluating the heredoc, so
        # the instance receives the intended script. Bare $(...) / $VAR are
        # untouched (only ${ and %{ trigger HCL interpolation). NOTE: do NOT
        # use the $->$$ doubling from _hcl_value here — that is for quoted
        # strings whose only $ usage is ${...}; this script has bare $(...)
        # that must survive un-doubled.
        traefik_user_data = traefik_user_data.replace(
            "${", "$${"
        ).replace("%{", "%%{")

    rendered = tpl.render(
        project=project,
        project_subdomain=project_subdomain,
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
        reverse_proxy=rp,
        traefik_user_data=traefik_user_data,
        ecs_clusters=ecs_clusters,
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
    # Mod 060: templates call standard_tags() instead of hand-writing the
    # three doctrine tag blocks (cicl.md § Naming and Tagging).
    env.globals["standard_tags"] = standard_tags
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
    iam_p = naming_policies.get("iam")

    ctx = _RenderCtx(
        project=compiled.project,
        env=compiled.env,
        alb_policy=alb_p,
        priorities=priorities,
        iam_policy=iam_p,
        observability_backend_url=compiled.observability_backend_url,
        reverse_proxy=compiled.reverse_proxy,
    )

    def _render(svc: CompiledService) -> str:
        return render_service(svc, ctx)

    rendered = tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        apex_domain=compiled.apex_domain,
        subdomain=compiled.subdomain,
        # Mod 048: bare-project host used by prod's `domain_default_service`
        # A-record. Template gates on `env == "prod"`.
        bare_project_subdomain=compiled.bare_project_subdomain,
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
        reverse_proxy=compiled.reverse_proxy,
    )
    out_path.write_text(rendered)
