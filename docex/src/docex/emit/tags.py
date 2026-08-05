"""Standard elastic resource tags. Mod 060. The one place the three
doctrine tag blocks (cicl.md § Naming and Tagging) are formed, so every
emit site and the bootstrap API path agree."""
from __future__ import annotations


def standard_tags(
    tier: str,                  # "prerequisite" | "project" | "environment"
    *,
    shape_name: str,
    descriptor: str,
    project: str | None = None,
    env: str | None = None,
    codebase: str | None = None,  # "etc" for env-scoped resources
    role: str | None = None,      # "etc" for env-scoped resources
    # Mod 096. Present on env-tier resources that belong to a specific core
    # service; omitted for backing services, which have none (cicl.md §
    # Elastic Foundation). A backing service's tag block is therefore
    # byte-identical to what it was before core-service expansion.
    service: str | None = None,
) -> dict[str, str]:
    managed_by = "doctrine-operator" if tier == "prerequisite" else "doctrine"
    tags = {
        "managed_by": managed_by,
        "infra_tier": tier,
        "shape_name": shape_name,
        "descriptor": descriptor,
    }
    if tier == "prerequisite":
        tags["Name"] = f"{shape_name}_{descriptor}"
        return tags
    # project + environment both carry project + Name
    assert project is not None
    tags["project"] = project
    if tier == "project":
        tags["Name"] = f"{project}_{shape_name}_{descriptor}"
        return tags
    # environment
    assert env is not None and codebase is not None and role is not None
    tags["env"] = env
    tags["codebase"] = codebase
    tags["role"] = role
    if service is not None:
        tags["service"] = service
    # Name uses the codebase when it's a real one; falls back to descriptor for
    # env-scoped resources (codebase == "etc") so Names stay unique (decision 2).
    #
    # WHY: the segment order is (codebase, service) — the same order the old
    # (service, process) pair rendered in — so every emitted Name is
    # byte-identical across the 1.7.0 rename. Only the tag KEYS moved.
    name_seg = descriptor if codebase == "etc" else codebase
    if service is not None and codebase != "etc":
        name_seg = f"{codebase}_{service}"
    tags["Name"] = f"{project}_{env}_{name_seg}"
    return tags


def render_hcl_tags(tags: dict[str, str], indent: str = "  ") -> str:
    """Render a tags dict as an HCL ``tags = { … }`` block body line."""
    inner = ", ".join(f'{k} = "{v}"' for k, v in tags.items())
    return f"{indent}tags = {{ {inner} }}"
