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

# Doctrine-injected env vars on every core service. A project may not
# declare these in its own env: or secrets: blocks — docex sets them
# at compile time. See transfer_tables.md § Per-core-service env
# (both foundations). Mods 011 (PROJECT_VERSION) + 017 (the OTEL_*
# quartet).
_RESERVED_CORE_ENV_KEYS = frozenset({
    "PROJECT_VERSION",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_RESOURCE_ATTRIBUTES",
})


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
    issues.extend(_validate_env_secrets_config_overlap(doc))
    issues.extend(_validate_reserved_engine_names(doc, tables))
    issues.extend(_validate_emits(doc, tables))
    issues.extend(_validate_reserved_env_keys(doc))
    issues.extend(_validate_source_key_disjointness(doc, tables))
    issues.extend(_validate_apex_domain_bare(doc))
    issues.extend(_validate_service_name_blacklist(doc))
    issues.extend(_validate_reverse_proxy_field(doc))
    issues.extend(_validate_reverse_proxy_role_removed(doc))
    issues.extend(_validate_scheduler_services(doc))
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


def _validate_env_secrets_config_overlap(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 16: a core service's `env:`, `secrets:`, and `config:` must not
    share a key. Each has distinct provenance/wiring (`env:` is
    compiler-resolved, `secrets:` is operator-supplied secret, `config:` is
    operator-supplied per-env config), so a shared key is ambiguous."""
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        blocks = {
            "env": set(svc.env or {}),
            "secrets": set(svc.secrets or {}),
            "config": set(getattr(svc, "config", {}) or {}),
        }
        for a, b in (("env", "secrets"), ("env", "config"), ("secrets", "config")):
            for key in sorted(blocks[a] & blocks[b]):
                issues.append(ValidationIssue(
                    rule="rule_env_secrets_config_overlap",
                    message=(
                        f"core service {name!r}: key {key!r} appears in both "
                        f"`{a}:` and `{b}:` — declare it in exactly one"
                    ),
                    where=f"core_services.{name}",
                ))
    return issues


def _engine_for_service(
    svc: Any, tables: TransferTables, foundation: str
) -> Any:
    """Resolve the engine entry that applies to ``svc`` under ``foundation``.

    Mirrors the precedence logic the compiler uses: for backing services,
    walk the ``engine:`` candidates and return the first that supports
    the foundation; for core services, walk all engines of the role and
    return the first that supports the foundation. Returns ``None`` if
    the role isn't known or nothing matches — callers skip in that case.
    """
    role = svc.role
    if role not in tables.by_role:
        return None
    if isinstance(svc, BackingService):
        candidates = svc.engine if isinstance(svc.engine, list) else [svc.engine]
    else:
        candidates = sorted(tables.role(role).keys())
    for cand in candidates:
        try:
            entry = tables.engine(role, cand)
        except Exception:
            continue
        if entry.supports(foundation):
            return entry
    return None


def _validate_emits(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    """Check every used engine declares `emits:` correctly, and that
    every `target:` reference resolves to a declared destination.

    See transfer_tables.md § Validation rules 11 + 12. Mod 010.
    """
    from docex.cicl.transfer import EMIT_DESTINATIONS

    issues: list[ValidationIssue] = []

    # Foundations the project may compile for: fixed always (dev/test);
    # elastic additionally if the project's foundation is elastic.
    project_foundations = ["fixed"]
    if doc.foundation == "elastic":
        project_foundations.append("elastic")

    seen_engines: set[tuple[str, str]] = set()
    for svc_name, svc in doc.all_services().items():
        engine = _engine_for_service(svc, tables, doc.foundation)
        if engine is None:
            continue
        key = (engine.role, engine.engine)
        if key not in seen_engines:
            seen_engines.add(key)

            # Rule 11: emits.<foundation> exists and is non-empty for every
            # foundation the engine + project supports. Destination names
            # are in the doctrine-recognized closed set.
            for fnd in project_foundations:
                if not engine.supports(fnd):
                    continue
                decls = (engine.emits or {}).get(fnd) or []
                if not decls:
                    issues.append(ValidationIssue(
                        rule="EMITS_MISSING",
                        message=(
                            f"engine {engine.engine!r} of role {engine.role!r} "
                            f"declares no `emits:` for foundation {fnd!r}. Every "
                            f"engine must declare at least one emit destination "
                            f"per supported foundation. See transfer_tables.md § "
                            f"Validation rule 11."
                        ),
                    ))
                    continue
                for dest in decls:
                    if dest not in EMIT_DESTINATIONS.get(fnd, frozenset()):
                        issues.append(ValidationIssue(
                            rule="EMITS_UNKNOWN_DESTINATION",
                            message=(
                                f"engine {engine.engine!r} of role "
                                f"{engine.role!r}: `emits.{fnd}` declares "
                                f"unknown destination {dest!r}. Known "
                                f"destinations for {fnd!r}: "
                                f"{sorted(EMIT_DESTINATIONS.get(fnd, []))}."
                            ),
                        ))

            # Rule 12: every field translation's `target:` (if set) names
            # a destination in the engine's `emits.<foundation>`.
            for field_name, per_field in (engine.fields or {}).items():
                if not isinstance(per_field, dict):
                    continue
                for fnd, translation in per_field.items():
                    if not isinstance(translation, dict):
                        continue
                    target = translation.get("target")
                    if target is None:
                        continue
                    declared = set((engine.emits or {}).get(fnd) or [])
                    if target not in declared:
                        issues.append(ValidationIssue(
                            rule="FIELD_TARGET_UNDECLARED",
                            message=(
                                f"engine {engine.engine!r} of role "
                                f"{engine.role!r}: field "
                                f"{field_name!r}.{fnd} declares "
                                f"target={target!r} but engine's "
                                f"emits.{fnd}={sorted(declared)!r} does not "
                                f"include it. See transfer_tables.md § "
                                f"Validation rule 12."
                            ),
                        ))

        # Rule 12 — conditional target check: `target: target_group`
        # requires the consuming service to be on the `web` network.
        # The translation is invalid for any service not on `web`.
        if "web" not in (svc.networks or []):
            for field_name, per_field in (engine.fields or {}).items():
                if not isinstance(per_field, dict):
                    continue
                # Check whether the project actually set this field on this
                # service. If not, the translation is dormant — no issue.
                if field_name not in (svc.model_extra or {}):
                    continue
                trans = per_field.get(doc.foundation)
                if not isinstance(trans, dict):
                    continue
                if trans.get("target") == "target_group":
                    issues.append(ValidationIssue(
                        rule="FIELD_TARGET_NOT_APPLICABLE",
                        message=(
                            f"service {svc_name!r} declares field "
                            f"{field_name!r} (routes to `target_group`) "
                            f"but is not on the `web` network. Add `web` "
                            f"to its `networks:` list or remove the "
                            f"field. See transfer_tables.md § Validation "
                            f"rule 12."
                        ),
                        where=svc_name,
                    ))

    return issues


def _validate_reserved_engine_names(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    """Reject backing-service names the engine reserves.

    The compiler derives identifiers like RDS's ``DBName`` (postgres) and
    the schema name from the service's name. AWS rejects names from
    each engine's reserved-keyword list at ``CreateDBInstance`` time,
    so a service named ``database`` (or ``user``, ``select``, …)
    compiles cleanly but blows up at ``tofu apply``. We catch the
    collision at compile time and tell the operator to rename.
    """
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.backing_services.items()):
        candidates = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        # Use the same per-foundation precedence the compiler will:
        # pick the first candidate the project's declared foundation
        # supports. (Per-env compilation resolves again — but the
        # service NAME doesn't vary per env, so checking once is
        # sufficient.)
        entry = None
        for cand in candidates:
            try:
                cand_entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            if cand_entry.supports(doc.foundation):
                entry = cand_entry
                break
        if entry is None or not entry.reserved_names:
            continue
        reserved = {r.lower() for r in entry.reserved_names}
        if name.lower() in reserved:
            issues.append(ValidationIssue(
                rule="rule_engine_reserved_name",
                message=(
                    f"backing service {name!r} (role {svc.role!r}, engine "
                    f"{entry.engine!r}) uses a reserved engine identifier. "
                    f"AWS RDS would reject this at apply time. Rename the "
                    f"service to something not on the engine's reserved list "
                    f"(e.g. {name}_db, or a project-scoped name)."
                ),
                where=f"backing_services.{name}",
            ))
    return issues


def _validate_reserved_env_keys(
    doc: CICLDocument,
) -> list[ValidationIssue]:
    """Doctrine-reserved env keys on core services. A project that
    declares one of these in its own env: or secrets: block is either
    duplicating doctrine or trying to lie about its identity — both
    are mistakes. Mods 011 + 017.
    """
    from docex.cicl.categories import DOCTRINE_INJECTED_SECRETS

    issues: list[ValidationIssue] = []
    for svc_name, svc in sorted(doc.core_services.items()):
        for source, block in (
            ("env", svc.env or {}),
            ("secrets", svc.secrets or {}),
            ("config", getattr(svc, "config", {}) or {}),
        ):
            block_keys = set(block)
            for key in sorted(block_keys & _RESERVED_CORE_ENV_KEYS):
                issues.append(ValidationIssue(
                    rule="rule_reserved_env_key",
                    message=(
                        f"core service {svc_name!r} declares "
                        f"{key!r} under `{source}:`. This name is "
                        f"doctrine-reserved: docex auto-injects it "
                        f"on every core service. Remove the "
                        f"declaration. See transfer_tables.md § "
                        f"Per-core-service env."
                    ),
                    where=f"core_services.{svc_name}.{source}",
                ))
            # Doctrine-injected secrets (e.g. TELEMETRY_API_KEY) are managed by
            # docex — a project must not declare
            # them in any block. This validator owns the diagnostic; the
            # disjointness check skips these keys to avoid double-reporting.
            for key in sorted(block_keys & DOCTRINE_INJECTED_SECRETS):
                issues.append(ValidationIssue(
                    rule="rule_doctrine_injected_key_reserved",
                    message=(
                        f"core service {svc_name!r} declares {key!r} under "
                        f"`{source}:`. This is a doctrine-injected secret "
                        f"managed by docex — it is surfaced by `docex secrets "
                        f"scaffold`/`status` and "
                        f"filled by the operator; a project must not declare "
                        f"it. Remove the declaration. See config_and_secrets.md "
                        f"§ Doctrine-Injected Secrets."
                    ),
                    where=f"core_services.{svc_name}.{source}",
                ))
    return issues


# ---------------------------------------------------------------------------
# Rule 20: cross-category source-key disjointness (Mod 079).
# ---------------------------------------------------------------------------


def _validate_source_key_disjointness(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    """Rule 20: the three value categories (TTE / secret / config) are disjoint
    project-wide by source key. A key claimed by two categories has ambiguous
    provenance, value, and read/write permission. Doctrine-injected keys are
    handled by the reserved-key check, so skip them here to avoid
    double-reporting."""
    from docex.cicl.categories import DOCTRINE_INJECTED_SECRETS, classify_source_keys

    issues: list[ValidationIssue] = []
    cats = classify_source_keys(doc, tables)
    for key, categories in sorted(cats.conflicts().items()):
        if key in DOCTRINE_INJECTED_SECRETS:
            continue  # reserved-key check owns this diagnostic
        names = ", ".join(c.value for c in categories)
        issues.append(ValidationIssue(
            rule="rule_source_key_category_conflict",
            message=(
                f"source key {key!r} is claimed by multiple value categories "
                f"({names}) — the categories must be disjoint (a key's "
                f"provenance, value, and read/write permission would be "
                f"ambiguous). Declare it in exactly one. See "
                f"config_and_secrets.md § Collision rules."
            ),
        ))
    return issues


# ---------------------------------------------------------------------------
# Mod 031 — apex_domain bare check, service-name blacklist, reverse_proxy
# field foundation gate, reverse_proxy role removal.
# ---------------------------------------------------------------------------


# Service-name blacklist (cicl.md § Validation Rules rule 14). These tokens
# collide with the canonical domain anatomy `<service>.<env>.<project>.
# <apex_domain>` (`dev`/`test`/`stage`/`prod` are env labels, `www` is the
# near-universal subdomain convention preserved for ergonomic clarity).
_RESERVED_SERVICE_NAMES = frozenset({"dev", "test", "stage", "prod", "www"})


def _validate_apex_domain_bare(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 13: ``apex_domain`` must be a bare apex (e.g. ``example.com``
    or ``example.co.uk``); subdomain components are rejected. The project
    segment of the canonical service host is derived automatically from
    ``project.yml``'s ``name``.

    The 3-part form is only accepted when the middle label is a recognized
    second-level country-code domain (``co.uk``, ``com.au``, etc.) —
    otherwise the leading label is treated as a project subdomain and
    rejected.
    """
    value = doc.apex_domain
    if not value:
        return [ValidationIssue(
            rule="rule_13_apex_domain_required",
            message="apex_domain must be set",
            where="apex_domain",
        )]
    parts = value.split(".")
    # Known second-level domain labels used in ccTLD ladders. A 3-part
    # apex requires the middle label to be one of these — anything else is
    # presumed to be a project subdomain. The set is intentionally small;
    # it covers the cases the doctrine has examples for. Adding to it is
    # a doctrine change.
    _SLD_LABELS = frozenset({
        "co", "com", "org", "net", "gov", "ac", "edu",
    })
    valid = False
    if len(parts) == 2 and all(parts):
        # Two-part apex: domain + TLD.
        valid = True
    elif len(parts) == 3 and all(parts):
        # Three-part apex: only valid when middle is a known SLD.
        valid = parts[1].lower() in _SLD_LABELS
    if not valid:
        return [ValidationIssue(
            rule="rule_13_apex_domain_bare",
            message=(
                f"apex_domain must be a bare apex (e.g. 'example.com' or "
                f"'example.co.uk'), got {value!r}. Per cicl.md, the project "
                f"subdomain is derived automatically from project.yml's name."
            ),
            where="apex_domain",
        )]
    return []


def _validate_service_name_blacklist(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 14: service names cannot be ``dev``, ``test``, ``stage``,
    ``prod``, or ``www`` — they collide with the canonical domain anatomy."""
    issues: list[ValidationIssue] = []
    for name in sorted(doc.all_services()):
        if name in _RESERVED_SERVICE_NAMES:
            issues.append(ValidationIssue(
                rule="rule_14_service_name_blacklist",
                message=(
                    f"service name {name!r} is reserved (one of "
                    f"{sorted(_RESERVED_SERVICE_NAMES)}). Per cicl.md § "
                    f"Validation Rules rule 14, these collide with the "
                    f"canonical domain anatomy "
                    f"<service>.<env>.<project>.<apex_domain>."
                ),
                where=name,
            ))
    return issues


def _validate_reverse_proxy_field(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 18: ``reverse_proxy:`` is elastic-only. Fixed-foundation
    projects must not declare it. The Literal type already constrains the
    accepted values (``alb`` / ``ec2_traefik_eip`` / ``ec2_traefik_pip``)
    at parse time; this validator gates by foundation."""
    if doc.foundation == "fixed" and doc.reverse_proxy is not None:
        return [ValidationIssue(
            rule="rule_18_reverse_proxy_elastic_only",
            message=(
                f"reverse_proxy: {doc.reverse_proxy!r} is set, but the "
                f"project foundation is 'fixed'. The reverse_proxy field is "
                f"only valid on elastic-foundation projects (cicl.md § "
                f"Reverse Proxy)."
            ),
            where="reverse_proxy",
        )]
    return []


# ---------------------------------------------------------------------------
# Mod 055 — scheduler role field rules.
# ---------------------------------------------------------------------------


def _validate_scheduler_services(doc: CICLDocument) -> list[ValidationIssue]:
    """Mod 055: a ``scheduler`` core service must declare both ``schedule``
    and ``command``, and ``schedule`` must be a well-formed 5-field cron.

    ``schedule`` on a *non*-scheduler service is already rejected by
    rule 4 (``tt_rule_4_undeclared_field``) since only ``scheduler/
    container`` declares it as a role-specific field. Here we add the
    scheduler-side requirements and surface a malformed cron at compile
    time rather than at apply / job-run time.
    """
    from docex.cicl.cron import cron_validation_issue

    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        if svc.role != "scheduler":
            continue
        schedule = (svc.model_extra or {}).get("schedule")
        if not isinstance(schedule, str) or not schedule.strip():
            issues.append(ValidationIssue(
                rule="rule_scheduler_schedule_required",
                message=(
                    f"scheduler service {name!r} must declare a non-empty "
                    f"`schedule` (a 5-field cron expression)"
                ),
                where=f"core_services.{name}.schedule",
            ))
        else:
            issue = cron_validation_issue(
                schedule, where=f"core_services.{name}.schedule"
            )
            if issue is not None:
                issues.append(issue)
        cmd = svc.command
        if cmd is None or (isinstance(cmd, (str, list)) and not cmd):
            issues.append(ValidationIssue(
                rule="rule_scheduler_command_required",
                message=(
                    f"scheduler service {name!r} must declare a non-empty "
                    f"`command` (the job entrypoint — there is no sensible "
                    f"default)"
                ),
                where=f"core_services.{name}.command",
            ))
    return issues


def _validate_reverse_proxy_role_removed(
    doc: CICLDocument,
) -> list[ValidationIssue]:
    """Mod 031 removes the ``reverse_proxy`` role. A service declaring
    ``role: reverse_proxy`` in infra.yml previously parsed as a no-op
    marker; the role is now project-tier infra (see projinfra/) and
    must not appear in CICL."""
    issues: list[ValidationIssue] = []
    for kind, services in (
        ("core_services", doc.core_services),
        ("backing_services", doc.backing_services),
    ):
        for name, svc in sorted(services.items()):
            if svc.role == "reverse_proxy":
                issues.append(ValidationIssue(
                    rule="rule_reverse_proxy_role_removed",
                    message=(
                        f"{kind} {name!r} declares role 'reverse_proxy', "
                        f"which no longer exists. Per mod 031, the reverse "
                        f"proxy is project-tier infrastructure managed by "
                        f"the compiler (Traefik on fixed; ALB or EC2-Traefik "
                        f"on elastic via the top-level reverse_proxy: field)."
                    ),
                    where=f"{kind}.{name}",
                ))
    return issues
