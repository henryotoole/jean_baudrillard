"""JSON renderer for ``docex describe <env> llm``."""

from __future__ import annotations

import json

from docex.cicl.compile import CompiledEnv
from docex.describe.dag import (
    _PREREQ_FIXED,
    _PREREQ_ELASTIC,
    _PROJECT_FIXED,
    _PROJECT_ELASTIC,
)


def render_llm(compiled: CompiledEnv) -> str:
    prereq = _PREREQ_FIXED if compiled.foundation == "fixed" else _PREREQ_ELASTIC
    project = _PROJECT_FIXED if compiled.foundation == "fixed" else _PROJECT_ELASTIC

    env_resources: list[dict[str, object]] = []
    if compiled.foundation == "elastic":
        env_resources.append({
            "kind": "reverse_proxy",
            "name": f"{compiled.project}-{compiled.env}-alb",
            "means": "AWS ALB",
        })
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
            "short": svc.name,
            "role": svc.role,
            "engine": svc.engine,
            "networks": svc.networks,
            "port": svc.port,
            "depends_on": svc.depends_on,
        })

    edges: list[dict[str, str]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for dep in sorted(svc.depends_on):
            edges.append({"from": name, "to": dep, "kind": "depends_on"})

    doc = {
        "project": compiled.project,
        "version": compiled.project_version,
        "env": compiled.env,
        "foundation": compiled.foundation,
        "domain": compiled.domain,
        "subdomain": compiled.subdomain,
        "tiers": {
            "prerequisite": [{"name": n, "description": d} for n, d in prereq],
            "project": [{"name": n, "description": d} for n, d in project],
            "environment": env_resources,
        },
        "edges": edges,
    }
    return json.dumps(doc, indent=2, sort_keys=True)
