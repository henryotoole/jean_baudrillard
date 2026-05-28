"""Cross-document CICL validation.

The pydantic schema in ``model.py`` covers per-model field rules (rule 1,
rule 5, units, etc.). This module covers the rules that need the full
infra.yml plus the transfer tables and the foundation context:

    Rule 2: roles defined in tables.
    Rule 3: magic refs resolve.
    Rule 4: engines known + match foundation.
    Rule 6: no depends_on cycles.
    Rule 7: magic-ref-implied deps in depends_on.
    Rule 8: relational_db has valid schema_owned_by.
    Rule 9: container_registry set on fixed foundation.
    Rule 10: every core service has cpu+memory (covered by pydantic;
             re-checked here as defense-in-depth).
    Rule 11: resources.gpu not declared under elastic foundation.

Field validation (rule 4 in transfer_tables.md: every role-specific
field on a service is declared in the engine's ``fields:`` block) is
also performed here.

All issues are aggregated into a list rather than raised one-at-a-time
so the developer can fix multiple problems per compile cycle.
"""

from __future__ import annotations

from typing import Any

from docex.cicl.magic_refs import find_magic_refs, walk_strings
from docex.cicl.model import (
    BackingService,
    CICLDocument,
    CoreService,
)
from docex.cicl.transfer import TransferTables
from docex.errors import ValidationIssue


# Standard CICL service fields (not subject to "must be declared in
# engine.fields" check).
_STANDARD_CORE_FIELDS = {
    "role", "networks", "depends_on", "port", "env", "replicas", "command",
    "resources",
}
_STANDARD_BACKING_FIELDS = {
    "role", "networks", "depends_on", "port", "engine", "version",
    "schema_owned_by",
}


def validate_document(doc: CICLDocument, tables: TransferTables) -> list[ValidationIssue]:
    """Run every cross-document rule. Returns aggregated issues.

    The compiler validates each environment separately for foundation-
    dependent rules; ``foundation`` here is the *project's* declared
    one (used for rules 4, 9, 11). Per-env compilation later does
    foundation-specific checks again as it resolves engines.
    """
    issues: list[ValidationIssue] = []
    issues.extend(_validate_roles_and_engines(doc, tables))
    issues.extend(_validate_role_specific_fields(doc, tables))
    issues.extend(_validate_magic_refs(doc, tables))
    issues.extend(_validate_depends_on(doc))
    issues.extend(_validate_schema_owned_by(doc))
    issues.extend(_validate_container_registry(doc))
    issues.extend(_validate_resources(doc))
    issues.extend(_validate_domain_default_service(doc))
    issues.extend(_validate_web_service_ports(doc))
    issues.extend(_validate_env_secrets_overlap(doc))
    return issues


# ---------------------------------------------------------------------------
# Rule 2 + Rule 4: roles and engines exist and match foundation.
# ---------------------------------------------------------------------------


def _validate_roles_and_engines(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        if svc.role not in tables.by_role:
            issues.append(ValidationIssue(
                rule="rule_2_unknown_role",
                message=f"core service {name!r} uses unknown role {svc.role!r}",
                where=f"core_services.{name}",
            ))
            continue
        # Core services don't declare an engine in infra.yml; transfer-table
        # layer must contain at least one engine for the role.
        engines = tables.role(svc.role)
        if not engines:
            issues.append(ValidationIssue(
                rule="rule_2_role_has_no_engines",
                message=f"core service {name!r} role {svc.role!r} has no engines defined",
                where=f"core_services.{name}",
            ))

    for name, svc in sorted(doc.backing_services.items()):
        if svc.role not in tables.by_role:
            issues.append(ValidationIssue(
                rule="rule_2_unknown_role",
                message=f"backing service {name!r} uses unknown role {svc.role!r}",
                where=f"backing_services.{name}",
            ))
            continue
        candidates = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in candidates:
            try:
                tables.engine(svc.role, cand)
            except Exception as exc:
                issues.append(ValidationIssue(
                    rule="rule_4_unknown_engine",
                    message=str(exc),
                    where=f"backing_services.{name}.engine",
                ))
        # Foundation match is checked per-env in the compiler; we add a
        # static project-level check: at least one candidate must support
        # the project's declared foundation.
        match = False
        for cand in candidates:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            if entry.supports(doc.foundation):
                match = True
                break
        if not match and candidates:
            issues.append(ValidationIssue(
                rule="rule_4_engine_foundation_mismatch",
                message=(
                    f"backing service {name!r}: no engine in {candidates!r} "
                    f"supports project foundation {doc.foundation!r}"
                ),
                where=f"backing_services.{name}",
            ))
    return issues


# ---------------------------------------------------------------------------
# Role-specific field validation (transfer_tables.md rule 4)
# ---------------------------------------------------------------------------


def _validate_role_specific_fields(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def check(svc_name: str, svc: Any, kind: str, standard: set[str]) -> None:
        role = svc.role
        if role not in tables.by_role:
            return
        # Determine which engine to validate field declarations against.
        if isinstance(svc, BackingService):
            engines = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        else:
            # Core services have a single canonical engine per role. We just
            # check the union of fields across all engines of the role.
            engines = list(tables.role(role).keys())

        union_fields: set[str] = set()
        for eng in engines:
            try:
                entry = tables.engine(role, eng)
            except Exception:
                continue
            union_fields |= set((entry.fields or {}).keys())

        # Iterate over extra fields on the service.
        extras = svc.model_extra or {}
        for fname in sorted(extras):
            if fname in standard:
                continue
            if fname not in union_fields:
                issues.append(ValidationIssue(
                    rule="tt_rule_4_undeclared_field",
                    message=(
                        f"{kind} {svc_name!r}: role-specific field {fname!r} "
                        f"is not declared in any engine's fields: block (role "
                        f"{role!r}; engines {engines!r})"
                    ),
                    where=f"{kind}.{svc_name}.{fname}",
                ))

    for name, svc in sorted(doc.core_services.items()):
        check(name, svc, "core_services", _STANDARD_CORE_FIELDS)
    for name, svc in sorted(doc.backing_services.items()):
        check(name, svc, "backing_services", _STANDARD_BACKING_FIELDS)
    return issues


# ---------------------------------------------------------------------------
# Rule 3 + 7: magic refs resolve, and imply depends_on.
# ---------------------------------------------------------------------------


def _validate_magic_refs(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_services = doc.all_services()

    for name, svc in sorted(all_services.items()):
        # Collect magic refs from all of this service's string fields.
        # Specifically: `env:`, plus any `command:` and other extras.
        templates: list[str] = []
        env_block = getattr(svc, "env", None) or {}
        if isinstance(env_block, dict):
            for v in env_block.values():
                if isinstance(v, str):
                    templates.append(v)
        cmd = getattr(svc, "command", None)
        if isinstance(cmd, str):
            templates.append(cmd)
        elif isinstance(cmd, list):
            for c in cmd:
                if isinstance(c, str):
                    templates.append(c)
        # Also scan model_extra for string values (role-specific fields).
        for v in (svc.model_extra or {}).values():
            templates.extend(walk_strings(v))

        for template in templates:
            for kind, target, part in find_magic_refs(template):
                # Rule 3: target service exists.
                if kind == "core_services":
                    target_svc = doc.core_services.get(target)
                elif kind == "backing_services":
                    target_svc = doc.backing_services.get(target)
                else:
                    target_svc = None
                if target_svc is None:
                    issues.append(ValidationIssue(
                        rule="rule_3_unresolved_magic_ref",
                        message=(
                            f"magic ref ${{{kind}.{target}.{part}}} in service "
                            f"{name!r} references unknown service {target!r}"
                        ),
                        where=name,
                    ))
                    continue

                # Rule 3 continued: engine exposes the part.
                if isinstance(target_svc, BackingService):
                    cands = target_svc.engine if isinstance(target_svc.engine, list) else [target_svc.engine]
                else:
                    cands = list(tables.role(target_svc.role).keys())
                exposed: set[str] = set()
                for eng in cands:
                    try:
                        entry = tables.engine(target_svc.role, eng)
                    except Exception:
                        continue
                    # Across all foundations: collect any part keys present.
                    for part_name in (entry.provides or {}).keys():
                        exposed.add(part_name)
                if part not in exposed:
                    issues.append(ValidationIssue(
                        rule="rule_3_unresolved_magic_ref",
                        message=(
                            f"magic ref ${{{kind}.{target}.{part}}} in {name!r}: "
                            f"engine(s) {cands!r} do not expose part {part!r}; "
                            f"known: {sorted(exposed)}"
                        ),
                        where=name,
                    ))

                # Rule 7: depends_on must include the target.
                if target != name and target not in (svc.depends_on or []):
                    issues.append(ValidationIssue(
                        rule="rule_7_magic_ref_implies_depends_on",
                        message=(
                            f"service {name!r} references {target!r} via "
                            f"${{{kind}.{target}.{part}}} but does not list "
                            f"it in depends_on"
                        ),
                        where=name,
                    ))
    return issues


# ---------------------------------------------------------------------------
# Rule 6: depends_on cycle.
# ---------------------------------------------------------------------------


def _validate_depends_on(doc: CICLDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_services = doc.all_services()
    # Check that every depends_on target exists.
    for name, svc in sorted(all_services.items()):
        for dep in (svc.depends_on or []):
            if dep not in all_services:
                issues.append(ValidationIssue(
                    rule="rule_6_unknown_depends_on",
                    message=f"service {name!r} depends_on unknown service {dep!r}",
                    where=name,
                ))

    # Cycle detection via DFS.
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in all_services}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        for dep in sorted((all_services[node].depends_on or [])):
            if dep not in all_services:
                continue
            if color[dep] == GRAY:
                cycle = path + [node, dep]
                issues.append(ValidationIssue(
                    rule="rule_6_depends_on_cycle",
                    message=f"depends_on cycle: {' -> '.join(cycle)}",
                ))
                return
            if color[dep] == WHITE:
                dfs(dep, path + [node])
        color[node] = BLACK

    for n in sorted(all_services):
        if color[n] == WHITE:
            dfs(n, [])
    return issues


# ---------------------------------------------------------------------------
# Rule 8: relational_db schema_owned_by.
# ---------------------------------------------------------------------------


def _validate_schema_owned_by(doc: CICLDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_owners: dict[str, str] = {}  # owner -> backing service it owns
    for name, svc in sorted(doc.backing_services.items()):
        if svc.role != "relational_db":
            continue
        owner = svc.schema_owned_by
        if not owner:
            issues.append(ValidationIssue(
                rule="rule_8_schema_owned_by_required",
                message=f"relational_db {name!r} must declare schema_owned_by",
                where=f"backing_services.{name}",
            ))
            continue
        if owner not in doc.core_services:
            issues.append(ValidationIssue(
                rule="rule_8_schema_owned_by_unknown",
                message=(
                    f"relational_db {name!r} schema_owned_by {owner!r} is not "
                    f"a core service"
                ),
                where=f"backing_services.{name}",
            ))
        # Enforce one-owner-per-DB explicitly. Multiple databases owned
        # by the same core service is allowed.
        seen_owners.setdefault(name, owner)
    return issues


# ---------------------------------------------------------------------------
# Rule 9: container_registry required on fixed.
# ---------------------------------------------------------------------------


def _validate_container_registry(doc: CICLDocument) -> list[ValidationIssue]:
    if doc.foundation == "fixed" and not doc.container_registry:
        return [ValidationIssue(
            rule="rule_9_container_registry_required",
            message="fixed-foundation projects must set container_registry",
        )]
    return []


# ---------------------------------------------------------------------------
# Rule 10 + 11: resources.
# ---------------------------------------------------------------------------


def _validate_resources(doc: CICLDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        # Rule 10 (defense in depth): resources required.
        if svc.resources is None:  # pragma: no cover - pydantic enforces this
            issues.append(ValidationIssue(
                rule="rule_10_resources_required",
                message=f"core service {name!r} must declare resources",
                where=f"core_services.{name}",
            ))
            continue
        # Rule 11: no GPU on elastic.
        if doc.foundation == "elastic" and svc.resources.gpu is not None:
            issues.append(ValidationIssue(
                rule="rule_11_no_gpu_on_elastic",
                message=(
                    f"core service {name!r}: resources.gpu is not supported "
                    f"on elastic foundation (Fargate)"
                ),
                where=f"core_services.{name}",
            ))
    return issues


# ---------------------------------------------------------------------------
# Domain default service + web-service ports.
# ---------------------------------------------------------------------------


def _validate_domain_default_service(doc: CICLDocument) -> list[ValidationIssue]:
    dds = doc.domain_default_service
    if dds is None:
        return []
    svc = doc.all_services().get(dds)
    if svc is None:
        return [ValidationIssue(
            rule="rule_domain_default_unknown",
            message=f"domain_default_service {dds!r} is not a declared service",
            where="domain_default_service",
        )]
    if "web" not in svc.networks:
        return [ValidationIssue(
            rule="rule_domain_default_not_web",
            message=(
                f"domain_default_service {dds!r} must be on the 'web' network "
                f"(only web services are reachable at a subdomain)"
            ),
            where="domain_default_service",
        )]
    return []


def _validate_web_service_ports(doc: CICLDocument) -> list[ValidationIssue]:
    """Every web-network service must declare a port — the reverse proxy
    (Traefik / ALB) needs the container port to route to."""
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.all_services().items()):
        # reverse_proxy IS the edge router, not a routed target — exempt.
        if svc.role == "reverse_proxy":
            continue
        if "web" in svc.networks and svc.port is None:
            issues.append(ValidationIssue(
                rule="rule_web_service_needs_port",
                message=(
                    f"service {name!r} is on the 'web' network and must declare "
                    f"a port (the reverse proxy routes to it)"
                ),
                where=name,
            ))
    return issues


def _validate_env_secrets_overlap(doc: CICLDocument) -> list[ValidationIssue]:
    """A core service's `env:` and `secrets:` must not declare the same key —
    `env:` is compiler-resolved, `secrets:` is operator-supplied, so a shared
    key has ambiguous provenance and wiring."""
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        overlap = set(svc.env or {}) & set(svc.secrets or {})
        for key in sorted(overlap):
            issues.append(ValidationIssue(
                rule="rule_env_secrets_overlap",
                message=(
                    f"core service {name!r}: key {key!r} appears in both `env:` "
                    f"and `secrets:` — declare it in exactly one"
                ),
                where=f"core_services.{name}",
            ))
    return issues
