"""Cross-document CICL validation.

The pydantic schema in ``model.py`` covers per-model field rules (rule 1,
rule 5, units, etc.). This module covers the rules that need the full
infra.yml plus the transfer tables and the foundation context:

    Rule 2: roles defined in tables.
    Rule 3: magic refs resolve.
    Rule 4: engines known + match foundation.
    Rule 6: no depends_on cycles.
    Rule 7: magic-ref-implied edges — `depends_on` for a backing target,
            `consumes` for a core process type.
    Rule 8: relational_db has valid schema_owned_by.
    Rule 9: container_registry set on fixed foundation.
    Rule 10: every core service has cpu+memory (covered by pydantic;
             re-checked here as defense-in-depth).
    Rule 11: resources.gpu not declared under elastic foundation.
    Rule 25: `consumes` names core process types, fully qualified as
             `<service>.<process>`, and never itself.

Field validation (rule 4 in transfer_tables.md: every role-specific
field on a service is declared in the engine's ``fields:`` block) is
also performed here.

All issues are aggregated into a list rather than raised one-at-a-time
so the developer can fix multiple problems per compile cycle.
"""

from __future__ import annotations

from typing import Any

from docex.cicl.magic_refs import (
    MagicRefArityError,
    find_magic_refs,
    self_consumes_message,
    self_reference_message,
    walk_strings,
)
from docex.cicl.model import (
    BackingService,
    CICLDocument,
    CoreService,
    ProcessRef,
    ProcessType,
)
from docex.cicl.transfer import TransferTables
from docex.errors import ValidationIssue


# Standard CICL service fields (not subject to "must be declared in
# engine.fields" check).
# Service level is model-enforced (CoreService.extra="forbid"); listed for
# documentation only.
_STANDARD_SERVICE_FIELDS = {"processes", "secrets", "config", "env"}
# Process level: everything ProcessType declares as a real field. Anything
# else must be declared in the engine's `fields:` block (tt rule 4).
_STANDARD_PROCESS_FIELDS = {
    "role", "command", "networks", "depends_on", "consumes", "port", "env",
    "resources", "replicas",
}
_STANDARD_BACKING_FIELDS = {
    "role", "networks", "depends_on", "port", "engine", "version",
    "schema_owned_by",
}


def _process_where(svc_name: str, proc_name: str) -> str:
    """The canonical ``where=`` path of one core process type."""
    return f"core_services.{svc_name}.processes.{proc_name}"


def _effective_env(svc: CoreService, proc: ProcessType) -> dict[str, Any]:
    """A process type's effective env: the codebase-scoped service-level
    ``env:`` block with the process-level ``env:`` merged over it
    (cicl.md § Field scoping)."""
    out: dict[str, Any] = dict(svc.env or {})
    out.update(proc.env or {})
    return out

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
    issues.extend(_validate_consumes(doc))
    issues.extend(_validate_schema_owned_by(doc))
    issues.extend(_validate_container_registry(doc))
    issues.extend(_validate_resources(doc))
    issues.extend(_validate_rendered_identity(doc))
    issues.extend(_validate_domain_default_process(doc))
    issues.extend(_validate_web_service_ports(doc))
    issues.extend(_validate_process_role_rules(doc))
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
    issues.extend(_validate_health_check_path_port(doc))
    return issues


# ---------------------------------------------------------------------------
# Rule 2 + Rule 4: roles and engines exist and match foundation.
# ---------------------------------------------------------------------------


def _validate_roles_and_engines(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # `role` is per-process type in CICL v2, so role/engine resolution is too.
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        where = _process_where(svc_name, proc_name)
        label = ProcessRef(svc_name, proc_name).dotted
        if proc.role not in tables.by_role:
            issues.append(ValidationIssue(
                rule="rule_2_unknown_role",
                message=(
                    f"core process type {label!r} uses unknown role "
                    f"{proc.role!r}"
                ),
                where=where,
            ))
            continue
        # Core services don't declare an engine in infra.yml; transfer-table
        # layer must contain at least one engine for the role.
        engines = tables.role(proc.role)
        if not engines:
            issues.append(ValidationIssue(
                rule="rule_2_role_has_no_engines",
                message=(
                    f"core process type {label!r} role {proc.role!r} has no "
                    f"engines defined"
                ),
                where=where,
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

    def check(
        label: str, svc: Any, kind: str, standard: set[str], where_base: str
    ) -> None:
        role = svc.role
        if role not in tables.by_role:
            return
        # Determine which engine to validate field declarations against.
        if isinstance(svc, BackingService):
            engines = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        else:
            # Core process types have a single canonical engine per role. We
            # just check the union of fields across all engines of the role.
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
                        f"{kind} {label!r}: role-specific field {fname!r} "
                        f"is not declared in any engine's fields: block (role "
                        f"{role!r}; engines {engines!r})"
                    ),
                    where=f"{where_base}.{fname}",
                ))

    # The service level needs no walk — CoreService forbids extras outright,
    # so a stray service-level field is a parse error, not an issue here.
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        check(
            ProcessRef(svc_name, proc_name).dotted, proc, "core_services",
            _STANDARD_PROCESS_FIELDS, _process_where(svc_name, proc_name),
        )
    for name, svc in sorted(doc.backing_services.items()):
        check(
            name, svc, "backing_services", _STANDARD_BACKING_FIELDS,
            f"backing_services.{name}",
        )
    return issues


# ---------------------------------------------------------------------------
# Rule 3 + 7: magic refs resolve, and imply depends_on.
# ---------------------------------------------------------------------------


def _validate_magic_refs(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def scan(
        label: str, where_label: str, own_ref: tuple[str, str] | None,
        templates: list[str], depends_on: list[str],
        consumes: set[str] | None,
    ) -> None:
        """Rule 3 + rule 7 over one referencer's templates.

        Rule 7 is kind-aware: ``depends_on`` answers it for a backing target,
        ``consumes`` answers it for a core process type. ``consumes=None``
        means the referencer is a *backing service*, which cannot answer it at
        all — see the core branch below for why that is rule 7 correctly not
        applying rather than a hole in it.
        """
        for template in templates:
            for match in find_magic_refs(template):
                try:
                    ref = match.parse()
                except MagicRefArityError as exc:
                    issues.append(ValidationIssue(
                        rule="rule_3_magic_ref_arity",
                        message=f"{exc} (referenced by {label!r})",
                        where=where_label,
                    ))
                    continue

                # --- core target -------------------------------------------
                if ref.kind == "core_services":
                    if own_ref is not None and (ref.target, ref.process) == own_ref:
                        issues.append(ValidationIssue(
                            rule="rule_3_self_magic_ref",
                            message=self_reference_message(ref, label),
                            where=where_label,
                        ))
                        continue
                    target_core = doc.core_services.get(ref.target)
                    if target_core is None:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r} references "
                                f"unknown core service {ref.target!r}"
                            ),
                            where=where_label,
                        ))
                        continue
                    target_proc = target_core.processes.get(ref.process)
                    if target_proc is None:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r}: core "
                                f"service {ref.target!r} declares no process "
                                f"type {ref.process!r}; known: "
                                f"{sorted(target_core.processes)}"
                            ),
                            where=where_label,
                        ))
                        continue
                    # The part must be exposed by an engine of the target
                    # process's role. Collected across foundations, exactly as
                    # the backing branch does — validate_document has no
                    # foundation.
                    core_exposed: set[str] = set()
                    try:
                        role_engines = tables.role(target_proc.role)
                    except Exception:
                        role_engines = {}
                    for entry in role_engines.values():
                        for part_name in (entry.provides or {}).keys():
                            core_exposed.add(part_name)
                    if ref.part not in core_exposed:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r}: role "
                                f"{target_proc.role!r} does not expose part "
                                f"{ref.part!r}; known: {sorted(core_exposed)}"
                            ),
                            where=where_label,
                        ))
                    # Rule 7, core half. ONE-DIRECTIONAL by construction: the
                    # walk is over refs, looking each up in the consumes set.
                    # There is no walk in the other direction and none may be
                    # added — `api.web` declares `consumes: [api.worker]` for
                    # the contract and the health fan-out while holding no ref
                    # to the worker, because it reaches it through the broker.
                    # A bidirectional rule would reject the most common
                    # web/worker topology in existence.
                    if consumes is None:
                        # A backing service holds this ref. Rule 7 is worded
                        # "on the referencing PROCESS TYPE"; a backing service
                        # has no `consumes:` and (rule 24) may not depends_on a
                        # core service, so there is nothing it could declare.
                        # WHY skipped rather than rejected: the ref can be
                        # perfectly legitimate — an object_store CORS origin set
                        # to ${core_services.api.web.host} — and it is not a
                        # CALL. Embedding a hostname in your own config implies
                        # no readiness coupling and crosses no interface
                        # boundary, so there is nothing for either relation to
                        # express. This is rule 7 correctly not applying, not a
                        # hole in it. Pinned by
                        # test_consumes_relation.py::test_backing_referencer_*.
                        continue
                    dotted = ProcessRef(ref.target, ref.process).dotted
                    if dotted not in consumes:
                        msg = (
                            f"process type {label!r} references {dotted!r} via "
                            f"{ref.text} but does not list it in consumes"
                        )
                        if own_ref is not None and ref.target == own_ref[0]:
                            # SAME-CODEBASE IS NOT EXEMPT. The check compares
                            # dotted targets and never compares codebases; this
                            # clause exists because it is the case an author
                            # will argue with.
                            msg += (
                                "; same-codebase is not exempt — sharing source "
                                "does not make it not a boundary"
                            )
                        issues.append(ValidationIssue(
                            rule="rule_7_magic_ref_implies_consumes",
                            message=(
                                msg + ". See cicl.md § Consumes Relationships."
                            ),
                            where=where_label,
                        ))
                    continue

                # --- backing target ----------------------------------------
                # Rule 3: target service exists.
                target_svc = doc.backing_services.get(ref.target)
                if target_svc is None:
                    issues.append(ValidationIssue(
                        rule="rule_3_unresolved_magic_ref",
                        message=(
                            f"magic ref {ref.text} in service "
                            f"{label!r} references unknown service {ref.target!r}"
                        ),
                        where=where_label,
                    ))
                    continue

                # Rule 3 continued: engine exposes the part.
                cands = (
                    target_svc.engine if isinstance(target_svc.engine, list)
                    else [target_svc.engine]
                )
                exposed: set[str] = set()
                for eng in cands:
                    try:
                        entry = tables.engine(target_svc.role, eng)
                    except Exception:
                        continue
                    # Across all foundations: collect any part keys present.
                    for part_name in (entry.provides or {}).keys():
                        exposed.add(part_name)
                if ref.part not in exposed:
                    issues.append(ValidationIssue(
                        rule="rule_3_unresolved_magic_ref",
                        message=(
                            f"magic ref {ref.text} in {label!r}: "
                            f"engine(s) {cands!r} do not expose part "
                            f"{ref.part!r}; known: {sorted(exposed)}"
                        ),
                        where=where_label,
                    ))

                # Rule 7: depends_on must include the target. The self-case
                # only ever meant anything for a backing consumer, whose
                # `label` IS its own name.
                if ref.target != label and ref.target not in (depends_on or []):
                    issues.append(ValidationIssue(
                        rule="rule_7_magic_ref_implies_depends_on",
                        message=(
                            f"service {label!r} references {ref.target!r} via "
                            f"{ref.text} but does not list "
                            f"it in depends_on"
                        ),
                        where=where_label,
                    ))

    # Core: one scan per process type, over its EFFECTIVE env (service-level
    # merged under process-level). A service-level `env:` ref therefore
    # obliges EVERY process type of that codebase to carry the edge ITS KIND
    # CALLS FOR — `depends_on` for a backing target, `consumes` for a core
    # one — cicl.md § Consumes Relationships § Three clarifications.
    for svc_name, proc_name, svc, proc in doc.all_processes():
        templates: list[str] = []
        for v in _effective_env(svc, proc).values():
            if isinstance(v, str):
                templates.append(v)
        cmd = proc.command
        if isinstance(cmd, str):
            templates.append(cmd)
        elif isinstance(cmd, list):
            for c in cmd:
                if isinstance(c, str):
                    templates.append(c)
        for v in (proc.model_extra or {}).values():
            templates.extend(walk_strings(v))
        scan(
            ProcessRef(svc_name, proc_name).dotted,
            _process_where(svc_name, proc_name),
            (svc_name, proc_name),
            templates,
            list(proc.depends_on or []),
            proc.consumes_refs(),
        )

    for name, svc in sorted(doc.backing_services.items()):
        templates = []
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
        for v in (svc.model_extra or {}).values():
            templates.extend(walk_strings(v))
        # `consumes=None`: a backing service has no such field and cannot
        # answer rule 7 for a core target. Reasoning at the core branch's
        # `if consumes is None` above.
        scan(name, name, None, templates, list(svc.depends_on or []), None)

    return issues


# ---------------------------------------------------------------------------
# Rule 6: depends_on cycle.
# ---------------------------------------------------------------------------


def _validate_depends_on(doc: CICLDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_services = doc.all_services()

    def check_edges(label: str, where: str, deps: list[str]) -> None:
        for dep in deps or []:
            if dep not in all_services:
                issues.append(ValidationIssue(
                    rule="rule_6_unknown_depends_on",
                    message=f"service {label!r} depends_on unknown service {dep!r}",
                    where=where,
                ))
            elif dep in doc.core_services:
                # Rule 24 (Mod 096).
                issues.append(ValidationIssue(
                    rule="rule_24_depends_on_core_service",
                    message=(
                        f"{label!r} declares depends_on: [{dep!r}], "
                        f"which is a core service. `depends_on` is a readiness gate and "
                        f"names backing services ONLY. Interface coupling between core "
                        f"process types is a different relation with different rules and "
                        f"lives in `consumes:`. "
                        f"See cicl.md § Depends-On Relationships."
                    ),
                    where=f"{where}.depends_on",
                ))

    for svc_name, proc_name, _svc, proc in doc.all_processes():
        check_edges(
            f"core process type {ProcessRef(svc_name, proc_name).dotted}",
            _process_where(svc_name, proc_name),
            list(proc.depends_on or []),
        )
    for name, svc in sorted(doc.backing_services.items()):
        check_edges(name, name, list(svc.depends_on or []))

    # Cycle detection (rule 6) over the BACKING-service graph only. With
    # rule 24 in force a core process type can only point at a backing
    # service, so core process types are leaves and cannot participate in
    # a cycle.
    backing = doc.backing_services
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in backing}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        for dep in sorted((backing[node].depends_on or [])):
            if dep not in backing:
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

    for n in sorted(backing):
        if color[n] == WHITE:
            dfs(n, [])
    return issues


# ---------------------------------------------------------------------------
# Rule 25: `consumes` names core process types, fully qualified, not itself.
# ---------------------------------------------------------------------------


def _validate_consumes(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 25. `ProcessRef.parse` is the parser — Mod 096 already wrote the
    bare-name-is-illegal rule and its reasoning into it, and a second parser
    would be a second place for that rule to drift."""
    issues: list[ValidationIssue] = []
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        label = ProcessRef(svc_name, proc_name).dotted
        where = f"{_process_where(svc_name, proc_name)}.consumes"

        def backing_message(entry: str, label: str = label) -> str:
            return (
                f"process type {label!r} lists {entry!r} in `consumes:`, which "
                f"names the backing service {entry.split('.')[0]!r}. `consumes` "
                f"is an interface edge between core process types; readiness "
                f"coupling to a backing service lives in `depends_on:`. "
                f"See cicl.md § Depends-On Relationships."
            )

        for raw in (proc.consumes or []):
            # WHY the namespace is consulted before the parser: `consumes:
            # [appdb]` is the mistake this field invites — an author reaching
            # for the relation they know — and "a codebase has no single
            # boundary" is the wrong answer to it.
            if "." not in raw and raw in doc.backing_services:
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_malformed",
                    message=backing_message(raw), where=where,
                ))
                continue
            try:
                ref = ProcessRef.parse(raw)
            except ValueError as exc:
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_malformed",
                    message=(
                        f"process type {label!r}: invalid `consumes:` entry — "
                        f"{exc} Rule 25 requires the same fully-qualified form "
                        f"(cicl.md § Consumes Relationships)."
                    ),
                    where=where,
                ))
                continue
            # Before the existence check: an author who consumes themselves
            # should get the self message, not a redundant pair.
            if (ref.service, ref.process) == (svc_name, proc_name):
                issues.append(ValidationIssue(
                    rule="rule_25_self_consumes",
                    message=self_consumes_message(ref), where=where,
                ))
                continue
            target = doc.core_services.get(ref.service)
            if target is None:
                message = (
                    backing_message(raw) if ref.service in doc.backing_services
                    else (
                        f"process type {label!r} lists {raw!r} in `consumes:`, "
                        f"but no core service {ref.service!r} is declared; "
                        f"known: {sorted(doc.core_services)}"
                    )
                )
                issues.append(ValidationIssue(
                    rule="rule_25_unresolved_consumes",
                    message=message, where=where,
                ))
                continue
            if ref.process not in target.processes:
                issues.append(ValidationIssue(
                    rule="rule_25_unresolved_consumes",
                    message=(
                        f"process type {label!r} lists {raw!r} in `consumes:`, "
                        f"but core service {ref.service!r} declares no process "
                        f"type {ref.process!r}; known: "
                        f"{sorted(target.processes)}"
                    ),
                    where=where,
                ))
                continue
            if target.processes[ref.process].role == "scheduler":
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_scheduler",
                    message=(
                        f"process type {label!r} lists {raw!r} in `consumes:`, but "
                        f"{raw!r} is a `scheduler` process type. Cron invokes a "
                        f"scheduler and nobody else does, so it exposes no boundary "
                        f"to consume — and it is exempt from the health fan-out that "
                        f"`consumes` drives. See cicl.md rule 25 and "
                        f"contracts.md § Health Checks."
                    ),
                    where=where,
                ))
                continue
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
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        where = _process_where(svc_name, proc_name)
        label = ProcessRef(svc_name, proc_name).dotted
        # Rule 10 (defense in depth): resources required.
        if proc.resources is None:  # pragma: no cover - pydantic enforces this
            issues.append(ValidationIssue(
                rule="rule_10_resources_required",
                message=f"core process type {label!r} must declare resources",
                where=where,
            ))
            continue
        # Rule 11: no GPU on elastic.
        if doc.foundation == "elastic" and proc.resources.gpu is not None:
            issues.append(ValidationIssue(
                rule="rule_11_no_gpu_on_elastic",
                message=(
                    f"core process type {label!r}: resources.gpu is not "
                    f"supported on elastic foundation (Fargate)"
                ),
                where=where,
            ))
    return issues


# ---------------------------------------------------------------------------
# Rule 5: rendered data-plane identity uniqueness (Mod 096).
# ---------------------------------------------------------------------------


def _normalized_identity(raw: str) -> str:
    # Every naming policy that reaches a service global_name (ecs, rds, s3)
    # is hyphen-separated and two of the three lowercase, so hyphenate-and-
    # lowercase is the conservative (most-collision-detecting) normalization.
    # The {project}_{env} prefix is common to every service, so comparing the
    # suffix alone is necessary and sufficient — which is what lets this run
    # without a project name or env.
    return raw.replace("_", "-").lower()


def _validate_rendered_identity(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 5: two emitted services may not render to the same data-plane
    identity after naming-policy normalization.

    Extends (does not replace) ``model.py::_validate_service_names``, whose
    exact-duplicate and core/backing-overlap checks are structural and
    per-document. This one catches the collisions process expansion makes
    possible: ``api`` + ``web-v2`` vs ``api-web`` + ``v2``; core ``api`` +
    ``db`` vs a backing service named ``api-db``; ``my_api`` + ``web`` vs
    ``my`` + ``api_web``.

    Mod 099 widened the domain a second time, to the derivatives the
    *compiler* appends — ``-otelcol`` (collector sidecar), ``-scheduler``
    (Ofelia trigger), ``-exec`` (per-codebase operations container) and
    ``-migrate`` (migration task definition). They render into the same
    namespace as the services the author wrote, so a process type named
    ``exec`` on codebase ``api`` produces ``api-exec``, byte-identical to
    ``api``'s exec container — one compose key, one silently clobbering the
    other. Three of the four holes predate Mod 099; the rule is keyed on
    COLLISION rather than on a reserved-name list precisely so it covers
    every suffix the compiler learns in future with no further edit.

    Mod 100 added the fifth such derivative — the ``-1``…``-N`` replica index
    the fixed-prod compose unroll appends — seeded only where the process type
    declares ``replicas > 1``. See the comment at its seeding site.
    """
    buckets: dict[str, list[str]] = {}
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        ref = ProcessRef(svc_name, proc_name)
        buckets.setdefault(_normalized_identity(ref.compiled), []).append(
            f"core process type {ref.dotted!r}"
        )
        # Compiler-emitted, per process type. A scheduler has no long-running
        # container to pair a collector with; it gets an Ofelia trigger
        # instead. Exactly one of the two suffixes exists per process type.
        if proc.role == "scheduler":
            buckets.setdefault(
                _normalized_identity(f"{ref.compiled}-scheduler"), []
            ).append(f"the scheduler trigger for core process type {ref.dotted!r}")
        else:
            buckets.setdefault(
                _normalized_identity(f"{ref.compiled}-otelcol"), []
            ).append(f"the collector sidecar for core process type {ref.dotted!r}")
        # Mod 100: the replica index. On fixed-prod the compiler unrolls a
        # process type with `replicas: N` into N compose services keyed
        # `{compiled}-{i}`, so `api` with process types `web` (replicas: 3)
        # and `web-1` renders `api-web-1` twice — one container silently
        # clobbering the other, in prod-fixed only, which is the worst place
        # to discover it.
        #
        # Gated on `replicas > 1` because with a count of 1 the suffix is
        # never emitted by anything, and rule 5 does not forbid a name that
        # collides with nothing. Unlike `-migrate` (seeded unconditionally
        # because whether it exists depends on a DIFFERENT service's
        # `schema_owned_by` — action at a distance), bumping `replicas` is an
        # edit on this very process type, so the error surfaces in the
        # reader's hand at the moment they create the collision.
        #
        # Seeding the container identity alone is sufficient: a sidecar
        # collision needs `{P}-otelcol == {Q}-{i}-otelcol`, i.e. `P == Q-i`,
        # which is exactly the container-level collision seeded here. Do not
        # "complete" this by also seeding `{compiled}-{i}-otelcol`.
        if proc.replicas > 1:
            for i in range(1, proc.replicas + 1):
                buckets.setdefault(
                    _normalized_identity(f"{ref.compiled}-{i}"), []
                ).append(
                    f"replica {i} of core process type {ref.dotted!r}"
                )
    for name in sorted(doc.backing_services):
        buckets.setdefault(_normalized_identity(name), []).append(
            f"backing service {name!r}"
        )
    # Compiler-emitted, per codebase. Unconditional: `-migrate` is seeded even
    # for a codebase that owns no schema today, because whether it owns one is
    # a property of a *backing* service's `schema_owned_by` and can be added
    # later without touching the codebase — a name that would collide the
    # moment it is should not be legal in the meantime.
    for codebase in sorted(doc.core_services):
        buckets.setdefault(
            _normalized_identity(f"{codebase}-exec"), []
        ).append(f"the exec container for codebase {codebase!r}")
        buckets.setdefault(
            _normalized_identity(f"{codebase}-migrate"), []
        ).append(f"the migration task definition for codebase {codebase!r}")

    issues: list[ValidationIssue] = []
    for rendered, members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        issues.append(ValidationIssue(
            rule="rule_5_rendered_identity_collision",
            message=(
                f"{' and '.join(sorted(members))} both render into the same "
                f"data-plane identity {rendered!r}. Every emitted service "
                f"shares the {{project}}_{{env}} prefix, so the suffix must be "
                f"unique across core process types, backing services, and the "
                f"derivatives the compiler appends to them (-otelcol, "
                f"-scheduler, -exec, -migrate, and the -1..-N replica index) "
                f"after naming-policy normalization (hyphenate + lowercase). "
                f"Rename one of them. "
                f"See cicl.md § Validation Rules rule 5."
            ),
        ))
    return issues


# ---------------------------------------------------------------------------
# Domain default process + web-process ports.
# ---------------------------------------------------------------------------


def _validate_domain_default_process(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 12: ``domain_default_process`` names a web-network *process
    type*, dotted (``api.web``)."""
    ddp = doc.domain_default_process
    if ddp is None:
        return []
    try:
        ref = ProcessRef.parse(ddp)
    except ValueError as exc:
        return [ValidationIssue(
            rule="rule_domain_default_malformed",
            message=f"domain_default_process {ddp!r}: {exc}",
            where="domain_default_process",
        )]
    svc = doc.core_services.get(ref.service)
    if svc is None:
        return [ValidationIssue(
            rule="rule_domain_default_unknown",
            message=(
                f"domain_default_process {ddp!r} names core service "
                f"{ref.service!r}, which is not declared"
            ),
            where="domain_default_process",
        )]
    proc = svc.processes.get(ref.process)
    if proc is None:
        return [ValidationIssue(
            rule="rule_domain_default_unknown",
            message=(
                f"domain_default_process {ddp!r}: core service "
                f"{ref.service!r} declares no process type {ref.process!r} "
                f"(known: {sorted(svc.processes)})"
            ),
            where="domain_default_process",
        )]
    if "web" not in proc.networks:
        return [ValidationIssue(
            rule="rule_domain_default_not_web",
            message=(
                f"domain_default_process {ddp!r} must be on the 'web' network "
                f"(only web process types are reachable at a subdomain)"
            ),
            where="domain_default_process",
        )]
    return []


def _validate_web_service_ports(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 15: every web-network process type / backing service must declare
    a port — the reverse proxy (Traefik / ALB) needs the container port to
    route to."""
    issues: list[ValidationIssue] = []
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        if "web" in proc.networks and proc.port is None:
            issues.append(ValidationIssue(
                rule="rule_web_service_needs_port",
                message=(
                    f"core process type "
                    f"{ProcessRef(svc_name, proc_name).dotted!r} is on the "
                    f"'web' network and must declare a port (the reverse "
                    f"proxy routes to it)"
                ),
                where=_process_where(svc_name, proc_name),
            ))
    for name, svc in sorted(doc.backing_services.items()):
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
    """Rule 16: a core service's effective `env:` (service ∪ process),
    `secrets:`, and `config:` must not share a key. Each has distinct
    provenance/wiring (`env:` is compiler-resolved, `secrets:` is
    operator-supplied secret, `config:` is operator-supplied per-env config),
    so a shared key is ambiguous."""
    issues: list[ValidationIssue] = []
    # `secrets:` and `config:` are both service-level, so their overlap is a
    # service-level fact — reported once, not once per process type.
    for name, svc in sorted(doc.core_services.items()):
        for key in sorted(set(svc.secrets or {}) & set(svc.config or {})):
            issues.append(ValidationIssue(
                rule="rule_env_secrets_config_overlap",
                message=(
                    f"core service {name!r}: key {key!r} appears in both "
                    f"`secrets:` and `config:` — declare it in exactly one"
                ),
                where=f"core_services.{name}",
            ))
    for svc_name, proc_name, svc, proc in doc.all_processes():
        env_keys = set(_effective_env(svc, proc))
        for other in ("secrets", "config"):
            for key in sorted(env_keys & set(getattr(svc, other) or {})):
                issues.append(ValidationIssue(
                    rule="rule_env_secrets_config_overlap",
                    message=(
                        f"core process type "
                        f"{ProcessRef(svc_name, proc_name).dotted!r}: key "
                        f"{key!r} appears in both `env:` and `{other}:` — "
                        f"declare it in exactly one"
                    ),
                    where=_process_where(svc_name, proc_name),
                ))
    return issues


def _engine_for_role(
    role: str, tables: TransferTables, foundation: str
) -> Any:
    """Resolve the engine entry a *core* role uses under ``foundation``.

    Mirrors the precedence logic the compiler uses: walk all engines of the
    role and return the first that supports the foundation. Returns ``None``
    if the role isn't known or nothing matches — callers skip in that case.
    """
    if role not in tables.by_role:
        return None
    for cand in sorted(tables.role(role).keys()):
        try:
            entry = tables.engine(role, cand)
        except Exception:
            continue
        if entry.supports(foundation):
            return entry
    return None


def _engine_for_service(
    svc: Any, tables: TransferTables, foundation: str
) -> Any:
    """Resolve the engine entry that applies to ``svc`` under ``foundation``.

    ``svc`` is a :class:`BackingService` (walk its ``engine:`` candidates)
    or a :class:`ProcessType` (delegate to :func:`_engine_for_role`).
    """
    if not isinstance(svc, BackingService):
        return _engine_for_role(svc.role, tables, foundation)
    role = svc.role
    if role not in tables.by_role:
        return None
    candidates = svc.engine if isinstance(svc.engine, list) else [svc.engine]
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

    # (label, where, model) over backing services plus core process types —
    # `role`, and therefore the engine, is per-process in CICL v2.
    targets: list[tuple[str, str, Any]] = [
        (name, name, svc) for name, svc in doc.backing_services.items()
    ]
    targets.extend(
        (
            ProcessRef(svc_name, proc_name).dotted,
            _process_where(svc_name, proc_name),
            proc,
        )
        for svc_name, proc_name, _svc, proc in doc.all_processes()
    )

    seen_engines: set[tuple[str, str]] = set()
    for svc_name, svc_where, svc in targets:
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
                        where=svc_where,
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
        # (source label, where suffix, key set). The service-level blocks are
        # reported once for the codebase; each process type's own `env:` is
        # reported against that process. Deduped by construction: a
        # service-level key is never re-reported per process.
        sources: list[tuple[str, str, set[str]]] = [
            ("env", f"core_services.{svc_name}.env", set(svc.env or {})),
            ("secrets", f"core_services.{svc_name}.secrets", set(svc.secrets or {})),
            ("config", f"core_services.{svc_name}.config", set(svc.config or {})),
        ]
        for proc_name in sorted(svc.processes):
            proc = svc.processes[proc_name]
            sources.append((
                "env",
                f"{_process_where(svc_name, proc_name)}.env",
                set(proc.env or {}),
            ))
        for source, where, block_keys in sources:
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
                    where=where,
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
                    where=where,
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
    """Rule 14: service *and process* names cannot be ``dev``, ``test``,
    ``stage``, ``prod``, or ``www`` — they collide with the canonical domain
    anatomy."""
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
    # A process name is the second segment of the emitted host label, so it
    # is bound by the same blacklist: `api` + a process named `prod` renders
    # `api-prod.dev.<project>.<apex>`, which reads as a production host
    # inside a dev environment.
    for svc_name, proc_name, _svc, _proc in doc.all_processes():
        if proc_name in _RESERVED_SERVICE_NAMES:
            issues.append(ValidationIssue(
                rule="rule_14_service_name_blacklist",
                message=(
                    f"process name {proc_name!r} (on core service "
                    f"{svc_name!r}) is reserved (one of "
                    f"{sorted(_RESERVED_SERVICE_NAMES)}). Per cicl.md § "
                    f"Validation Rules rule 14, these collide with the "
                    f"canonical domain anatomy "
                    f"<service>-<process>.<env>.<project>.<apex_domain>: a "
                    f"process named {proc_name!r} renders "
                    f"{svc_name}-{proc_name}.dev.<project>.<apex_domain>, "
                    f"which reads as a production host in a dev environment."
                ),
                where=_process_where(svc_name, proc_name),
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
    """Mod 055: a ``scheduler`` core process type must declare a
    well-formed 5-field cron ``schedule``.

    ``schedule`` on a *non*-scheduler process type is already rejected by
    rule 4 (``tt_rule_4_undeclared_field``) since only ``scheduler/
    container`` declares it as a role-specific field. Here we add the
    scheduler-side requirement and surface a malformed cron at compile
    time rather than at apply / job-run time.

    The command-required half is gone: ``ProcessType.command`` is required
    and non-empty on EVERY process type (rule 23), so the check would be
    unreachable.
    """
    from docex.cicl.cron import cron_validation_issue

    issues: list[ValidationIssue] = []
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        if proc.role != "scheduler":
            continue
        where = f"{_process_where(svc_name, proc_name)}.schedule"
        schedule = (proc.model_extra or {}).get("schedule")
        if not isinstance(schedule, str) or not schedule.strip():
            issues.append(ValidationIssue(
                rule="rule_scheduler_schedule_required",
                message=(
                    f"scheduler process type "
                    f"{ProcessRef(svc_name, proc_name).dotted!r} must declare "
                    f"a non-empty `schedule` (a 5-field cron expression)"
                ),
                where=where,
            ))
        else:
            issue = cron_validation_issue(schedule, where=where)
            if issue is not None:
                issues.append(issue)
    return issues


# ---------------------------------------------------------------------------
# Rules 26 + 27 (Mod 096) — fields and networks that a role forbids.
# ---------------------------------------------------------------------------


# Roles that never take public ingress. A process type wanting it *is* a web
# process type and should say so with `role: web`.
_NON_WEB_ROLES = frozenset({"worker", "scheduler"})


def _validate_process_role_rules(doc: CICLDocument) -> list[ValidationIssue]:
    """Rules 26 + 27 — fields and networks that a role forbids.

    Rule 26: `replicas` on a scheduler is a compile error. Ofelia fires one
    job; a replica count is meaningless. Consistent with how `schedule:` is
    rejected on every non-scheduler role — inert fields fail rather than being
    silently ignored.

    Rule 27: a `worker` or `scheduler` process type may not declare `web` in
    `networks`. A process type wanting public ingress *is* a web process type
    and should say so with `role: web`. Replaces the prose-only, unenforced
    note this file carried for scheduler.
    """
    issues: list[ValidationIssue] = []
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        where = _process_where(svc_name, proc_name)
        label = ProcessRef(svc_name, proc_name).dotted
        # Rule 26. `replicas` defaults to 1, so "declared" is the only
        # meaningful test — model_fields_set distinguishes it from the default.
        if proc.role == "scheduler" and "replicas" in proc.model_fields_set:
            issues.append(ValidationIssue(
                rule="rule_26_replicas_on_scheduler",
                message=(
                    f"scheduler process type {label!r} declares `replicas: "
                    f"{proc.replicas}`. A scheduler fires one job per tick, so "
                    f"a replica count is inert — remove it. See cicl.md § "
                    f"Validation Rules rule 26."
                ),
                where=f"{where}.replicas",
            ))
        # Rule 27.
        if proc.role in _NON_WEB_ROLES and "web" in (proc.networks or []):
            issues.append(ValidationIssue(
                rule="rule_27_web_network_on_non_web_role",
                message=(
                    f"{proc.role} process type {label!r} declares 'web' in "
                    f"`networks:`. The web network carries public ingress "
                    f"through the reverse proxy; a process type that wants it "
                    f"*is* a web process type and should declare `role: web`. "
                    f"See cicl.md § Validation Rules rule 27."
                ),
                where=f"{where}.networks",
            ))
    return issues


# ---------------------------------------------------------------------------
# Rule 28 (Mod 095) — health_check_path obliges a port.
# ---------------------------------------------------------------------------


def _validate_health_check_path_port(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 28 (Mod 095): declaring ``health_check_path`` obliges a ``port``.

    The path is only meaningful against a port — every role's translation
    probes ``http://localhost:${port}${field_value}``. No role declares a
    ``default_port`` (deliberately: an implicit health port would silently
    oblige the application to bind it), so an omitted ``port`` substitutes
    to the empty string and emits a malformed probe that surfaces as a
    container which never becomes healthy instead of as a compile error.

    Role-agnostic on purpose. It is vacuous for ``web``, whose port is
    already required by rule 15 for any web-network service, and it must
    stay that way rather than being special-cased per role.
    """
    issues: list[ValidationIssue] = []
    # Both the field and the port are process-scoped in CICL v2 — reading
    # them off the CoreService would see permanently empty extras and pass
    # while checking nothing.
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        if (proc.model_extra or {}).get("health_check_path") is None:
            continue
        if proc.port is None:
            issues.append(ValidationIssue(
                rule="rule_28_health_check_path_needs_port",
                message=(
                    f"core process type "
                    f"{ProcessRef(svc_name, proc_name).dotted!r} declares "
                    f"`health_check_path` but no `port`. The health probe is "
                    f"issued at http://localhost:<port><path>, so the path is "
                    f"meaningless without one, and no role supplies a default "
                    f"health port. See cicl.md § Validation Rules rule 28."
                ),
                where=f"{_process_where(svc_name, proc_name)}.port",
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
    targets: list[tuple[str, str, str, Any]] = [
        (
            "core_services",
            ProcessRef(svc_name, proc_name).dotted,
            _process_where(svc_name, proc_name),
            proc,
        )
        for svc_name, proc_name, _svc, proc in doc.all_processes()
    ]
    targets.extend(
        ("backing_services", name, f"backing_services.{name}", svc)
        for name, svc in sorted(doc.backing_services.items())
    )
    for kind, label, where, svc in targets:
        if svc.role == "reverse_proxy":
            issues.append(ValidationIssue(
                rule="rule_reverse_proxy_role_removed",
                message=(
                    f"{kind} {label!r} declares role 'reverse_proxy', "
                    f"which no longer exists. Per mod 031, the reverse "
                    f"proxy is project-tier infrastructure managed by "
                    f"the compiler (Traefik on fixed; ALB or EC2-Traefik "
                    f"on elastic via the top-level reverse_proxy: field)."
                ),
                where=where,
            ))
    return issues
