"""Emit a docker-compose.yml for one fixed-foundation environment.

The emitter:

  - Prepends the doctrine's ``x-logging`` YAML anchor.
  - For each service: pulls the merged service body from the compiled
    representation and writes it under ``services:``.
  - Adds project-scoped ``networks:`` and ``volumes:`` sections at the
    bottom.

``$[VAR]`` runtime refs that survive to here are translated to compose's
``${VAR}`` form so docker-compose reads them from ``.env`` at runtime.

Mod 099 — the exec service
--------------------------
Alongside the per-core-service app containers, the emitter writes exactly one
``<codebase>-exec`` block per codebase: the container that *is* the codebase,
into which the three per-**codebase** operations (``migrate``, ``test``,
``build``) run one-off via ``docker compose run --rm``. It exists because
those operations previously had to *pick* one core service's container to
``compose exec`` into, through a heuristic that was duplicated three times
and wrong at least once.

Two properties carry the design:

- ``profiles: [exec]`` keeps ``compose up`` from ever starting it, while
  ``compose run`` implicitly enables the profile of the service it names. The
  block is inert until something runs in it.
- Its ``environment:`` is the **codebase-level** ``env:`` surface only
  (``CompiledService.codebase_env``), never a core service's overlay. That is
  what turns *``migrate.sh``, ``test_unit.sh``, ``test_integration.sh`` and
  ``build.sh`` may depend only on
  codebase-scoped env* from a convention into an enforceable rule: a
  core-service-level key is not merely discouraged there, it is absent.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

from docex import OTEL_COLLECTOR_IMAGE, TRAEFIK_IMAGE
from docex.cicl.compile import (
    CompiledEnv, CompiledService, effective_replicas, group_by_codebase,
)
from docex.cicl.substitute import HCLLiteral
from docex.emit.otelcol import render_otelcol_config
from docex.emit.schedules import schedule_env


# Runtime-ref pattern matches $[VAR_NAME].
_RUNTIME_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


def _translate_runtime_refs(s: str) -> str:
    """Compose: $[VAR] -> ${VAR}. Plain strings pass through."""
    return _RUNTIME_RE.sub(lambda m: "${" + m.group(1) + "}", s)


def _docex_project_label(project_dns_label: str) -> str:
    """The ``docex.project=<label>`` label stamped on every container docex
    emits on fixed.

    Mod 051 (Gap B): the per-project traefik constrains its docker provider
    to ``Label(`docex.project`,`<label>`)`` so it only registers routers for
    *this* project's containers — not every ``traefik.enable=true`` container
    reachable on the shared ``docex-ingress`` bridge. The label value MUST be
    byte-identical to the constraint's value or the constraint matches
    nothing. Emitted uniformly (every container, not just web services) so
    the constraint is unambiguous.
    """
    return f"docex.project={project_dns_label}"


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
    named ``${project}-${env}-${shortname}``: a plain user-defined bridge
    with no published ports. That is already exactly what ``doctrine/
    infrastructure/specifics/networks.md § networks: [internal]``
    promises — reachable from services on the same network, not from
    other networks, not from the public internet.

    Docker's ``internal: true`` is deliberately NOT emitted (mod 110). It
    contributes no ingress protection: cross-network isolation comes from
    Docker's own inter-bridge isolation rules, and the host can reach an
    internal network's containers just as easily since the gateway sits
    in-subnet. Its only real effect is stripping the bridge's masquerade
    rule, which kills egress — contradicting ``networks.md § Egress``
    ("Nothing project-specific or doctrine-emitted is involved") and
    elastic's allow-all SG egress. Do not restore it.

    Per mod 030's naming unification, docker network names — being
    data-plane resolvable identifiers — use hyphens.

    The ``web`` network is special-cased per mod 036: it references the
    project-tier ``${project}-${env}-web`` network owned by projinfra,
    declared ``external: true`` so env compose merely attaches without
    ownership ambiguity. The per-project traefik (also projinfra) spans
    all four ``-web`` networks and the host-wide ``docex-ingress``
    bridge; coexistence on :443 isn't an issue because the HAProxy web
    demux fronts every project. See ``doctrine/infrastructure/specifics/
    projinfra/fixed_reverse_proxy.md``.
    """
    out: dict[str, Any] = {}
    for short in sorted(compiled.networks):
        if short == "web":
            out[short] = {
                "name": f"{compiled.project_dns_label}-{compiled.env}-web",
                "external": True,
            }
            continue
        full = f"{compiled.project_dns_label}-{compiled.env}-{short}"
        out[short] = {"name": full}
    return out


def _traefik_labels(
    svc: CompiledService, project_dns_label: str, env: str,
) -> list[str]:
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

    Mod 047 — `traefik.docker.network` is also mandatory. A `web`-network
    service is on at least two docker networks (the project `-web` net
    that traefik shares + a private `-internal` net that it does not).
    Without an explicit network label, traefik 3.x picks one of the
    container's networks non-deterministically when forming the backend
    URL — often the `-internal` one, which traefik can't reach, so every
    forward times out with a 504. The doctrine network is always the
    project's per-env `-web` net (`<project_dns_label>-<env>-web`); name
    it explicitly so traefik picks it deterministically.
    """
    gname = svc.global_name
    rule = " || ".join(f"Host(`{h}`)" for h in svc.web_hosts)
    web_net = f"{project_dns_label}-{env}-web"
    return [
        "traefik.enable=true",
        f"traefik.docker.network={web_net}",
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
    svc: CompiledService, project_dns_label: str,
    observability_backend_url: str, *, paired_key: str | None = None,
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
    # Mod 100: `paired_key` is the compose key of the container this sidecar
    # shares a netns with — `{global_name}-{i}` on the replica unroll,
    # `{global_name}` otherwise. The sidecar's own name is that key plus
    # `-otelcol`, which keeps the suffix last and `docker logs
    # …-api-web-3-otelcol` readable. Both the name and the netns target derive
    # from the ONE string on purpose: they must agree or the pairing breaks.
    # For every naming policy in the tree the unqualified case is byte-
    # identical to the pre-Mod-100 `{project_dns_label}-{env}-{svc.name}`.
    target = paired_key or svc.global_name
    sidecar_name = f"{target}-otelcol"
    return {
        "image": OTEL_COLLECTOR_IMAGE,
        "container_name": sidecar_name,
        "command": ["--config=/etc/otelcol/config.yaml"],
        "network_mode": f"service:{target}",
        "configs": [
            {"source": "otelcol_config", "target": "/etc/otelcol/config.yaml"},
        ],
        "environment": {
            "OBSERVABILITY_BACKEND_URL": observability_backend_url,
            "TELEMETRY_API_KEY": "${TELEMETRY_API_KEY:-}",
        },
        # Mod 051 (Gap B): stamped on the sidecar too, for label uniformity
        # across every container docex emits on fixed.
        "labels": [_docex_project_label(project_dns_label)],
        "deploy": {
            "resources": {"limits": {"cpus": "0.1", "memory": "128M"}}
        },
        "restart": "unless-stopped",
        "logging": _LoggingAnchor(),
    }


def _replica_networks(svc: CompiledService) -> dict[str, Any]:
    """Convert compose short-form ``networks: [a, b]`` to map form with a
    shared alias, so all N replicas answer to the unqualified name.

    This is what keeps ``provides.host`` — ``${global_service_name}`` on the
    fixed side — working after the unroll: no container is named
    ``{global_name}`` any more, so the name is carried by an alias that
    Docker's embedded DNS resolves to all N containers, round-robin.

    The alias goes on EVERY network the core service joins. A consumer
    resolves the target over whichever network the two share, so restricting
    the alias to non-``web`` networks would break a web→web reference for no
    gain.

    Called only on the unroll path (N > 1). The N == 1 path keeps the
    short-form list byte-for-byte — there is no ``aliases`` handling anywhere
    else in this emitter and none is added.
    """
    return {n: {"aliases": [svc.global_name]} for n in svc.networks}


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
    # Map compiled identity -> compose service key (global name). Its one
    # consumer is the exec block's readiness gate below: `uses` is authored
    # against simple names in infra.yml, but the compose file's service keys
    # are the global names — they must agree or docker compose rejects the
    # file with "depends on undefined service".
    # A core entry here is two-segment (`api-web`) and so never matches a bare
    # authored name. That is safe because the gate reads `uses_backing` only,
    # and a backing service's compiled identity IS its bare name.
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
            # Mod 096: keyed on the CODEBASE, not the compiled identity —
            # `core/<codebase>/` is one source folder shared by every core
            # service.
            bind_mounts = [
                f"./core/{svc.codebase}/src:/service/src",
                f"./core/{svc.codebase}/dist:/service/dist",
            ]
            existing_vols = block.get("volumes")
            if isinstance(existing_vols, list):
                # Preserve any named volumes already set by transfer-table merging.
                block["volumes"] = list(existing_vols) + bind_mounts
            else:
                block["volumes"] = bind_mounts

        # Phase 2: dev and test envs build images locally from the
        # service's Dockerfile rather than pulling from the registry.
        # The doctrine requires every codebase to ship a Dockerfile
        # with build/dev/prod/test stages; we tell compose which stage
        # to target so `docker compose up --build` produces the right
        # image. Stage/prod compose intentionally retains the registry
        # image ref — those envs pull, they don't build.
        if compiled.env in ("dev", "test") and svc.is_core:
            block["build"] = {
                # Mod 096: the codebase, matching the bind mounts above.
                "context": f"./core/{svc.codebase}",
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

        # Mod 115: the clock's schedule table, delivered as one literal env
        # var (clock.md § How the schedule reaches the container). Merged
        # AFTER the project's own `env:` above so a project key cannot shadow
        # it — rule 20 already forbids the collision, and this makes the
        # emission order unambiguous rather than relying on that.
        #
        # WHY `$` -> `$$`: compose interpolates `environment:` values exactly
        # as it interpolates `configs.content` (see the otelcol note below),
        # and on this foundation the payload is ALWAYS a compose env value —
        # so an unescaped `$` would reach the container mangled. Only the
        # DELIVERED value is doubled; `infra/output/<env>/schedules.yml` keeps
        # the true content.
        sched_env = schedule_env(svc)
        if sched_env:
            existing_env = block.get("environment")
            merged_env = dict(existing_env) if isinstance(existing_env, dict) else {}
            for k, v in sched_env.items():
                merged_env[k] = v.replace("$", "$$")
            block["environment"] = merged_env

        # Network-driven routing: any web-network service (core or backing
        # container) gets Traefik discovery labels with its per-service
        # host(s). The machine-wide Traefik routes those subdomains to the
        # container over the docker network — no host port is published.
        # Mod 051 (Gap B): every emitted container also carries the
        # ``docex.project`` label so the project traefik's docker-provider
        # constraint matches only this project's containers. Web services
        # append it to the existing Traefik-label list; non-web services
        # get a fresh labels list with just that one label.
        # Mod 054: the `test` env is excluded from web routing entirely —
        # it is exercised in-container over the internal network and never
        # browsed to, so its web services get NO traefik discovery labels
        # (no router, no `tls`, no certresolver). This stops the project
        # traefik from firing LE HTTP-01 challenges for `test` hostnames
        # that nobody will ever reach, which would otherwise burn the
        # failed-authorization rate limit. They keep the ``docex.project``
        # label (still harmless) and remain on the `-web` network. See
        # cicl.md § TLS Implications / fixed_reverse_proxy.md.
        project_label = _docex_project_label(compiled.project_dns_label)
        if svc.web_hosts and compiled.env != "test":
            block["labels"] = _traefik_labels(
                svc, compiled.project_dns_label, compiled.env,
            ) + [project_label]
        else:
            block["labels"] = [project_label]

        # Mod 100: the replica unroll. `deploy.replicas` CANNOT work here —
        # the collector sidecar pairs via `network_mode: "service:<svc>"` to
        # share the app container's netns, and Compose has no
        # replica-to-replica pairing semantics, so one sidecar cannot pair
        # with N replicas. `deploy.replicas` also forces dropping
        # `container_name` (Compose refuses both together), costing the
        # container-name DNS entry and the readable names operators debug
        # with. So the compiler emits N DISTINCT compose services instead.
        #
        # WHY the traefik labels above are left exactly as they are: they key
        # on the UNQUALIFIED `svc.global_name`, so N containers declare one
        # router and one service and traefik's docker provider loads them as
        # N servers. Qualifying them per replica would produce N routers
        # fighting over one Host() rule. This is a constraint, not an
        # accident — see `tests/unit/test_replicas.py`.
        count = effective_replicas(svc, compiled.env)
        if count == 1:
            services[svc.global_name] = block
        else:
            for i in range(1, count + 1):
                replica_key = f"{svc.global_name}-{i}"
                replica = copy.deepcopy(block)
                replica["container_name"] = replica_key
                replica["networks"] = _replica_networks(svc)
                services[replica_key] = replica

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
        # WHY: project/env/svc joiners and the `-otelcol` suffix all use
        # hyphens per the unified data-plane naming rule (mod 030 flipped
        # joiners; mod 032 flipped the suffix). Docker container names.
        # The project segment is the DNS-labeled form so underscored project
        # names (e.g. `docex_smoke_elastic`) render hyphenated here (mod 046)
        # — which is exactly what `global_name` already is.
        #
        # Mod 100: one sidecar per EMITTED container, not per compiled
        # service. Under the replica unroll the app containers are keyed
        # `{global_name}-{i}`, and each needs its own collector in its own
        # netns.
        count = effective_replicas(svc, compiled.env)
        if count == 1:
            keys = [svc.global_name]
        else:
            keys = [f"{svc.global_name}-{i}" for i in range(1, count + 1)]
        for target in keys:
            services[f"{target}-otelcol"] = _sidecar_block(
                svc, compiled.project_dns_label,
                compiled.observability_backend_url, paired_key=target,
            )

    # Mod 099: one exec service per codebase — the per-codebase operations
    # container. See the module docstring for why it exists and what makes it
    # load-bearing. Emitted in ALL FOUR fixed envs (not just dev/test): the
    # ansible playbook's stage/prod migration runs through it too, which is
    # what makes the codebase-scoped-env rule true in the environment where
    # violating it costs the most.
    #
    # This pass runs LAST among the blocks it reads. Every core, replica,
    # backing, and sidecar block is already in `services` by the time it
    # starts, which is what lets the readiness gate below resolve each
    # target's condition INLINE — no second pass over `services` is needed or
    # wanted. It is also the LAST pass to add service blocks at all; nothing
    # is emitted into `services` after it.
    for codebase, svcs in group_by_codebase(compiled).items():
        head = svcs[0]
        exec_block: dict[str, Any] = {
            # `up` never starts it; `run` implicitly enables the profile of
            # the service it names. The first `profiles:` key in the codebase.
            "profiles": ["exec"],
            # The image ref is codebase-keyed, so it is identical across every
            # core service of the codebase: one tag, one build.
            "image": head.body.get("image", ""),
        }
        if compiled.env in ("dev", "test"):
            # Byte-identical to the app services' build block, so Docker's
            # layer cache makes building the exec image free. stage/prod pull
            # the registry ref, exactly as their app services do.
            exec_block["build"] = {
                "context": f"./core/{codebase}",
                "dockerfile": "Dockerfile",
                "target": compiled.env,
            }
        # WHY `codebase_env` and not `env`: the codebase-scoped surface. It is
        # identical across a codebase's core services by construction (the
        # compiler builds it from the codebase-level `env:` block alone), so
        # reading it off `svcs[0]` picks nothing — there is nothing to pick.
        # Mod 102 made that true of EVERY key: the telemetry identity on this
        # surface is codebase-scoped too (`OTEL_SERVICE_NAME={codebase}`, no
        # `docex.service`), where it previously leaked `svcs[0]`'s
        # service segment.
        if head.codebase_env:
            exec_block["environment"] = _translate_tree(head.codebase_env)
        if compiled.env == "dev":
            # Mirrors the app-service rule exactly: `test` bakes artifacts
            # into the image, stage/prod ship them from the registry.
            exec_block["volumes"] = [
                f"./core/{codebase}/src:/service/src",
                f"./core/{codebase}/dist:/service/dist",
            ]
        exec_nets = sorted({
            n for p in svcs for n in p.networks if n != "web"
        })
        if exec_nets:
            # Never `web`: the exec container is a one-off operations shell
            # and is never publicly routed.
            exec_block["networks"] = exec_nets
        # THE COMPILER'S ONE REMAINING ORDERING EMISSION. `uses` emits nothing
        # onto a core service's own block; the exec block carries the union of
        # its codebase's BACKING-targeted `uses` edges, rewritten to
        # `condition: service_healthy` (cicl.md § Startup ordering is not a
        # doctrine feature; migrations.md § Dev and Test Mechanism).
        #
        # WHY long-form and not compose short-form: short-form waits only for
        # the target container to *start*. Backing services like postgres take
        # measurable time to become reachable after starting, so a `migrate.sh`
        # launched through `compose run` would hit a refused TCP socket and
        # surface as a flaky migration rather than as a compiler bug.
        # `service_healthy` gates on the target's already-declared healthcheck;
        # `service_started` is the fallback when the target declares none
        # (semantically equivalent to short-form). DO NOT downgrade this to a
        # plain list.
        #
        # This is `uses_backing`, never `uses_core`: a one-shot batch job waits
        # on the datastores it writes to, and a core target has no readiness
        # gate to offer anyway.
        exec_deps = sorted({d for p in svcs for d in p.uses_backing})
        if exec_deps:
            long_form: dict[str, Any] = {}
            for dep in exec_deps:
                target_global = simple_to_global.get(dep, dep)
                target_block = services.get(target_global, {})
                long_form[target_global] = {
                    "condition": (
                        "service_healthy" if "healthcheck" in target_block
                        else "service_started"
                    )
                }
            exec_block["depends_on"] = long_form
        exec_block["labels"] = [
            _docex_project_label(compiled.project_dns_label)
        ]
        # Deliberately unset: `container_name` (compose run generates its own
        # `<project>-<svc>-run-<hash>`; a fixed name would collide or be
        # ignored), `logging` (the container is `--rm`, there is no post-hoc
        # log to rotate), `command` (supplied at the call site — the core
        # service Dockerfiles declare no ENTRYPOINT, so `run --rm …-exec
        # ./migrate.sh` executes the script directly under WORKDIR /service),
        # `restart`, and `healthcheck`.
        #
        # `healthcheck` is the one that needs stating, because mod 127 made
        # `./health.sh <service>` a role-table DEFAULT, so every core service
        # block now carries one and this block sits beside them. Per
        # specifics/exec_service.md and healthchecks.md, `health.sh` is the one
        # codebase shim that does NOT run here: the exec container is a
        # one-off that runs a script and exits, and its own liveness question
        # is answered by the exit code it was invoked for. A `healthcheck:`
        # here would additionally change what `depends_on: service_healthy`
        # means for anything gating on this block, and compose would report a
        # `--rm` one-shot as `health: starting`.
        #
        # WHY it is safe: `exec_block` is built key-by-key as a fresh dict and
        # reads exactly ONE key off a core service (`head.body.get("image")`),
        # so it inherits nothing from `svc.body` and cannot pick a role
        # default up by accident. This comment is what keeps that true —
        # anyone reaching for a whole-body copy here has to read it first.
        services[f"{head.codebase_global_name}-exec"] = exec_block

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
    configs: dict[str, Any] = {}
    if any(s.is_core for s in compiled.services.values()):
        content = render_otelcol_config(compiled.env).replace("$", "$$")
        configs["otelcol_config"] = {"content": content}

    if configs:
        body_doc["configs"] = configs

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


def emit_project_compose(*, project_dns_label: str, out_path: Path) -> None:
    """Emit a project-tier compose file declaring the four
    ``${project_dns_label}-${env}-web`` external networks plus the
    ``docex-ingress`` preinfra network reference, AND the per-project
    traefik container that joins all five networks and terminates TLS
    for the project.

    Per ``doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy
    .md``, the traefik container is named ``${project_dns_label}-traefik``,
    uses the cert resolver handle ``doctrine`` (referenced by env-tier
    service labels), mounts the docker socket read-only for service-
    discovery, and persists ACME state to the named volume
    ``${project_dns_label}-traefik-acme`` so certs survive container
    restarts and ``projinfra down/up`` cycles.

    The ``project_dns_label`` argument is the DNS-labeled form of the
    project name (underscores → hyphens, lowercased). Every name emitted
    here is a docker container/network/volume identifier and therefore a
    data-plane resolvable name; underscored project names (e.g.
    ``docex_smoke_elastic``) must hyphenate here. The HAProxy web demux
    parses the project segment out of the request domain (PSL-aware, so
    multi-label TLDs like ``.co.uk`` work — mod 058) and forwards to a
    container named ``<project>-traefik``; that parsed segment is the
    DNS-labeled form, so the traefik container's name must match. Mod 046.

    Both the development and production sides emit this same body shape
    (single-machine fixed projects converge on the same docker daemon).
    Side-specific differences live elsewhere: HCL on elastic production,
    ansible artifacts when fixed prod is remote (deferred per mod 036).

    Mod 051 (Gap A): cert issuance uses the HTTP-01 challenge (served on
    the ``web`` entrypoint, :80, which the HAProxy demux already forwards
    by Host header). HTTP-01 needs no DNS-provider credentials, so the only
    operator-supplied value is ``TRAEFIK_ACME_EMAIL`` (LE account
    registration). Out-of-box issuance works once the operator sets that.

    Mod 051 (Gap B): the docker provider is constrained to
    ``Label(`docex.project`,`<project_dns_label>`)`` so this traefik
    registers routers only for its own project's containers — not every
    ``traefik.enable=true`` container on the shared ``docex-ingress``
    bridge. Every container docex emits on fixed carries the matching
    ``docex.project`` label (see :func:`_docex_project_label`).
    """
    acme_volume = f"{project_dns_label}-traefik-acme"
    data: dict[str, Any] = {
        "networks": {
            f"{project_dns_label}-dev-web": {
                "name": f"{project_dns_label}-dev-web"
            },
            f"{project_dns_label}-test-web": {
                "name": f"{project_dns_label}-test-web"
            },
            f"{project_dns_label}-stage-web": {
                "name": f"{project_dns_label}-stage-web"
            },
            f"{project_dns_label}-prod-web": {
                "name": f"{project_dns_label}-prod-web"
            },
            "docex-ingress": {"external": True},
        },
        "services": {
            f"{project_dns_label}-traefik": {
                "image": TRAEFIK_IMAGE,
                "container_name": f"{project_dns_label}-traefik",
                "restart": "unless-stopped",
                "networks": [
                    f"{project_dns_label}-dev-web",
                    f"{project_dns_label}-test-web",
                    f"{project_dns_label}-stage-web",
                    f"{project_dns_label}-prod-web",
                    "docex-ingress",
                ],
                "volumes": [
                    "/var/run/docker.sock:/var/run/docker.sock:ro",
                    f"{acme_volume}:/letsencrypt",
                ],
                "command": [
                    "--providers.docker=true",
                    "--providers.docker.exposedbydefault=false",
                    "--providers.docker.constraints="
                    f"Label(`docex.project`,`{project_dns_label}`)",
                    "--entrypoints.web.address=:80",
                    "--entrypoints.websecure.address=:443",
                    "--certificatesresolvers.doctrine.acme.email="
                    "${TRAEFIK_ACME_EMAIL:-}",
                    "--certificatesresolvers.doctrine.acme.storage="
                    "/letsencrypt/acme.json",
                    "--certificatesresolvers.doctrine.acme.httpchallenge=true",
                    "--certificatesresolvers.doctrine.acme.httpchallenge"
                    ".entrypoint=web",
                ],
                "labels": [_docex_project_label(project_dns_label)],
            },
        },
        # Explicit ``name:`` so the real volume is exactly
        # ``${project_dns_label}-traefik-acme`` (matching
        # ``fixed_reverse_proxy.md`` and the env-tier volume pattern).
        # Without it, Compose prefixes the volume with the project name
        # and reality diverges from the doctrine (mod 053 / Cluster 1).
        "volumes": {acme_volume: {"name": acme_volume}},
    }
    header = (
        "# Generated by `docex compile`. Do not edit by hand.\n"
        f"# project: {project_dns_label}\n"
        "# tier: project (mod 036: 4 -web networks + per-project traefik)\n"
    )
    out_path.write_text(header + _dump_compose(data))
