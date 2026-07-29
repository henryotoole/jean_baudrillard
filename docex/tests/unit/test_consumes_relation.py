"""Mod 098 — the `consumes` relation.

`consumes` is the interface half of the split `depends_on` used to conflate:
`depends_on` is a readiness gate naming backing services only (rule 24),
`consumes` is an interface edge between core process types (rule 25). This
module covers rule 25 itself, rule 7's newly kind-aware split (a backing
target is answered by `depends_on`, a core one by `consumes`), and the three
clarifications that fall out of *where* the rule-7 check sits rather than out
of extra conditionals.

In-memory documents in the style of ``test_process_nesting.py``. The
"nothing is emitted from `consumes`" guard needs a real project on disk and
lives in ``test_process_expansion_emit.py``.
"""

from __future__ import annotations

import json

import pytest
import yaml

from docex.cicl import magic_refs
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.errors import ValidationIssue


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _all(src: str) -> list[ValidationIssue]:
    return validate_document(_doc(src), _tables())


def _issues(src: str) -> list[str]:
    return [i.rule for i in _all(src)]


def _hits(src: str, prefix: str) -> list[ValidationIssue]:
    return [i for i in _all(src) if i.rule.startswith(prefix)]


_HEAD = """\
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
"""


def _proc(
    name: str,
    role: str = "worker",
    *,
    consumes: list[str] | None = None,
    depends_on: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> str:
    lines = [
        f"      {name}:",
        f"        role: {role}",
        '        command: ["python", "-m", "x"]',
        "        networks: [web, internal]" if role == "web"
        else "        networks: [internal]",
    ]
    if role == "web":
        lines.append("        port: 8080")
    if consumes is not None:
        lines.append(f"        consumes: {json.dumps(consumes)}")
    if depends_on is not None:
        lines.append(f"        depends_on: {json.dumps(depends_on)}")
    if env:
        lines.append("        env:")
        lines += [f"          {k}: {json.dumps(v)}" for k, v in env.items()]
    lines += [
        "        resources:",
        "          cpu: 0.5",
        "          memory: 512MB",
    ]
    return "\n".join(lines) + "\n"


def _codebase(name: str, *procs: str, env: dict[str, str] | None = None) -> str:
    out = f"  {name}:\n"
    if env:
        out += "    env:\n"
        out += "".join(f"      {k}: {json.dumps(v)}\n" for k, v in env.items())
    return out + "    processes:\n" + "".join(procs)


def _src(*codebases: str, backing: str = "") -> str:
    return _HEAD + "core_services:\n" + "".join(codebases) + backing


_APPDB = """\
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


def _api(web: str = "", worker: str = "", **kw) -> str:
    """The two-process base codebase: `api.web` + `api.worker`."""
    return _codebase(
        "api",
        web or _proc("web", "web"),
        worker or _proc("worker"),
        **kw,
    )


_BASE = _src(_api())


def test_base_document_is_clean():
    """Guard against vacuous passes below: the shared base validates clean."""
    assert _issues(_BASE) == []


def test_base_with_backing_service_is_clean():
    assert _issues(_src(_api(), backing=_APPDB)) == []


# ---------------------------------------------------------------------------
# Rule 25 — `consumes` names core process types, fully qualified, not itself.
# ---------------------------------------------------------------------------


def test_1_bare_core_service_target_rejected():
    """A bare service name is illegal, not shorthand: a codebase has no one
    boundary. `ProcessRef.parse` already owns that rule and its reasoning, so
    rule 25 reuses it rather than growing a second parser."""
    src = _src(_api(web=_proc("web", "web", consumes=["api"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_consumes_malformed"]
    assert "no single boundary" in hits[0].message
    assert hits[0].where == "core_services.api.processes.web.consumes"


def test_2_bare_backing_service_target_names_depends_on():
    """The migration mistake this field invites — reaching for the relation
    the author already knows. The bare form is dispatched on the namespace
    BEFORE the parser runs, because "a codebase has no single boundary" is
    the wrong answer to `consumes: [appdb]`."""
    src = _src(_api(web=_proc("web", "web", consumes=["appdb"])), backing=_APPDB)
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_consumes_malformed"]
    assert "`depends_on:`" in hits[0].message
    assert "appdb" in hits[0].message
    # The dispatch is the point: the author must NOT get the parser's text.
    assert "no single boundary" not in hits[0].message


def test_3_dotted_target_whose_service_is_backing_rejected():
    src = _src(
        _api(web=_proc("web", "web", consumes=["appdb.main"])), backing=_APPDB
    )
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_consumes"]
    assert "`depends_on:`" in hits[0].message


def test_4_unknown_codebase_rejected():
    src = _src(_api(web=_proc("web", "web", consumes=["ghost.web"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_consumes"]
    assert "'ghost'" in hits[0].message


def test_4_unknown_process_of_known_codebase_lists_the_known_ones():
    src = _src(_api(web=_proc("web", "web", consumes=["api.ghost"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_consumes"]
    assert "'ghost'" in hits[0].message
    # The message earns its length by listing what the author could have meant.
    assert "'web'" in hits[0].message
    assert "'worker'" in hits[0].message


@pytest.mark.parametrize("entry", ["a.b.c", "api.", ".web", "", " . "])
def test_5_wrong_arity_rejected(entry):
    src = _src(_api(web=_proc("web", "web", consumes=[entry])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_consumes_malformed"]
    assert "<service>.<process>" in hits[0].message


def test_6_self_consume_rejected_and_shares_the_rule_clause():
    """The self-reference RULE is stated once, in ``_SELF_REF_RULE``, and
    both messages that state it are built from the constant. Comparing
    against the constant rather than a retyped string is what pins rule 3's
    self-magic-ref message and rule 25's self-consumes message together: a
    reword of either without the other now fails here."""
    src = _src(_api(web=_proc("web", "web", consumes=["api.web"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_self_consumes"]
    assert magic_refs._SELF_REF_RULE in hits[0].message
    # Its OWN consequence: the health fan-out would proxy its own /health.
    assert "/health/api/web" in hits[0].message

    # The sibling states the same rule and a different consequence.
    ref_src = _src(
        _api(web=_proc(
            "web", "web", env={"U": "${core_services.api.web.host}"},
        ))
    )
    sibling = _hits(ref_src, "rule_3_self_magic_ref")
    assert sibling
    assert magic_refs._SELF_REF_RULE in sibling[0].message
    assert "localhost" in sibling[0].message


def test_6_self_consume_reported_once_not_as_a_redundant_pair():
    """The self case is checked before the exists-check, so `api.web`
    consuming itself does not also draw an unresolved-target complaint."""
    src = _src(_api(web=_proc("web", "web", consumes=["api.web"])))
    assert len(_hits(src, "rule_25_")) == 1


def test_legal_consumes_entry_is_clean():
    src = _src(_api(web=_proc("web", "web", consumes=["api.worker"])))
    assert _issues(src) == []


# ---------------------------------------------------------------------------
# Rule 7 — kind-aware. A backing target wants `depends_on`, a core process
# type wants `consumes`, and neither branch can reach the other's field.
# ---------------------------------------------------------------------------


_DB_REF = {"DATABASE_HOST": "${backing_services.appdb.host}"}
_WEB_REF = {"UPSTREAM": "${core_services.api.web.host}"}


def test_7_backing_kind_unchanged_violated_without_depends_on():
    src = _src(
        _api(worker=_proc("worker", env=_DB_REF)), backing=_APPDB
    )
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_depends_on"]


def test_7_backing_kind_unchanged_satisfied_with_depends_on():
    src = _src(
        _api(worker=_proc("worker", depends_on=["appdb"], env=_DB_REF)),
        backing=_APPDB,
    )
    assert _hits(src, "rule_7_") == []


def test_7_backing_kind_is_not_satisfiable_by_consumes():
    """The two fields are not interchangeable. `consumes` naming a backing
    service is itself rule-25 malformed, and it does not answer rule 7."""
    src = _src(
        _api(worker=_proc("worker", consumes=["appdb"], env=_DB_REF)),
        backing=_APPDB,
    )
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_depends_on"]


def test_8_core_kind_violated_without_consumes():
    src = _src(_api(worker=_proc("worker", env=_WEB_REF)))
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_consumes"]
    assert "api.web" in hits[0].message
    assert hits[0].where == "core_services.api.processes.worker"


def test_8_core_kind_satisfied_with_consumes():
    src = _src(
        _api(worker=_proc("worker", consumes=["api.web"], env=_WEB_REF))
    )
    assert _issues(src) == []


def test_8_core_kind_is_not_satisfiable_by_depends_on():
    """`depends_on: [api]` is rule-24 illegal and answers nothing. Pinning
    it keeps a future 'be lenient' refactor from re-conflating the two."""
    src = _src(
        _api(worker=_proc("worker", depends_on=["api"], env=_WEB_REF))
    )
    rules = _issues(src)
    assert "rule_7_magic_ref_implies_consumes" in rules
    assert "rule_24_depends_on_core_service" in rules


def test_8_malformed_consumes_entry_does_not_also_produce_a_rule_7_miss():
    """A malformed entry is reported once, by rule 25. The consumes set is
    built from PARSED refs, so `api.web.extra` cannot silently look like a
    missing edge against a target the author plainly named."""
    src = _src(
        _api(worker=_proc("worker", consumes=["api.web.extra"], env=_WEB_REF))
    )
    rules = _issues(src)
    assert rules.count("rule_25_consumes_malformed") == 1
    # It DOES still miss rule 7 — the edge genuinely was not declared — but
    # exactly once, and the two diagnostics say different things.
    assert rules.count("rule_7_magic_ref_implies_consumes") == 1


# ---------------------------------------------------------------------------
# The three clarifications. Each is a property of WHERE the check sits, so
# each gets its own test — a refactor that moves it loses the property
# silently.
# ---------------------------------------------------------------------------


def test_9_one_directional_edge_without_a_ref_is_clean():
    """ref ⇒ edge, never edge ⇒ ref. `api.web` declares `consumes:
    [api.worker]` for the contract and the health fan-out while holding no
    magic ref to the worker, because it reaches it through the broker. A
    bidirectional rule would reject the most common topology in existence."""
    src = _src(_api(web=_proc("web", "web", consumes=["api.worker"])))
    assert _issues(src) == []


def test_9_one_directional_the_target_owes_nothing_back():
    """The consumed process type declares nothing, and that is correct."""
    src = _src(
        _api(
            web=_proc("web", "web", consumes=["api.worker"], env={
                "W": "${core_services.api.worker.host}"
            }),
            worker=_proc("worker"),
        )
    )
    assert _hits(src, "rule_7_") == []


def test_10_same_codebase_is_not_exempt():
    """The check compares dotted targets and never compares codebases.
    Sharing source does not make it not a boundary — and the message says so,
    because this is the case an author will argue with."""
    src = _src(_api(worker=_proc("worker", env=_WEB_REF)))
    hits = _hits(src, "rule_7_magic_ref_implies_consumes")
    assert hits
    assert "same-codebase is not exempt" in hits[0].message


def test_10_cross_codebase_omits_the_same_codebase_clause():
    """The clause is conditional, not boilerplate."""
    src = _src(
        _api(worker=_proc(
            "worker", env={"U": "${core_services.other.web.host}"}
        )),
        _codebase("other", _proc("web", "web")),
    )
    hits = _hits(src, "rule_7_magic_ref_implies_consumes")
    assert hits
    assert "other.web" in hits[0].message
    assert "same-codebase is not exempt" not in hits[0].message


def test_11_service_level_env_ref_obliges_every_process_type():
    """Free from Mod 096's structure: the scan runs once per process type
    over its EFFECTIVE env, so a service-level ref is seen on every pass.
    The assertion that matters is the COUNT — one ref, two process types,
    one edge declared, therefore exactly one issue, naming the other.

    The target is a second codebase so that rule 3's self-reference clause
    does not fire on `api`'s own pass and pre-empt rule 7.
    """
    src = _src(
        _api(
            web=_proc("web", "web", consumes=["other.web"]),
            worker=_proc("worker"),
            env={"WEB_HOST": "${core_services.other.web.host}"},
        ),
        _codebase("other", _proc("web", "web")),
    )
    hits = _hits(src, "rule_7_magic_ref_implies_consumes")
    assert len(hits) == 1
    assert hits[0].where == "core_services.api.processes.worker"


def test_11_service_level_env_ref_clean_when_every_process_declares_it():
    src = _src(
        _api(
            web=_proc("web", "web", consumes=["other.web"]),
            worker=_proc("worker", consumes=["other.web"]),
            env={"WEB_HOST": "${core_services.other.web.host}"},
        ),
        _codebase("other", _proc("web", "web")),
    )
    assert _issues(src) == []


def test_11_service_level_ref_to_own_process_reports_as_self_reference():
    """No code makes this happen and none should: rule 3's self-ref check
    fires on that process's own pass and `continue`s before rule 7 is
    reached. That is the better message for it."""
    src = _src(
        _api(
            web=_proc("web", "web"),
            worker=_proc("worker", consumes=["api.web"]),
            env={"WEB_HOST": "${core_services.api.web.host}"},
        )
    )
    rules = _issues(src)
    assert "rule_3_self_magic_ref" in rules
    # `web`'s own pass reports self-reference; `worker` declared the edge.
    assert "rule_7_magic_ref_implies_consumes" not in rules


# ---------------------------------------------------------------------------
# The cycle asymmetry. One test, because it is the CONJUNCTION that is the
# doctrine.
# ---------------------------------------------------------------------------


def test_12_consumes_cycle_is_legal_while_a_depends_on_cycle_is_fatal():
    """`depends_on` is a DAG (a readiness cycle cannot be satisfied);
    `consumes` is a directed graph that may legitimately contain cycles —
    web calls the worker's API, the worker calls web's. No single field
    could carry a cycle rule that is simultaneously fatal and fine.

    The two halves are one test on purpose. Mechanically the legal half is
    *doing nothing*: rule 6's DFS walks the backing graph alone, since rule
    24 made core process types leaves of it. The hazard is a future reader
    "completing" the walk — which would break the first half while leaving
    the second half green, so neither assertion is a guard on its own.
    """
    cyclic_consumes = _src(
        _api(
            web=_proc("web", "web", consumes=["api.worker"]),
            worker=_proc("worker", consumes=["api.web"]),
        )
    )
    assert _issues(cyclic_consumes) == []

    cyclic_depends_on = _src(_api()) + """\
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
    depends_on: [cache]
  cache:
    role: cache
    engine: redis
    networks: [internal]
    port: 6379
    depends_on: [appdb]
"""
    assert "rule_6_depends_on_cycle" in _issues(cyclic_depends_on)


# ---------------------------------------------------------------------------
# The backing referencer — rule 7 correctly not applying.
# ---------------------------------------------------------------------------


# The design record's own example: an object_store whose CORS-origin field
# names a core web process type. Role-specific fields (not an `env:` block)
# because that is the shape the example describes — and because a backing
# `env:` block is currently scanned twice, once as an attribute and once
# through `model_extra`, which would make the counts below say nothing.
_STORE_WITH_CORE_REF = """\
backing_services:
  store:
    role: object_store
    engine: minio
    networks: [internal]
    cors_origin: "${core_services.api.web.host}"
    audit_sink: "${backing_services.appdb.host}"
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


def test_backing_referencer_core_ref_is_not_obliged():
    """A backing service holding `${core_services.api.web.host}` owes no
    edge. It has no `consumes:`, and rule 24 forbids it `depends_on: [api]`
    — but more to the point the ref is not a CALL: embedding a hostname in
    your own config (a CORS origin) implies no readiness coupling and
    crosses no interface boundary, so there is nothing for either relation
    to express. Rule 7 correctly not applying, not a hole in it.

    The `appdb` ref in the same block is the vacuity guard: it proves these
    templates ARE scanned, so the core ref was skipped rather than unseen.
    """
    src = _src(_api(), backing=_STORE_WITH_CORE_REF)
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_depends_on"]
    assert "appdb" in hits[0].message


def test_backing_referencer_core_ref_still_resolves_under_rule_3():
    """Skipping rule 7 does not skip rule 3 — a backing service's core ref
    must still name a process type that exists and exposes the part."""
    src = _src(_api(), backing=_STORE_WITH_CORE_REF)
    assert _hits(src, "rule_3_") == []

    bad = _src(
        _api(),
        backing=_STORE_WITH_CORE_REF.replace("api.web.host", "api.ghost.host"),
    )
    assert [i.rule for i in _hits(bad, "rule_3_")] == [
        "rule_3_unresolved_magic_ref"
    ]


# ---------------------------------------------------------------------------
# A backing service declaring `consumes:` — free behavior, pinned.
# ---------------------------------------------------------------------------


def test_14_consumes_on_a_backing_service_is_rejected_as_undeclared():
    """`consumes` is a ProcessType field. On a backing service it lands in
    `model_extra` and transfer-table rule 4 rejects it as a role-specific
    field no engine declares. Adequate — a bespoke message would be a new
    rule — but pinned so it cannot silently become permitted."""
    src = _src(_api(), backing=_APPDB.replace(
        "    schema_owned_by: api\n",
        "    schema_owned_by: api\n    consumes: [api.web]\n",
    ))
    hits = [i for i in _all(src) if i.rule == "tt_rule_4_undeclared_field"]
    assert hits
    assert "consumes" in hits[0].message


# ---------------------------------------------------------------------------
# Mod 101 — rule 25's scheduler clause. `contracts.md § Health Checks` states
# "a scheduler is never a `consumes` target" as fact; until Mod 101 nothing
# enforced it, so `consumes: [jobs.nightly]` validated clean and the contract /
# health gates had to work AROUND the gap.
# ---------------------------------------------------------------------------


_NIGHTLY = """\
      nightly:
        role: scheduler
        command: ["python", "-m", "x"]
        networks: [internal]
        schedule: "0 3 * * *"
        resources:
          cpu: 0.5
          memory: 512MB
"""


def test_consumes_scheduler_rejected():
    src = _src(
        _api(web=_proc("web", "web", consumes=["jobs.nightly"])),
        _codebase("jobs", _NIGHTLY),
    )
    hits = _hits(src, "rule_25_consumes_scheduler")
    assert len(hits) == 1
    assert hits[0].rule == "rule_25_consumes_scheduler"
    assert "jobs.nightly" in hits[0].message
    assert "scheduler" in hits[0].message
    assert hits[0].where == "core_services.api.processes.web.consumes"


def test_consumes_non_scheduler_in_the_same_document_is_clean():
    """The negative half: the clause fires on the scheduler target and on
    nothing else, so a legal edge in the same document stays silent."""
    src = _src(
        _api(web=_proc("web", "web", consumes=["api.worker"])),
        _codebase("jobs", _NIGHTLY),
    )
    assert _issues(src) == []


def test_consumes_scheduler_reported_once_not_alongside_an_unresolved():
    """One entry, one issue: the existence check `continue`s before the role
    check can also fire."""
    src = _src(
        _api(web=_proc("web", "web", consumes=["jobs.missing"])),
        _codebase("jobs", _NIGHTLY),
    )
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_consumes"]
