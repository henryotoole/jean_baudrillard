"""Emit a per-env ``main.tf`` for elastic-foundation envs.

The HCL is rendered via Jinja2 from a template. For each backing /
core service the emitter formats its merged body (a dict possibly
containing ``HCLLiteral`` raw expressions) into HCL key=value lines.

Phase 4 hardened the emitter so its output passes ``tofu validate``:

- Block-attribute formatting (no inline-semicolon blocks in the
  Jinja template — fixed via ``main.tf.j2``).
- Fargate ``(cpu, memory)`` pair validation (fixed via
  :mod:`docex.cicl.fargate` and the compiler's ``_resources_to_elastic``).
- Ephemeral storage floor 21 GiB / ceiling 200 GiB (same).
- ``$[VAR]`` → ECS ``secrets[]`` block, not literal ``environment[]``
  entries. Implemented below in ``render_core``: a core service env
  value that is a bare ``$[REF]`` becomes a ``secrets[]`` entry named
  after the *consumer's* env key, whose ``valueFrom`` points at
  ``/<project>/<env>/<REF>`` in SSM Parameter Store. Naming by the
  consumer's key (not ``REF``) keeps the container's env-var surface
  identical to the fixed/compose side — the parts-only symmetry
  guarantee. Composed secrets are rejected earlier, by the compiler.
  The account ID is referenced from
  ``data.aws_caller_identity.current.account_id`` so compile stays
  pure (no AWS creds needed).
- RDS password / username sourced from ``data "aws_ssm_parameter"``
  rather than emitted as the literal string ``"$[POSTGRES_PASSWORD]"``.
  Implemented below in ``render_backing``.
- Listener-rule ``host_header.values`` set to the env's full
  subdomain (e.g. ``"stage.example.com"``), not just the env name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from docex import ELASTIC_REGION
from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.substitute import HCLLiteral


_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Match a runtime-ref token ``$[VAR]`` inside a value string. Used to
# detect (and extract) which entries on a core service's env block must
# move to the secrets[] block.
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
        # Escape backslashes and double-quotes.
        esc = value.replace("\\", "\\\\").replace('"', '\\"')
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


# ---------------------------------------------------------------------------
# Per-service renderers
# ---------------------------------------------------------------------------


_ENGINE_TO_RESOURCE = {
    "postgres": "aws_db_instance",
    "redis": "aws_elasticache_cluster",
    "s3": "aws_s3_bucket",
    # MinIO is fixed-only; should never appear here.
}


def _ssm_arn_literal(project: str, env: str, var: str) -> HCLLiteral:
    """Return an HCL literal for the SSM ARN of a per-env secret.

    Uses ``data.aws_caller_identity.current.account_id`` so the
    compile stage does not need AWS credentials to resolve the account
    ID; OpenTofu resolves it at apply time.
    """
    # NOTE: the leading ``"`` and trailing ``"`` are part of the
    # returned literal — it's a JSON string inside an HCL ``jsonencode``,
    # with HCL interpolation embedded via ``${...}``. The interpolation
    # produces the account ID at apply time.
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


def render_backing(svc: CompiledService, *, project: str, env: str) -> str:
    """Render a backing service to its HCL resource block.

    On postgres/RDS the engine's ``env:`` block declares which
    parameter-store keys the operator must populate before release.
    Phase 4 emits an ``aws_ssm_parameter`` *data source* per such key
    and points the RDS resource's ``username``/``password`` at the
    data source values, so AWS pulls them from SSM Parameter Store
    rather than reading them as literal strings from the HCL.

    The release flow's SSM-push step guarantees these parameters
    exist before ``tofu apply`` evaluates the data sources.
    """
    rtype = _ENGINE_TO_RESOURCE.get(svc.engine)
    if rtype is None:
        # Unknown — emit a comment so the developer sees the issue but
        # tofu apply doesn't choke silently on partial output.
        return f"# unknown engine {svc.engine!r} for service {svc.name!r}; no HCL emitted"

    body = dict(svc.body)

    # Phase 4: identify any runtime-ref-shaped values in the body. These
    # are values that came from the engine's defaults.elastic block
    # carrying a ``$[VAR]`` token (e.g. ``username: $[POSTGRES_USER]``).
    # Translate each into a data.aws_ssm_parameter reference and emit
    # the corresponding data source above the resource.
    data_sources: list[str] = []
    seen_keys: set[str] = set()

    def maybe_ssm_substitute(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        m = _RUNTIME_REF_RE.fullmatch(value)
        if m is None:
            return value
        key = m.group(1)
        if key not in seen_keys:
            seen_keys.add(key)
            ds_name = _ssm_data_name(svc.name, key)
            data_sources.append(
                f'data "aws_ssm_parameter" "{ds_name}" {{\n'
                f'  name            = "/{project}/{env}/{key}"\n'
                f'  with_decryption = true\n'
                f'}}'
            )
        ds_name = _ssm_data_name(svc.name, key)
        return HCLLiteral(f"data.aws_ssm_parameter.{ds_name}.value")

    body = {k: maybe_ssm_substitute(v) for k, v in body.items()}

    # `identifier` is doctrine's invariant name; rename to the resource-type
    # appropriate field per transfer_tables.md § Per-resource (elastic).
    if rtype == "aws_db_instance":
        body["identifier"] = body.pop("identifier", svc.global_name)
    elif rtype == "aws_elasticache_cluster":
        body["cluster_id"] = body.pop("identifier", svc.global_name)
    elif rtype == "aws_s3_bucket":
        body["bucket"] = body.pop("identifier", svc.global_name)
    # Strip keys we don't emit at this layer.
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)
    # Networks become security group attachments on resources that support it.
    nets = list(svc.networks)
    body.pop("networks", None)
    if rtype == "aws_db_instance" and nets:
        body["vpc_security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["db_subnet_group_name"] = HCLLiteral(
            f"aws_db_subnet_group.{svc.name}.name"
        )
    if rtype == "aws_elasticache_cluster" and nets:
        body["security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["subnet_group_name"] = HCLLiteral(
            f"aws_elasticache_subnet_group.{svc.name}.name"
        )

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.extend(data_sources)
    if data_sources:
        out.append("")
    out.append(f'resource "{rtype}" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    if rtype == "aws_db_instance" and nets:
        out.append("")
        out.append(f'resource "aws_db_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    if rtype == "aws_elasticache_cluster" and nets:
        out.append("")
        out.append(f'resource "aws_elasticache_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    return "\n".join(out)


def render_core(svc: CompiledService, *, project: str, env: str, priority: int) -> str:
    """Render a core service to ECS task definition + service + (optional) target group.

    Phase 4 partitions the service's env block into ``environment[]``
    (plain strings, resolved at compile time) and ``secrets[]``
    (entries whose value contains ``$[VAR]``, which on elastic must
    be sourced from SSM Parameter Store).
    """
    body = dict(svc.body)
    nets = list(svc.networks)
    cpu = body.get("cpu", "256")
    memory = body.get("memory", "512")
    ephemeral = body.get("ephemeral_storage")

    env_entries: list[dict[str, Any]] = []
    secret_entries: list[dict[str, Any]] = []

    for k in sorted(svc.env):
        v = svc.env[k]
        if isinstance(v, HCLLiteral):
            # @-pass-through (e.g. RDS endpoint). Embed as an HCL
            # interpolation inside the JSON string. These do not
            # contain runtime refs.
            env_entries.append({"name": k, "value": HCLLiteral(f'"${{{str(v)}}}"')})
            continue
        if isinstance(v, str):
            m = _RUNTIME_REF_RE.fullmatch(v)
            if m is not None:
                # Secret part. By the parts-only rule (enforced in the
                # compiler), a secret resolves to exactly one bare $[REF].
                # Emit an ECS secret named after the *consumer's* key (k),
                # with valueFrom pointing at the underlying secret's SSM
                # path — keeping the container's env-var surface identical
                # to the fixed/compose side.
                secret_entries.append({
                    "name": k,
                    "valueFrom": _ssm_arn_literal(project, env, m.group(1)),
                })
                continue
            # Plain string with no runtime refs.
            env_entries.append({"name": k, "value": v})
            continue
        # Non-string scalar — stringify and emit as plain env.
        env_entries.append({"name": k, "value": str(v)})

    container_def: dict[str, Any] = {
        "name": svc.name,
        "image": body.get("image", ""),
        "essential": True,
    }
    if svc.port is not None:
        container_def["portMappings"] = [
            {"containerPort": svc.port, "protocol": "tcp"}
        ]
    if env_entries:
        container_def["environment"] = env_entries
    if secret_entries:
        container_def["secrets"] = secret_entries

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
    out.append("  container_definitions = jsonencode([")
    out.append(f"    {_hcl_value(container_def, indent=4)},")
    out.append("  ])")
    out.append(
        f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
        f'service = "{svc.name}", role = "{svc.role}", '
        f'managed_by = "doctrine" }}'
    )
    out.append("}")
    out.append("")

    # Migration task definition: same image as main, but command runs
    # /service/migrate.sh. Emitted only for services with schema
    # ownership (i.e. those that own a relational_db). The compiler
    # doesn't expose schema_owned_by from the *core* side, so we
    # emit one per core service that owns a database. Practically,
    # for Phase 4's smoke fixture this means the API service.
    if svc.schema_owned_by_db:
        mig_family = f"{svc.global_name}_migrate"
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
        out.append("")

    # Target group + listener rule if on the web network.
    if "web" in nets:
        out.append(f'resource "aws_lb_target_group" "{svc.name}" {{')
        out.append(f'  name        = "{svc.global_name}-tg"')
        out.append(f'  port        = {svc.port or 80}')
        out.append( '  protocol    = "HTTP"')
        out.append( '  target_type = "ip"')
        out.append( '  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id')
        out.append("}")
        out.append("")
        out.append(f'resource "aws_lb_listener_rule" "{svc.name}" {{')
        out.append( '  listener_arn = aws_lb_listener.alb_https.arn')
        out.append(f'  priority     = {priority}')
        out.append( '  action {')
        out.append( '    type             = "forward"')
        out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
        out.append( '  }')
        out.append( '  condition {')
        out.append( '    host_header {')
        # Per-service host(s): <service>.<env>.<domain>, plus the bare
        # <env>.<domain> for the domain_default_service.
        hosts_hcl = ", ".join(f'"{h}"' for h in svc.web_hosts)
        out.append(f'      values = [{hosts_hcl}]')
        out.append( '    }')
        out.append( '  }')
        out.append("}")
        out.append("")

    # ECS service.
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
    if "web" in nets:
        out.append("  load_balancer {")
        out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
        out.append(f'    container_name   = "{svc.name}"')
        out.append(f'    container_port   = {svc.port or 80}')
        out.append("  }")
    out.append("}")
    return "\n".join(out)


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
    domain: str,
    core_service_names: list[str],
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
    rendered = tpl.render(
        project=project,
        project_version=project_version,
        domain=domain,
        region=ELASTIC_REGION,
        core_service_names=svc_entries,
    )
    out_path.write_text(rendered)


def emit_hcl(compiled: CompiledEnv, out_path: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template("main.tf.j2")
    backing = [s for s in compiled.services.values() if not s.is_core]
    core = [s for s in compiled.services.values() if s.is_core]
    backing.sort(key=lambda s: s.name)
    core.sort(key=lambda s: s.name)

    # Wrap the per-service renderers so Jinja can call them with just
    # `svc` while we pass the project/env/subdomain context they need.
    def _backing(svc: CompiledService) -> str:
        return render_backing(svc, project=compiled.project, env=compiled.env)

    # ALB listener rules need a unique priority per web service. Assign
    # deterministically from the sorted web-core services (100, 101, ...).
    _web_core = [s for s in core if "web" in s.networks]
    _priorities = {s.name: 100 + i for i, s in enumerate(_web_core)}

    def _core(svc: CompiledService) -> str:
        return render_core(
            svc,
            project=compiled.project,
            env=compiled.env,
            priority=_priorities.get(svc.name, 100),
        )

    rendered = tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        domain=compiled.domain,
        subdomain=compiled.subdomain,
        region=ELASTIC_REGION,
        networks_sorted=sorted(compiled.networks),
        backing_services=backing,
        core_services=core,
        render_backing=_backing,
        render_core=_core,
    )
    out_path.write_text(rendered)
