"""Mod 113 — the `uses` relation.

`uses` is the single relation between services (cicl.md § Uses Relationships).
An entry names a **backing service** bare (`database`) or a **core service**
dotted and fully qualified (`api.worker`), and classification is BY FORM —
`_SERVICE_NAME_RE` forbids a dot in any service name, so bare/dotted partitions
the entries with no overlap and no gap.

This module covers rule 25 itself, rule 7 (now ONE clause over one relation),
the standing scope rule that only a core service may declare `uses`, and the
three clarifications that fall out of *where* the rule-7 check sits rather than
out of extra conditionals.

Retired here with their subjects: the `depends_on`/`consumes` cycle asymmetry
(a backing service is now a graph SINK, so there is no backing cycle left to
build) and the "neither branch is satisfiable by the other" family (there is no
other branch).

In-memory documents in the style of ``test_service_nesting.py``. The
"nothing is emitted from `uses`" guard needs a real project on disk and
lives in ``test_service_expansion_emit.py``.
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
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
"""


def _proc(
    name: str,
    role: str = "worker",
    *,
    uses: list[str] | None = None,
    env: dict[str, str] | None = None,
    extra: list[str] | None = None,
) -> str:
    lines = [
        f"      {name}:",
        f"        role: {role}",
        '        command: ["python", "-m", "x"]',
        "        networks: [web, internal]" if role == "web"
        else "        networks: [internal]",
    ]
    # Mod 125. Every core service here is a potential `uses` target, so each
    # declares the surface rule 31 requires; a web one additionally declares the
    # `health_check_path` rule 33 requires of every web-network core service. A
    # non-web core service declares NO port — rule 32's negative arm forbids a
    # decorative one on a target reached through a queue.
    if role == "web":
        lines.append("        port: 8080")
        lines.append("        health_check_path: /health")
        lines.append("        surfaces:")
        lines.append("          rest:")
        lines.append("            api_styles: [rest]")
    else:
        lines.append("        surfaces:")
        lines.append("          events:")
        lines.append("            api_styles: [events]")
    if uses is not None:
        lines.append(f"        uses: {json.dumps(uses)}")
    lines.extend(extra or [])
    if env:
        lines.append("        env:")
        lines += [f"          {k}: {json.dumps(v)}" for k, v in env.items()]
    lines += [
        "        resources:",
        "          cpu: 0.5",
        "          memory: 512MB",
    ]
    return "\n".join(lines) + "\n"


def _codebase(name: str, *svcs: str, env: dict[str, str] | None = None) -> str:
    out = f"  {name}:\n"
    if env:
        out += "    env:\n"
        out += "".join(f"      {k}: {json.dumps(v)}\n" for k, v in env.items())
    return out + "    core_services:\n" + "".join(svcs)


def _src(*codebases: str, backing: str = "") -> str:
    return _HEAD + "codebases:\n" + "".join(codebases) + backing


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
    """The two-core-service base codebase: `api.web` + `api.worker`."""
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
# Rule 25 — `uses` names a backing service bare, or a core service fully
# qualified, and never itself.
# ---------------------------------------------------------------------------


def test_1_bare_codebase_name_rejected():
    """A bare codebase name is illegal, not shorthand for "all its core
    services": an interface edge points at a specific boundary, and a codebase
    does not have one contract. This is the mistake the merged field invites,
    so it is dispatched on the codebase namespace and gets its own message."""
    src = _src(_api(web=_proc("web", "web", uses=["api"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_uses_malformed"]
    assert "does not have one contract" in hits[0].message
    assert hits[0].where == "codebases.api.core_services.web.uses"


def test_2_bare_backing_service_target_is_legal():
    """The merge's whole point: one field carries both target kinds, so a bare
    backing name is now the CORRECT form rather than a rule-25 violation."""
    src = _src(_api(web=_proc("web", "web", uses=["appdb"])), backing=_APPDB)
    assert _issues(src) == []


def test_2b_bare_name_matching_nothing_is_unresolved():
    """The surviving unknown-target check (formerly `rule_6_unknown_depends_on`,
    named for a retired rule but live and necessary). A typo'd target must fail
    at COMPILE time, not later as an unresolvable magic ref or not at all."""
    src = _src(_api(web=_proc("web", "web", uses=["ghostdb"])), backing=_APPDB)
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_uses"]
    assert "ghostdb" in hits[0].message
    # The message earns its length by listing what the author could have meant.
    assert "appdb" in hits[0].message
    assert hits[0].where == "codebases.api.core_services.web.uses"


def test_3_dotted_target_whose_codebase_is_a_backing_service_rejected():
    src = _src(
        _api(web=_proc("web", "web", uses=["appdb.main"])), backing=_APPDB
    )
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_uses"]
    assert "'appdb'" in hits[0].message


def test_4_unknown_codebase_rejected():
    src = _src(_api(web=_proc("web", "web", uses=["ghost.web"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_uses"]
    assert "'ghost'" in hits[0].message


def test_4_unknown_service_of_known_codebase_lists_the_known_ones():
    src = _src(_api(web=_proc("web", "web", uses=["api.ghost"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_uses"]
    assert "'ghost'" in hits[0].message
    assert "'web'" in hits[0].message
    assert "'worker'" in hits[0].message


@pytest.mark.parametrize("entry", ["a.b.c", "api.", ".web", " . "])
def test_5_wrong_arity_rejected(entry):
    """Every one of these CONTAINS a dot, so form classifies it as a core
    target and the parser is what rejects it."""
    src = _src(_api(web=_proc("web", "web", uses=[entry])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_uses_malformed"]
    assert "<codebase>.<service>" in hits[0].message


def test_5b_empty_entry_is_a_bare_name_and_resolves_to_nothing():
    """The dotless counterpart of the arity cases: `""` holds no dot, so it is
    a BACKING target by form, and it names nothing that exists."""
    src = _src(_api(web=_proc("web", "web", uses=[""])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_unresolved_uses"]


def test_6_self_use_rejected_and_shares_the_rule_clause():
    """The self-reference RULE is stated once, in ``_SELF_REF_RULE``, and
    both messages that state it are built from the constant. Comparing
    against the constant rather than a retyped string is what pins rule 3's
    self-magic-ref message and rule 25's self-`uses` message together: a
    reword of either without the other now fails here."""
    src = _src(_api(web=_proc("web", "web", uses=["api.web"])))
    hits = _hits(src, "rule_25_")
    assert [i.rule for i in hits] == ["rule_25_self_uses"]
    assert magic_refs._SELF_REF_RULE in hits[0].message
    # Its OWN consequence: the core service would be its own `uses` target, so
    # rules 31/32 would be satisfied against itself.
    assert "rules 31 and 32" in hits[0].message
    assert "against itself" in hits[0].message

    # The sibling states the same rule and a different consequence.
    ref_src = _src(
        _api(web=_proc(
            "web", "web", env={"U": "${codebases.api.core_services.web.host}"},
        ))
    )
    sibling = _hits(ref_src, "rule_3_self_magic_ref")
    assert sibling
    assert magic_refs._SELF_REF_RULE in sibling[0].message
    assert "localhost" in sibling[0].message


def test_6_self_use_reported_once_not_as_a_redundant_pair():
    """The self case is checked before the exists-check, so `api.web`
    using itself does not also draw an unresolved-target complaint."""
    src = _src(_api(web=_proc("web", "web", uses=["api.web"])))
    assert len(_hits(src, "rule_25_")) == 1


def test_legal_mixed_uses_list_is_clean():
    """Both kinds in one list — the shape the merge exists to allow."""
    src = _src(
        _api(web=_proc("web", "web", uses=["appdb", "api.worker"])),
        backing=_APPDB,
    )
    assert _issues(src) == []


# ---------------------------------------------------------------------------
# Rule 7 — ONE clause over ONE relation. A magic ref must be matched by a
# `uses` entry on the referencing core service, whatever the target's kind.
# ---------------------------------------------------------------------------


_DB_REF = {"DATABASE_HOST": "${backing_services.appdb.host}"}
_WEB_REF = {"UPSTREAM": "${codebases.api.core_services.web.host}"}


def test_7_backing_target_violated_without_uses():
    src = _src(
        _api(worker=_proc("worker", env=_DB_REF)), backing=_APPDB
    )
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_uses"]
    assert "appdb" in hits[0].message


def test_7_backing_target_satisfied_with_uses():
    src = _src(
        _api(worker=_proc("worker", uses=["appdb"], env=_DB_REF)),
        backing=_APPDB,
    )
    assert _hits(src, "rule_7_") == []


def test_8_core_target_violated_without_uses():
    src = _src(_api(worker=_proc("worker", env=_WEB_REF)))
    hits = _hits(src, "rule_7_")
    assert [i.rule for i in hits] == ["rule_7_magic_ref_implies_uses"]
    assert "api.web" in hits[0].message
    assert hits[0].where == "codebases.api.core_services.worker"


def test_8_core_target_satisfied_with_uses():
    src = _src(
        _api(worker=_proc("worker", uses=["api.web"], env=_WEB_REF))
    )
    assert _issues(src) == []


def test_8_one_id_answers_both_target_kinds():
    """Two ids became one because the rule is one. A document missing both a
    backing edge and a core edge reports the SAME id twice — which is the
    property that would silently regress if the branches ever re-split."""
    src = _src(
        _api(worker=_proc("worker", env={**_DB_REF, **_WEB_REF})),
        backing=_APPDB,
    )
    hits = _hits(src, "rule_7_")
    assert {i.rule for i in hits} == {"rule_7_magic_ref_implies_uses"}
    assert len(hits) == 2


def test_8_malformed_uses_entry_does_not_also_produce_a_rule_7_miss():
    """A malformed entry is reported once, by rule 25. The `uses` set the
    rule-7 check reads is built from PARSED refs, so `api.web.extra` cannot
    silently look like a missing edge against a target the author plainly
    named."""
    src = _src(
        _api(worker=_proc("worker", uses=["api.web.extra"], env=_WEB_REF))
    )
    rules = _issues(src)
    assert rules.count("rule_25_uses_malformed") == 1
    # It DOES still miss rule 7 — the edge genuinely was not declared — but
    # exactly once, and the two diagnostics say different things.
    assert rules.count("rule_7_magic_ref_implies_uses") == 1


# ---------------------------------------------------------------------------
# The three clarifications. Each is a property of WHERE the check sits, so
# each gets its own test — a refactor that moves it loses the property
# silently.
# ---------------------------------------------------------------------------


def test_9_one_directional_edge_without_a_ref_is_clean():
    """ref ⇒ edge, never edge ⇒ ref. `api.web` declares `uses:
    [api.worker]` for the contract while holding no magic ref to the worker,
    because it reaches it through the broker. A bidirectional rule would
    reject the most common topology in existence."""
    src = _src(_api(web=_proc("web", "web", uses=["api.worker"])))
    assert _issues(src) == []


def test_9_one_directional_the_target_owes_nothing_back():
    """The used core service declares nothing, and that is correct."""
    src = _src(
        _api(
            web=_proc("web", "web", uses=["api.worker"], env={
                "W": "${codebases.api.core_services.worker.host}"
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
    hits = _hits(src, "rule_7_magic_ref_implies_uses")
    assert hits
    assert "same-codebase is not exempt" in hits[0].message


def test_10_cross_codebase_omits_the_same_codebase_clause():
    """The clause is conditional, not boilerplate."""
    src = _src(
        _api(worker=_proc(
            "worker", env={"U": "${codebases.other.core_services.web.host}"}
        )),
        _codebase("other", _proc("web", "web")),
    )
    hits = _hits(src, "rule_7_magic_ref_implies_uses")
    assert hits
    assert "other.web" in hits[0].message
    assert "same-codebase is not exempt" not in hits[0].message


def test_11_codebase_level_env_ref_obliges_every_core_service():
    """Free from Mod 096's structure: the scan runs once per core service
    over its EFFECTIVE env, so a codebase-level ref is seen on every pass.
    The assertion that matters is the COUNT — one ref, two core services,
    one edge declared, therefore exactly one issue, naming the other.

    The target is a second codebase so that rule 3's self-reference clause
    does not fire on `api`'s own pass and pre-empt rule 7.
    """
    src = _src(
        _api(
            web=_proc("web", "web", uses=["other.web"]),
            worker=_proc("worker"),
            env={"WEB_HOST": "${codebases.other.core_services.web.host}"},
        ),
        _codebase("other", _proc("web", "web")),
    )
    hits = _hits(src, "rule_7_magic_ref_implies_uses")
    assert len(hits) == 1
    assert hits[0].where == "codebases.api.core_services.worker"


def test_11_codebase_level_env_ref_clean_when_every_service_declares_it():
    src = _src(
        _api(
            web=_proc("web", "web", uses=["other.web"]),
            worker=_proc("worker", uses=["other.web"]),
            env={"WEB_HOST": "${codebases.other.core_services.web.host}"},
        ),
        _codebase("other", _proc("web", "web")),
    )
    assert _issues(src) == []


def test_11_codebase_level_ref_to_own_service_reports_as_self_reference():
    """No code makes this happen and none should: rule 3's self-ref check
    fires on that core service's own pass and `continue`s before rule 7 is
    reached. That is the better message for it."""
    src = _src(
        _api(
            web=_proc("web", "web"),
            worker=_proc("worker", uses=["api.web"]),
            env={"WEB_HOST": "${codebases.api.core_services.web.host}"},
        )
    )
    rules = _issues(src)
    assert "rule_3_self_magic_ref" in rules
    # `web`'s own pass reports self-reference; `worker` declared the edge.
    assert "rule_7_magic_ref_implies_uses" not in rules


# ---------------------------------------------------------------------------
# Cycles. `test_12_consumes_cycle_is_legal_while_a_depends_on_cycle_is_fatal`
# is DELETED: its subject was the ASYMMETRY between two relations, and there
# is one relation now. The legal half survives on its own below — a backing
# service declares no outbound edges, so it is a graph SINK and the fatal half
# cannot be constructed at all (cicl.md § The graph may contain cycles).
# ---------------------------------------------------------------------------


def test_12_core_target_cycle_is_legal_and_compiles_clean():
    """`web ↔ worker` — web calls the worker's API, the worker calls web's.
    It is the most common topology in existence and it must validate clean."""
    src = _src(
        _api(
            web=_proc("web", "web", uses=["api.worker"]),
            worker=_proc("worker", uses=["api.web"]),
        )
    )
    assert _issues(src) == []


# ---------------------------------------------------------------------------
# The backing referencer — rule 7 correctly not applying.
# ---------------------------------------------------------------------------


# The design record's own example: an object_store whose CORS-origin field
# names a core web core service. Role-specific fields (not an `env:` block)
# because that is the shape the example describes — and because a backing
# `env:` block is currently scanned twice, once as an attribute and once
# through `model_extra`, which would make the counts below say nothing.
_STORE_WITH_CORE_REF = """\
backing_services:
  store:
    role: object_store
    engine: minio
    networks: [internal]
    cors_origin: "${codebases.api.core_services.web.host}"
    audit_sink: "${backing_services.appdb.host}"
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


def test_backing_referencer_owes_no_edge_for_a_ref_of_either_kind():
    """A backing service holding `${codebases.api.core_services.web.host}` owes
    no edge, and neither does one holding `${backing_services.appdb.host}`.

    Rule 7 governs the referencing CORE SERVICE. A backing service declares no
    outbound edges at all — it is a graph sink — so there is nothing it could
    declare. More to the point the ref is not a CALL: embedding a hostname in
    your own config (a CORS origin) crosses no interface boundary, so there is
    no interface implication for the relation to express. Rule 7 correctly not
    applying, not a hole in it (cicl.md rule 7, second sentence onward).

    Vacuity is guarded by its sibling below: the same templates DO reach rule
    3, so these refs were skipped by rule 7 rather than never scanned.
    """
    src = _src(_api(), backing=_STORE_WITH_CORE_REF)
    assert _hits(src, "rule_7_") == []


def test_backing_referencer_core_ref_still_resolves_under_rule_3():
    """Skipping rule 7 does not skip rule 3 — a backing service's core ref
    must still name a core service that exists and exposes the part. This is
    also the vacuity guard for the test above."""
    src = _src(_api(), backing=_STORE_WITH_CORE_REF)
    assert _hits(src, "rule_3_") == []

    bad = _src(
        _api(),
        backing=_STORE_WITH_CORE_REF.replace(
            "core_services.web.host", "core_services.ghost.host"
        ),
    )
    assert [i.rule for i in _hits(bad, "rule_3_")] == [
        "rule_3_unresolved_magic_ref"
    ]


# ---------------------------------------------------------------------------
# Scope: only a core service declares `uses`. Not a numbered rule — cicl.md's
# Service Fields scope column plus the standing "fails loudly when a field is
# in the wrong scope" sentence. Mod 112 declined to invent a number and this
# mod does not invent one either.
# ---------------------------------------------------------------------------


def test_uses_on_a_backing_service_is_rejected_with_a_targeted_message():
    """`uses` on a backing service must be reported ONCE, by this check —
    which is why "uses" is in `_STANDARD_BACKING_FIELDS` and the extras walk
    stays quiet. The message must state the sink property and point at the
    engine's transfer-table `defaults` block as the correct home.

    This is also the only form the acyclicity claim can take: a backing
    service has no field with which to point back, so a backing-targeted cycle
    cannot be built rather than being rejected once built.
    """
    src = _src(_api(), backing=_APPDB.replace(
        "    schema_owned_by: api\n",
        "    schema_owned_by: api\n    uses: [api.web]\n",
    ))
    hits = [i for i in _all(src) if i.rule == "rule_uses_on_backing_service"]
    assert len(hits) == 1
    assert "sink" in hits[0].message.lower()
    assert "defaults" in hits[0].message
    assert hits[0].where == "backing_services.appdb"
    # Single reporter: the extras walk must NOT also complain about it.
    assert "tt_rule_4_undeclared_field" not in _issues(src)


# ---------------------------------------------------------------------------
# The retired fields are HARD ERRORS, never silent aliases. Model-layer, so
# they raise rather than aggregating — the same treatment
# `Codebase._reject_v1_shape` gives the other one-time migration mistake.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["depends_on", "consumes"])
def test_retired_relation_on_a_core_service_is_a_hard_error(field):
    src = _src(_api(web=_proc(
        "web", "web", extra=[f"        {field}: [appdb]"],
    )), backing=_APPDB)
    with pytest.raises(Exception) as exc:
        _doc(src)
    msg = str(exc.value)
    assert field in msg
    assert "`uses`" in msg
    assert "upgrade_1.7.0.md" in msg


@pytest.mark.parametrize("field", ["depends_on", "consumes"])
def test_retired_relation_on_a_backing_service_is_a_hard_error(field):
    """The backing message says something the core one cannot: a backing
    service declares NO outbound edges, so the fix is deletion, not a rename
    to `uses`. Engine-level container needs belong in the transfer table."""
    src = _src(_api(), backing=_APPDB.replace(
        "    schema_owned_by: api\n",
        f"    schema_owned_by: api\n    {field}: [api.web]\n",
    ))
    with pytest.raises(Exception) as exc:
        _doc(src)
    msg = str(exc.value)
    assert field in msg
    assert "sink" in msg.lower()
    assert "upgrade_1.7.0.md" in msg


def test_cicl_version_2_is_rejected_and_the_message_names_3():
    """Rule 21: earlier generations are REJECTED, not translated."""
    src = _BASE.replace('cicl_version: "3"', 'cicl_version: "2"')
    with pytest.raises(Exception) as exc:
        _doc(src)
    msg = str(exc.value)
    assert "'2'" in msg
    assert "'3'" in msg
