"""Render the traefik dynamic-routing config for ec2_traefik projects.

An ``ec2_traefik_*`` elastic project runs a single traefik instance that
serves BOTH stage and prod. traefik's file provider reads a dynamic config
synced from an SSM parameter (created as an empty stub by projinfra). This
module renders that config from compiled state so ``docex release`` can push
the real routes. See ec2_traefik.md § Routing Discovery / § Config Delivery.

Only *core* services on the ``web`` network route (mirrors the ALB path in
``emit/hcl.py``: ``_web_core = [s for s in core if "web" in s.networks]``);
managed backing services on ``web`` are not proxy targets.
"""

from __future__ import annotations

import yaml

from docex.cicl.compile import CompiledEnv

# Empty stub matching the projinfra-created SSM parameter default. Returned
# when no core web services exist across any env, so a release still converges
# the param to a valid (empty) config rather than leaving a stale one.
_EMPTY_STUB = "http:\n  routers: {}\n  services: {}\n"


def render_traefik_dynamic_config(compiled_envs: list[CompiledEnv]) -> str:
    """Render the traefik dynamic config YAML for the given compiled envs.

    One router + service is emitted per core web-network service per env,
    keyed ``<svc.name>-<env>``. The router matches ``svc.web_hosts`` and
    proxies to the ECS Service Connect FQDN on the container port. Keys are
    sorted for deterministic output. Returns the empty stub when there are
    no core web services across all envs.
    """
    routers: dict[str, dict] = {}
    services: dict[str, dict] = {}

    for compiled in compiled_envs:
        for svc in compiled.services.values():
            if not (svc.is_core and "web" in svc.networks):
                continue
            key = f"{svc.name}-{compiled.env}"
            # Backticks are literal in the traefik host-matcher rule.
            rule = " || ".join(f"Host(`{h}`)" for h in svc.web_hosts)
            routers[key] = {
                "rule": rule,
                "service": key,
                "tls": {"certResolver": "doctrine"},
            }
            url = (
                f"http://{svc.global_name}."
                f"{compiled.project_dns_label}-{compiled.env}:{svc.port}"
            )
            services[key] = {"loadBalancer": {"servers": [{"url": url}]}}

    if not routers:
        return _EMPTY_STUB

    return yaml.safe_dump(
        {"http": {"routers": routers, "services": services}},
        sort_keys=True,
    )
