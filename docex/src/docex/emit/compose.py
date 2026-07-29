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

from docex import OFELIA_IMAGE, OTEL_COLLECTOR_IMAGE, TRAEFIK_IMAGE
from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.substitute import HCLLiteral
from docex.emit.otelcol import render_otelcol_config


# Runtime-ref pattern matches $[VAR_NAME].
_RUNTIME_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")

# Full-match form of the runtime-ref pattern: an env value that is a bare
# $[VAR] (a secret), as opposed to a literal or a composed string. The
# parts-only rule (compile.py) guarantees a secret value is exactly this.
_RUNTIME_FULL_RE = re.compile(r"^\$\[([A-Z_][A-Z0-9_]*)\]$")


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
    named ``${project}-${env}-${shortname}`` with ``internal: true``.
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
        out[short] = {"name": full, "internal": True}
    return out


def _traefik_labels(
    svc: CompiledService, project_dns_label: str, env: str,
) -> list[str]:
    """Traefik discovery labels for a web-network service.

    The router rule ORs together every host the service answers at — a
    service is reachable at ``<service>.<env>.<project>.<apex_domain>``,
    and the ``domain_default_process`` additionally at the bare
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
    svc: CompiledService, project_dns_label: str, env: str,
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
    sidecar_name = f"{project_dns_label}-{env}-{svc.name}-otelcol"
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
        # Mod 051 (Gap B): stamped on the sidecar too, for label uniformity
        # across every container docex emits on fixed.
        "labels": [_docex_project_label(project_dns_label)],
        "deploy": {
            "resources": {"limits": {"cpus": "0.1", "memory": "128M"}}
        },
        "restart": "unless-stopped",
        "logging": _LoggingAnchor(),
    }


# Shell-safe characters that never need quoting in a command argument.
_SHELL_SAFE_RE = re.compile(r"^[A-Za-z0-9_./:=@%+-]+$")


def _shell_quote(arg: str) -> str:
    """POSIX single-quote a shell argument so it survives the ``sh -c``
    wrapper unmodified — but only when it actually needs quoting, so the
    common ``python -m jobs.cleanup`` case stays human-readable. Embedded
    single quotes use the ``'\\''`` idiom.
    """
    if arg and _SHELL_SAFE_RE.match(arg):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"


def _wrapped_job_command(
    command: Any, env_file_target: str, secret_exports: list[tuple[str, str]],
) -> str:
    """Build the ofelia ``command =`` value for a scheduler job.

    The one-off job container must see the env's secrets, which ofelia
    cannot deliver itself (it spawns the container outside Compose, so
    Compose's ``.env`` interpolation never reaches it). Secrets arrive via
    a mounted env file the command sources before exec'ing the real job.
    But the sourced ``.env`` carries the *provider* secret names
    (``POSTGRES_USER``) while the job reads the *consumer* keys
    (``DATABASE_USER``) — a mapping Compose does for ordinary services but
    the raw Docker-API job does not get. So we re-export each secret key
    from its provider var before exec (mod 075):

        sh -c '. /run/job.env && export DATABASE_USER="$POSTGRES_USER" && exec <cmd>'

    ``secret_exports`` is the sorted list of ``(consumer_key,
    provider_var)`` pairs. The ``$`` on the provider var is **doubled**
    (``$$``) so Compose — which interpolates ``configs.content`` — passes
    the literal ``$POSTGRES_USER`` through to the rendered config, and the
    job shell (not Compose) expands it from the sourced file at run time.
    That keeps the secret value out of the rendered config
    (scheduler.md § Env and secret delivery).

    ``command`` is the model's ``str | list[str]`` form; a list is joined
    with shell quoting, a string is passed through verbatim.
    """
    if isinstance(command, list):
        cmd = " ".join(_shell_quote(str(c)) for c in command)
    else:
        cmd = str(command)
    parts = [f". {env_file_target}"]
    for key, var in secret_exports:
        # `$$` so Compose emits a literal `$`; the job shell expands it.
        parts.append(f'export {key}="$${var}"')
    parts.append(f"exec {cmd}")
    return "sh -c '" + " && ".join(parts) + "'"


def _ofelia_ini(
    svc: CompiledService, project_dns_label: str, env: str,
    env_file_source: str,
) -> str:
    """Render the ofelia INI for one scheduler service.

    One ``[job-run "<svc>"]`` section: the translated 6-field ofelia
    schedule, the service's image, the job's docker network (its first
    non-``web`` network — a scheduler is never on ``web``), ``delete =
    true`` to auto-remove the one-off container, the NON-secret env
    inlined into ``environment``, the secret-sourcing + re-exporting
    command wrapper, and the env-file mount. See scheduler.md § Fixed
    Foundation.

    ``env_file_source`` is the **absolute** host path of the env file the
    job sources — ``${DOCEX_SECRETS_ENV_FILE}`` in ``dev``/``test`` (docex
    sets it at ``up`` time; a relative source fails at the Docker API) or
    the baked ``/opt/<project>/<env>/.env`` in fixed ``stage``/``prod``
    (mod 075).
    """
    from docex.cicl.cron import to_ofelia_cron

    env_file_target = "/run/job.env"
    image = svc.body.get("image", "")
    # The job's docker network: the service's first non-web network,
    # rendered to its project-scoped data-plane name. Schedulers are never
    # on `web`, so a non-web network is expected; fall back gracefully.
    job_nets = [n for n in svc.networks if n != "web"]
    network_name = (
        f"{project_dns_label}-{env}-{job_nets[0]}" if job_nets else ""
    )

    # Env/secret split: a bare $[VAR] value is a secret; everything else is
    # a non-secret literal inlined into `environment`. The two sets are
    # disjoint per the parts-only rule. Secrets are NOT inlined — they are
    # sourced from the mounted env file, then re-exported from their
    # provider var to the consumer key (mod 075).
    env_pairs: list[str] = []
    secret_exports: list[tuple[str, str]] = []
    for key in sorted(svc.env):
        val = svc.env[key]
        if isinstance(val, str) and (m := _RUNTIME_FULL_RE.match(val)):
            # secret — provider var name is the captured group; re-exported
            # to `key` (the consumer name) after the env file is sourced.
            secret_exports.append((key, m.group(1)))
            continue
        # HCLLiteral never appears on fixed; treat any non-secret value as
        # a literal string for inlining.
        env_pairs.append(f"{key}={val}")

    schedule = to_ofelia_cron(svc.schedule) if svc.schedule else ""
    command = _wrapped_job_command(
        svc.body.get("command", ""), env_file_target, secret_exports,
    )

    # Ofelia's INI uses gcfg: repeatable list fields (`environment`,
    # `volume`) are expressed as one bare `key = value` line PER entry, NOT
    # as a JSON array (mod 075 fix — the JSON-array form emitted through mod
    # 055 was mis-parsed by ofelia: it took the literal `["…` as a volume
    # name / env string, so no fixed scheduler job ever ran). Verified
    # end-to-end against mcuadros/ofelia:v0.3.7.
    lines = [
        f'[job-run "{svc.name}"]',
        f"schedule = {schedule}",
        f"image = {image}",
        f"network = {network_name}",
        "delete = true",
    ]
    lines += [f"environment = {p}" for p in env_pairs]
    lines.append(f"command = {command}")
    lines.append(f"volume = {env_file_source}:{env_file_target}:ro")
    return "\n".join(lines) + "\n"


def _ofelia_block(
    svc: CompiledService, project_dns_label: str, env: str, config_key: str,
) -> dict[str, Any]:
    """Render the ofelia scheduler container for one scheduler service.

    The container reads its INI from compose's top-level ``configs:``
    block (the same delivery mechanism the OTel sidecar uses) and mounts
    the docker socket read-only so it can spawn the job's one-off
    container (the DooD-adjacent pattern the project traefik also uses).
    No traefik labels (a scheduler is never web-facing); it carries the
    ``docex.project`` label and ``restart: unless-stopped`` like every
    emitted container. See scheduler.md § Fixed Foundation.
    """
    name = f"{project_dns_label}-{env}-{svc.name}-scheduler"
    return {
        "image": OFELIA_IMAGE,
        "container_name": name,
        "command": ["daemon", "--config=/etc/ofelia/config.ini"],
        "restart": "unless-stopped",
        "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
        "configs": [
            {"source": config_key, "target": "/etc/ofelia/config.ini"},
        ],
        "labels": [_docex_project_label(project_dns_label)],
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
    # Map compiled identity -> compose service key (global name). depends_on
    # is authored against simple names in infra.yml, but the compose file's
    # service keys are the global names — they must agree or docker compose
    # rejects the file with "depends on undefined service".
    # Mod 096: the keys are now compiled identities, so a core entry is
    # two-segment (`api-web`) and no longer matches a bare authored name.
    # That is safe because rule 24 forbids a core `depends_on` target
    # outright — every authored edge names a backing service, whose compiled
    # identity is still its bare name.
    simple_to_global = {
        n: s.global_name for n, s in compiled.services.items()
    }
    for name in sorted(compiled.services):
        svc = compiled.services[name]

        # Mod 055: a scheduler service does not run as a long-running
        # container. Its job is launched by a paired ofelia container
        # (emitted below) as a one-off container on each fire, so we skip
        # the normal service block for the job itself.
        if svc.role == "scheduler":
            continue

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
            # `core/<svc>/` is one source folder shared by every process type.
            bind_mounts = [
                f"./core/{svc.core_service}/src:/service/src",
                f"./core/{svc.core_service}/dist:/service/dist",
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
                # Mod 096: the codebase, matching the bind mounts above.
                "context": f"./core/{svc.core_service}",
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
        # Mod 055: scheduler services have no long-running container to
        # share a netns with, so no paired sidecar (consistent with the
        # elastic side). Job-level SDK telemetry is deferred.
        if svc.role == "scheduler":
            continue
        # WHY: project/env/svc joiners and the `-otelcol` suffix all use
        # hyphens per the unified data-plane naming rule (mod 030 flipped
        # joiners; mod 032 flipped the suffix). Docker container names.
        # The project segment is the DNS-labeled form so underscored project
        # names (e.g. `docex_smoke_elastic`) render hyphenated here (mod 046).
        sidecar_name = (
            f"{compiled.project_dns_label}-{compiled.env}-{svc.name}-otelcol"
        )
        services[sidecar_name] = _sidecar_block(
            svc, compiled.project_dns_label, compiled.env,
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
    configs: dict[str, Any] = {}
    if any(
        s.is_core and s.role != "scheduler"
        for s in compiled.services.values()
    ):
        content = render_otelcol_config(compiled.env).replace("$", "$$")
        configs["otelcol_config"] = {"content": content}

    # Mod 055: ofelia scheduler containers + their rendered INI configs.
    # Each scheduler service gets one ofelia container and one INI config
    # entry. The INI is delivered inline via compose's `configs.content`
    # (self-contained, the same mechanism the otelcol sidecar config uses)
    # so the compose file travels to the deploy host without a sidecar
    # file.
    #
    # Env-file mount source (scheduler.md § Env and secret delivery, mod
    # 075): ofelia spawns the job via the docker socket (DooD, NOT Compose),
    # so the host side of the mount must be an ABSOLUTE path the docker
    # daemon resolves — a relative source fails at the Docker API.
    #   - stage/prod (fixed): the deterministic ansible deploy path
    #     `/opt/<project>/<env>/.env`, baked here (matches the migrate
    #     one-off's `env_file`). `project` is the raw name, matching
    #     emit/ansible.py's `deploy_root`.
    #   - dev/test: the path is the operator's machine-specific project
    #     root, so baking it would break compile determinism. Emit
    #     `${DOCEX_SECRETS_ENV_FILE}` instead; `docex up` sets that var to
    #     the absolute `infra/secrets/<env>.env` and Compose interpolates
    #     it into the rendered config. (test suppresses the scheduler
    #     entirely, so in practice this is the dev path.)
    if compiled.env in ("dev", "test"):
        env_file_source = "${DOCEX_SECRETS_ENV_FILE}"
    else:
        env_file_source = f"/opt/{compiled.project}/{compiled.env}/.env"
    # Mod 073: the `test` env drops the scheduler trigger entirely. A
    # scheduler is otherwise inert (no long-running container in any env),
    # so skipping the ofelia container + its INI here means a scheduler
    # service produces NO output in `test` and its job never fires inside
    # the test window. Because `dev`/`test` are always fixed → compose,
    # the ofelia container is the only trigger `test` could carry (the
    # elastic EventBridge path is never reached for `test`), so this one
    # guard fully suppresses it. Mirrors the mod-054 web-label exclusion
    # above. See scheduler.md § Caveats.
    if compiled.env != "test":
        for name in sorted(compiled.services):
            svc = compiled.services[name]
            if svc.role != "scheduler":
                continue
            ofelia_name = (
                f"{compiled.project_dns_label}-{compiled.env}-{svc.name}-scheduler"
            )
            config_key = f"ofelia_{svc.name}"
            services[ofelia_name] = _ofelia_block(
                svc, compiled.project_dns_label, compiled.env, config_key,
            )
            ini = _ofelia_ini(
                svc, compiled.project_dns_label, compiled.env,
                env_file_source,
            )
            configs[config_key] = {"content": ini}

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
