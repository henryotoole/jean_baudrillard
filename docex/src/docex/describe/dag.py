"""Text DAG renderer for ``docex describe <env> dag``.

Output groups resources by infrastructure tier (prerequisite / project
/ environment), then renders ``depends_on`` edges between environment
services as arrows. The format is plain ASCII so it greps and copies
cleanly out of a terminal.
"""

from __future__ import annotations

from docex.cicl.compile import CompiledEnv


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
            lines.append(f"  - network:{n:<16} {full}  ({kind})")
    # Services.
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        kind = "core" if svc.is_core else "backing"
        lines.append(
            f"  - {kind}:{name:<19} {svc.global_name}  "
            f"[role={svc.role}, engine={svc.engine}, networks={svc.networks}]"
        )
    lines.append("")

    # Depends-on edges.
    edges: list[tuple[str, str]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for dep in sorted(svc.depends_on):
            edges.append((name, dep))
    if edges:
        lines.append("depends_on edges:")
        for src, dst in edges:
            lines.append(f"  {src} -> {dst}")

    return "\n".join(lines)
