"""JSON renderer for ``docex describe <env> llm``."""

from __future__ import annotations

import json

from docex.cicl.compile import CompiledEnv
from docex.describe.dag import (
    _PREREQ_FIXED,
    _PREREQ_ELASTIC,
    _PROJECT_FIXED,
    _PROJECT_ELASTIC,
    collect_edges,
    node_id,
    target_id,
)


def render_llm(compiled: CompiledEnv) -> str:
    prereq = _PREREQ_FIXED if compiled.foundation == "fixed" else _PREREQ_ELASTIC
    project = _PROJECT_FIXED if compiled.foundation == "fixed" else _PROJECT_ELASTIC

    env_resources: list[dict[str, object]] = []
    # WHY: the project-tier reverse proxy is no longer a CICL service (mod 031
    # removed the `reverse_proxy` role). Its describe representation is
    # project-tier work landing in mods 036/038 — for now the synthetic
    # env-tier node is dropped rather than misrepresenting tier or shape.
    for n in sorted(compiled.networks):
        env_resources.append({
            "kind": "network",
            "name": f"{compiled.project}_{compiled.env}_{n}",
            "short": n,
            "means": "docker network" if compiled.foundation == "fixed" else "AWS security group",
        })
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        env_resources.append({
            "kind": "core_service" if svc.is_core else "backing_service",
            "name": svc.global_name,
            "short": node_id(svc),
            # Both axes independently readable, so a consumer never splits a
            # hyphenated string to recover them (the same argument Mod 102 made
            # for two OTel attributes over one fused `service.name`). None for a
            # backing service, which has no service dimension.
            "codebase": svc.codebase,
            "service": svc.service,
            "role": svc.role,
            "engine": svc.engine,
            "networks": svc.networks,
            "port": svc.port,
            "depends_on": svc.depends_on,
            # Display ids, so a node's relations join to node `short` values
            # exactly as `depends_on` already does.
            "consumes": [target_id(compiled, k) for k in svc.consumes],
        })

    edges = [
        {"from": src, "to": dst, "kind": kind}
        for src, dst, kind in collect_edges(compiled)
    ]

    doc = {
        "project": compiled.project,
        "version": compiled.project_version,
        "env": compiled.env,
        "foundation": compiled.foundation,
        "apex_domain": compiled.apex_domain,
        "subdomain": compiled.subdomain,
        "tiers": {
            "prerequisite": [{"name": n, "description": d} for n, d in prereq],
            "project": [{"name": n, "description": d} for n, d in project],
            "environment": env_resources,
        },
        "edges": edges,
    }
    return json.dumps(doc, indent=2, sort_keys=True)
