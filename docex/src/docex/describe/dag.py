"""Text DAG renderer for ``docex describe <env> dag``.

Output groups resources by infrastructure tier (prerequisite / project
/ environment), then renders the ONE relation — ``uses`` — between environment
services as arrows of two kinds, DERIVED FROM TARGET KIND: a backing target is
solid ``->``, a core target is dashed ``..>``. The rendered graph is directed
and may legally contain cycles, because a cycle among core targets is legal
and is the most common web/worker topology there is (cicl.md § The graph may
contain cycles). The format is plain ASCII so it greps and copies cleanly out
of a terminal.
"""

from __future__ import annotations

from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.model import ServiceRef


_PREREQ_FIXED = [
    ("registrar", "domain registrar (NameSilo, GoDaddy, etc.)"),
    ("dns", "registrar's DNS configuration"),
    ("host_machine", "the on-prem server"),
    # WHY: machine-wide traefik is preinfra but the per-project reverse proxy
    # is project-tier (cicl.md § Reverse Proxy). Project-tier describe shows
    # up in mods 036/038; until then, no reverse_proxy node is emitted here.
    ("cert_manager", "traefik + Let's Encrypt"),
    ("container_registry", "Docker Registry V2 (project-pinned)"),
]

_PREREQ_ELASTIC = [
    ("aws_account", "the project's AWS account"),
    ("registrar", "domain registrar (NS-delegated to Route53)"),
]

_PROJECT_FIXED = [
    ("service_discovery", "docker network DNS"),
    ("build_image", "docker container images"),
]

_PROJECT_ELASTIC = [
    ("dns", "Route53 hosted zone"),
    ("vpc", "AWS VPC + subnets"),
    ("cert_manager", "ACM cert for *.<domain>"),
    ("container_registry", "AWS ECR"),
    ("build_image", "docker container images"),
]


def node_id(svc: CompiledService) -> str:
    """The display id of one compiled service — a ``describe`` node id.

    Dotted for a core service (``api.web``), bare for a backing service
    (``appdb``), per cicl.md § Dots for reference, hyphens for emission, which
    names ``describe`` node ids in its dotted list. The compiled key is
    hyphenated (``api-web``) and does not decompose, since both segments may
    themselves contain ``-``; a view whose whole purpose is human understanding
    uses the reference form and shows the emitted name beside it.
    """
    if svc.codebase is not None and svc.service is not None:
        return ServiceRef(svc.codebase, svc.service).dotted
    return svc.name


def target_id(compiled: CompiledEnv, key: str) -> str:
    """Display id for an edge target named by its compiled key.

    Falls back to the raw key when the target is absent. ``run_describe`` calls
    ``compile_env`` WITHOUT ``validate_document``, so a document with an
    unresolvable ``uses`` target reaches the renderer; ``describe`` is
    purely illustrative and must degrade to printing an odd token rather than
    raise.
    """
    target = compiled.services.get(key)
    return node_id(target) if target is not None else key


def collect_edges(compiled: CompiledEnv) -> list[tuple[str, str, str]]:
    """Every ``uses`` edge, as ``(from_id, to_id, kind)``.

    ``kind`` is the TARGET's kind — ``uses_backing`` or ``uses_core`` — not a
    second relation. There is one relation and two renderings of its edges.

    The single derivation behind both renderers. ``llm.py`` ran a second,
    independent copy of this loop until Mod 104: there is one graph and two
    *renderings* of it, so there is one derivation.

    Backing-targeted edges first, each group sorted by source then target, so
    the output is order-stable.

    A flat pass over ``CompiledEnv.services`` — deliberately NOT a graph walk.
    The ``uses`` graph is a cyclic digraph by doctrine (``web ↔ worker`` is
    legal and the most common topology there is), so a traversal here would
    need a visited set and would be one forgotten line away from unbounded
    recursion. Keep it flat: there is no traversal to get wrong.
    """
    edges: list[tuple[str, str, str]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for dep in sorted(svc.uses_backing):
            edges.append((node_id(svc), target_id(compiled, dep), "uses_backing"))
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for used in sorted(svc.uses_core):
            edges.append((node_id(svc), target_id(compiled, used), "uses_core"))
    return edges


def render_dag(compiled: CompiledEnv) -> str:
    lines: list[str] = []
    lines.append(f"# {compiled.project} v{compiled.project_version} — {compiled.env}")
    lines.append(f"#   foundation: {compiled.foundation}")
    lines.append(f"#   subdomain: {compiled.subdomain}")
    lines.append("")

    # Prerequisite tier.
    lines.append("Prerequisite Infrastructure")
    prereq = _PREREQ_FIXED if compiled.foundation == "fixed" else _PREREQ_ELASTIC
    for name, desc in prereq:
        lines.append(f"  - {name:<24} {desc}")
    lines.append("")

    # Project tier.
    lines.append("Project Infrastructure")
    project = _PROJECT_FIXED if compiled.foundation == "fixed" else _PROJECT_ELASTIC
    for name, desc in project:
        lines.append(f"  - {name:<24} {desc}")
    lines.append("")

    # Environment tier.
    # WHY: the elastic ALB / fixed project Traefik is project-tier infra (per
    # mod 031 + cicl.md § Reverse Proxy), so it no longer appears here under
    # environment infrastructure. Project-tier describe arrives in mods
    # 036/038.
    lines.append(f"Environment Infrastructure ({compiled.env})")
    networks = sorted(compiled.networks)
    if networks:
        for n in networks:
            full = f"{compiled.project}_{compiled.env}_{n}"
            kind = "docker network" if compiled.foundation == "fixed" else "AWS security group"
            label = f"network:{n}"
            lines.append(f"  - {label:<24} {full}  ({kind})")
    # Services.
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        kind = "core" if svc.is_core else "backing"
        # WHY the pad spans `kind:id` and not the id alone: padding the id left
        # the `core:` and `backing:` rows in different columns.
        label = f"{kind}:{node_id(svc)}"
        lines.append(
            f"  - {label:<24} {svc.global_name}  "
            f"[role={svc.role}, engine={svc.engine}, networks={svc.networks}]"
        )
    lines.append("")

    # One relation, two target kinds, visually distinguished. The kind is
    # carried TWICE — glyph and heading — because this output is as often
    # grepped as read: `grep uses` must find the edges. `->` / `..>` is
    # mermaid's solid/dashed (`-->` / `-.->`) rendered in ASCII.
    edges = collect_edges(compiled)
    groups: list[list[str]] = []
    for kind, heading, arrow in (
        ("uses_backing", "uses edges (backing target) — solid:", "->"),
        ("uses_core", "uses edges (core target) — dashed:", "..>"),
    ):
        rendered = [
            f"  {src} {arrow} {dst}" for src, dst, k in edges if k == kind
        ]
        if rendered:
            groups.append([heading, *rendered])
    for i, group in enumerate(groups):
        if i:
            lines.append("")
        lines.extend(group)

    return "\n".join(lines)
