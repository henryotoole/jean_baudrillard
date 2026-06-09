"""Emit a docker-compose.yml for one fixed-foundation environment.

The emitter:

  - Prepends the doctrine's ``x-logging`` YAML anchor.
  - For each service: pulls the merged service body from the compiled
    representation and writes it under ``services:``.
  - Adds project-scoped ``networks:`` and ``volumes:`` sections at the
    bottom.

``$[VAR]`` runtime refs that survive to here are translated to compose's
``${VAR}`` form so docker-compose reads them from ``.env`` at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from docex import OTEL_COLLECTOR_IMAGE
from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.substitute import HCLLiteral
from docex.emit.otelcol import render_otelcol_config


# Runtime-ref pattern matches $[VAR_NAME].
_RUNTIME_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


def _translate_runtime_refs(s: str) -> str:
    """Compose: $[VAR] -> ${VAR}. Plain strings pass through."""
    return _RUNTIME_RE.sub(lambda m: "${" + m.group(1) + "}", s)


def _translate_tree(node: Any) -> Any:
    """Translate all $[VAR] references throughout a YAML-shaped tree."""
    if isinstance(node, str):
        return _translate_runtime_refs(node)
    if isinstance(node, dict):
        return {k: _translate_tree(v) for k, v in sorted(node.items())}
    if isinstance(node, list):
        return [_translate_tree(v) for v in node]
    return node


def _named_volumes(compiled: CompiledEnv) -> list[str]:
    """Collect named volumes referenced by services."""
    seen: set[str] = set()
    for svc in compiled.services.values():
        for v in svc.body.get("volumes", []) or []:
            if not isinstance(v, str):
                continue
            # ``<name>:<path>`` form. Skip bind mounts (start with '/').
            if ":" not in v:
                continue
            left = v.split(":", 1)[0]
            if left.startswith("/") or left.startswith("."):
                continue
            seen.add(left)
    return sorted(seen)


def _network_section(compiled: CompiledEnv) -> dict[str, Any]:
    """Top-level ``networks:`` block.

    Every non-``web`` network compiles to a project-scoped docker network
    named ``${project}-${env}-${shortname}`` with ``internal: true``.
    Per mod 030's naming unification, docker network names — being
    data-plane resolvable identifiers — use hyphens.

    The ``web`` network is special-cased: it compiles to a bare external
    docker network named ``web`` that the machine-wide Traefik is also
    attached to. This is the shared public-routing plane, per
    ``doctrine/infrastructure/specifics/networks.md § Network Definition
    Name vs. Compiled Name``.
    """
    out: dict[str, Any] = {}
    for short in sorted(compiled.networks):
        if short == "web":
            # WHY: project-scoping `web` would force per-project Traefik
            # instances, which can't coexist on :443. The bare external
            # `web` network is the single host-wide public-routing plane
            # the machine-wide Traefik attaches to.
            out[short] = {"name": "web", "external": True}
            continue
        full = f"{compiled.project}-{compiled.env}-{short}"
        out[short] = {"name": full, "internal": True}
    return out


def _traefik_labels(svc: CompiledService) -> list[str]:
    """Traefik discovery labels for a web-network service.

    The router rule ORs together every host the service answers at — a
    service is reachable at ``<service>.<env>.<project>.<apex_domain>``,
    and the ``domain_default_service`` additionally at the bare
    ``<env>.<project>.<apex_domain>``; in prod it also answers at the
    bare-project host ``<project>.<apex_domain>``. Traefik reaches the
    container over the docker network on ``svc.port``; no host port is
    published. These are generated here (per ``web_hosts``) rather than
    carried as static labels in the transfer table, so routing is driven
    by network membership, not role.

    The ``tls.certresolver=doctrine`` label is mandatory: per ``doctrine/
    infrastructure/specifics/transfer_tables.md § Foundation Invariants §
    Per-container (fixed)``, the doctrine prescribes the literal handle
    ``doctrine`` as the name of the machine-wide cert resolver. Traefik
    v3 does not propagate an entrypoint-level default ``tls.certResolver``
    into a router whose ``tls={}`` is set from labels, so emitting
    ``tls=true`` without naming the resolver suppresses ACME entirely.
    """
    gname = svc.global_name
    rule = " || ".join(f"Host(`{h}`)" for h in svc.web_hosts)
    return [
        "traefik.enable=true",
        f"traefik.http.routers.{gname}.rule={rule}",
        f"traefik.http.routers.{gname}.entrypoints=websecure",
        f"traefik.http.routers.{gname}.tls=true",
        f"traefik.http.routers.{gname}.tls.certresolver=doctrine",
        f"traefik.http.services.{gname}.loadbalancer.server.port={svc.port}",
    ]


def _service_block(svc: CompiledService) -> dict[str, Any]:
    """Render one compiled service into a compose-ready dict."""
    block = dict(svc.body)

    # The compiler stored ``logging`` as a YAML-merge-key placeholder; replace
    # with the actual anchor reference via a string sentinel that PyYAML
    # emits verbatim by way of a custom representer below.
    if "logging" in block:
        # Use a special object that the YAML dumper turns into an alias.
        block["logging"] = _LoggingAnchor()

    # Translate $[VAR] runtime refs to compose ${VAR} form throughout.
    block = _translate_tree(block)

    return block


class _LoggingAnchor:
    """Sentinel for the doctrinal ``*default-logging`` YAML alias."""


def _sidecar_block(
    svc: CompiledService, project: str, env: str,
    observability_backend_url: str,
) -> dict[str, Any]:
    """Render the paired OTel Collector sidecar block for a core service.

    The sidecar shares the core service's network namespace via
    ``network_mode: service:<core>`` (mutually exclusive with a
    ``networks:`` list per docker-compose), reads its config from
    compose's top-level ``configs:`` block, and gets:

    - ``OBSERVABILITY_BACKEND_URL`` as a literal value from
      ``infra.yml``'s top-level field (it's config, not a secret —
      mirrors the elastic side's behavior, mod 023).
    - ``TELEMETRY_API_KEY`` via compose's ``${TELEMETRY_API_KEY:-}``
      interpolation from ``.env`` (it IS a secret; lives in
      ``<env>.env`` on the operator's machine).

    The ``:-`` empty default on the API key keeps dev/test compose
    succeeding without the operator setting it — the dev/test sidecars
    use the ``debug`` exporter and don't consume the key. Mod 018 + 023.

    No ``healthcheck:`` block: the otel/opentelemetry-collector image
    is built FROM scratch and carries no probe tool (wget/curl/shell
    all absent). The doctrine-prescribed wget-based healthcheck could
    never succeed; emitting it left compose reporting the sidecar as
    ``health: starting`` forever while the container actually worked
    fine. Mod 024 dropped it; otelcol's ``health_check`` extension on
    127.0.0.1:13133 stays available for in-band diagnostics from
    inside the shared netns.
    """
    sidecar_name = f"{project}_{env}_{svc.name}_otelcol"
    return {
        "image": OTEL_COLLECTOR_IMAGE,
        "container_name": sidecar_name,
        "command": ["--config=/etc/otelcol/config.yaml"],
        "network_mode": f"service:{svc.global_name}",
        "configs": [
            {"source": "otelcol_config", "target": "/etc/otelcol/config.yaml"},
        ],
        "environment": {
            "OBSERVABILITY_BACKEND_URL": observability_backend_url,
            "TELEMETRY_API_KEY": "${TELEMETRY_API_KEY:-}",
        },
        "deploy": {
            "resources": {"limits": {"cpus": "0.1", "memory": "128M"}}
        },
        "restart": "unless-stopped",
        "logging": _LoggingAnchor(),
    }


def _logging_anchor_representer(dumper: yaml.SafeDumper, _data: Any) -> yaml.Node:
    # Emit ``*default-logging`` as an alias reference. PyYAML represents
    # aliases via Anchor handles; here we render as a plain scalar that
    # YAML readers parse as an alias. Easier: just emit ``*default-logging``
    # as a raw scalar in plain form.
    return dumper.represent_scalar("tag:yaml.org,2002:str", "*default-logging", style="")


def _hcl_literal_representer(dumper: yaml.SafeDumper, data: Any) -> yaml.Node:
    # Should not occur in compose output (raw HCL only appears in elastic
    # templates). If it does, emit a literal string with a clear marker.
    return dumper.represent_scalar("tag:yaml.org,2002:str", f"<HCL:{str(data)}>")


class _DocexComposeDumper(yaml.SafeDumper):
    """SafeDumper subclass with our custom representers."""


_DocexComposeDumper.add_representer(_LoggingAnchor, _logging_anchor_representer)
_DocexComposeDumper.add_representer(HCLLiteral, _hcl_literal_representer)
# Force block style and stable key order.
_DocexComposeDumper.add_representer(
    dict,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map",
        sorted(data.items()) if isinstance(data, dict) else data,
        flow_style=False,
    ),
)


def emit_compose(compiled: CompiledEnv, out_path: Path) -> None:
    """Write the env's ``docker-compose.yml`` to ``out_path``.

    Top-level layout (deterministic):
        # header comments
        x-logging: &default-logging  (anchor)
          ...
        services: ...
        networks: ...
        volumes: ...
    """
    # Services
    services: dict[str, Any] = {}
    # Map simple service name -> compose service key (global name). depends_on
    # is authored against simple names in infra.yml, but the compose file's
    # service keys are the global names — they must agree or docker compose
    # rejects the file with "depends on undefined service".
    simple_to_global = {
        n: s.global_name for n, s in compiled.services.items()
    }
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        block = _service_block(svc)

        # Phase 2: dev compose gets bind mounts on core services so
        # ``docex build`` can refresh host-side dist/ without rebuilding
        # the image. Test/stage/prod intentionally do NOT get bind mounts —
        # the test image builds artifacts via `docker build`'s build stage,
        # and stage/prod ship images from the registry.
        # The container-side paths /service/src and /service/dist are
        # doctrinal defaults; see infrastructure.md § Core Service Containers.
        if compiled.env == "dev" and svc.is_core:
            bind_mounts = [
                f"./core/{svc.name}/src:/service/src",
                f"./core/{svc.name}/dist:/service/dist",
            ]
            existing_vols = block.get("volumes")
            if isinstance(existing_vols, list):
                # Preserve any named volumes already set by transfer-table merging.
                block["volumes"] = list(existing_vols) + bind_mounts
            else:
                block["volumes"] = bind_mounts

        # Phase 2: dev and test envs build images locally from the
        # service's Dockerfile rather than pulling from the registry.
        # The doctrine requires every core service to ship a Dockerfile
        # with build/dev/prod/test stages; we tell compose which stage
        # to target so `docker compose up --build` produces the right
        # image. Stage/prod compose intentionally retains the registry
        # image ref — those envs pull, they don't build.
        if compiled.env in ("dev", "test") and svc.is_core:
            block["build"] = {
                "context": f"./core/{svc.name}",
                "dockerfile": "Dockerfile",
                "target": compiled.env,  # "dev" stage or "test" stage
            }
        if svc.is_core and svc.env:
            # Merge `env:` (translated) into the service `environment:` map.
            env_translated = _translate_tree(svc.env)
            existing = block.get("environment", {})
            if isinstance(existing, dict):
                merged = dict(existing)
                merged.update(env_translated)
                block["environment"] = merged
            elif isinstance(existing, list):
                # Convert list-form to dict-form for consistent merging.
                d: dict[str, Any] = {}
                for item in existing:
                    if isinstance(item, str) and "=" in item:
                        k, v = item.split("=", 1)
                        d[k] = v
                d.update(env_translated)
                block["environment"] = d
            else:
                block["environment"] = env_translated

        # Network-driven routing: any web-network service (core or backing
        # container) gets Traefik discovery labels with its per-service
        # host(s). The machine-wide Traefik routes those subdomains to the
        # container over the docker network — no host port is published.
        if svc.web_hosts:
            block["labels"] = _traefik_labels(svc)

        services[svc.global_name] = block

    # Mod 018: paired OTel Collector sidecar per core service. The sidecar
    # block uses compose's native ${VAR:-} syntax for its env, not docex's
    # $[VAR] runtime-ref form, so we add it *after* the per-service
    # translation pass above — _translate_tree would otherwise convert
    # only $[VAR] tokens (which sidecars don't carry) but the rule is
    # cleanest if sidecars sit entirely outside the translation path.
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        if not svc.is_core:
            continue
        # WHY: project/env/svc joiners use hyphens per mod 030's data-plane
        # naming rule (docker container names). The `_otelcol` suffix is
        # tracked separately for mod 032.
        sidecar_name = f"{compiled.project}-{compiled.env}-{svc.name}_otelcol"
        services[sidecar_name] = _sidecar_block(
            svc, compiled.project, compiled.env,
            compiled.observability_backend_url,
        )

    # Second pass: rewrite each service's depends_on from compose short-form
    # (list of names) to long-form (map keyed by global name with a condition).
    # WHY: short-form only waits for the target container to *start*. Backing
    # services like postgres take measurable time to become reachable after
    # starting; a dependent service (or `compose exec` from `docex up`) that
    # connects too early hits a refused TCP socket. service_healthy uses the
    # target's already-declared healthcheck as the gate; service_started is
    # the safe fallback when the target declares no healthcheck (semantically
    # equivalent to compose short-form).
    # A second pass is required because the condition depends on whether the
    # target's emitted block contains a ``healthcheck`` key — every block must
    # exist before we can resolve any dependency's condition.
    for block in services.values():
        deps = block.get("depends_on")
        if not isinstance(deps, list):
            continue
        long_form: dict[str, Any] = {}
        for dep in deps:
            target_global = simple_to_global.get(dep, dep)
            target_block = services.get(target_global, {})
            cond = (
                "service_healthy"
                if "healthcheck" in target_block
                else "service_started"
            )
            long_form[target_global] = {"condition": cond}
        block["depends_on"] = long_form

    # Build top-level dict without the x-logging key (we render it by hand
    # so its YAML anchor reference is exact).
    body_doc: dict[str, Any] = {"services": services}
    networks = _network_section(compiled)
    if networks:
        body_doc["networks"] = networks
    volumes = _named_volumes(compiled)
    if volumes:
        body_doc["volumes"] = {v: {"name": v} for v in volumes}
    # Mod 018 introduced the top-level `configs:` block. Mod 020 patched
    # the file-mount path. Mod 021 switches to inline `content:` so the
    # compose file is self-contained — the otelcol config travels with
    # the compose file to the deploy host, no separate file needed. This
    # also makes fixed symmetric with elastic, where the config is
    # already embedded as a literal in the OTEL_CONFIG_YAML env var.
    # Mod 022: compose interpolates ${VAR} inside `configs.content` too.
    # The otelcol config carries `${env:OBSERVABILITY_BACKEND_URL}` and
    # `${env:TELEMETRY_API_KEY}` references that otelcol must see
    # verbatim; doubling `$` → `$$` makes compose pass through a single
    # literal `$` to the sidecar. Elastic is unaffected (ECS does not
    # interpolate `$`).
    if any(s.is_core for s in compiled.services.values()):
        content = render_otelcol_config(compiled.env).replace("$", "$$")
        body_doc["configs"] = {
            "otelcol_config": {"content": content},
        }

    header = (
        "# Generated by `docex compile`. Do not edit by hand.\n"
        f"# project: {compiled.project} v{compiled.project_version}\n"
        f"# env: {compiled.env} (foundation: {compiled.foundation})\n"
        f"# apex_domain: {compiled.apex_domain} -> {compiled.subdomain}\n"
    )
    x_logging = (
        "x-logging: &default-logging\n"
        "  driver: json-file\n"
        "  options:\n"
        "    max-size: \"10m\"\n"
        "    max-file: \"3\"\n"
    )
    body = _dump_compose(body_doc)
    # Replace the quoted placeholder we used internally with the YAML
    # alias reference. We render the sentinel value as the literal
    # string '*default-logging'; the compose YAML reader interprets
    # this as an alias because we wrote it without quoting via our
    # custom representer. To be safe, also convert any quoted form.
    body = body.replace("'*default-logging'", "*default-logging")
    body = body.replace('"*default-logging"', "*default-logging")
    out_path.write_text(header + x_logging + body)


def _dump_compose(doc: dict[str, Any]) -> str:
    """Serialize the compose document with our custom dumper."""
    return yaml.dump(
        doc,
        Dumper=_DocexComposeDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
