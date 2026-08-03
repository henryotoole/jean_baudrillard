# Mod 110 — Implementation Steps

Design: [`overview.md`](./overview.md). Read it first — it carries the rationale
for *why* the flag goes rather than a second bridge being added, and you will
need that rationale for the comments and docstrings below.

Four files change. No new files. Repo root is `~/.claude/jean_baudrillard`.

---

## Step 1 — `src/docex/emit/compose.py::_network_section`

Currently (around line 110-137) the function emits every non-`web` network with
`internal: True`, and its docstring states that flag as though it were doctrine.

**1a.** In the emit loop, drop the flag:

```python
        full = f"{compiled.project_dns_label}-{compiled.env}-{short}"
        out[short] = {"name": full}
```

Leave the `web` special-case (the `external: True` branch) untouched.

**1b.** Rewrite the docstring's first paragraph. It currently reads:

> Every non-``web`` network compiles to a project-scoped docker network
> named ``${project}-${env}-${shortname}`` with ``internal: true``.

Replace that sentence with a statement of the plain-bridge shape **and the
reason the flag is absent**, because the flag's absence is the load-bearing part
and a future reader will otherwise "helpfully" restore it. Cover, concisely:

- A non-`web` network is a plain user-defined bridge with no published ports.
  That is already exactly what `networks.md § networks: [internal]` promises:
  reachable from services on the same network, not from other networks, not from
  the public internet.
- Docker's `internal: true` is **not** used. It contributes no ingress
  protection — cross-network isolation comes from Docker's own inter-bridge
  isolation rules, and the host can reach an internal network's containers just
  as easily, since the gateway is in-subnet. Its only effect is to strip the
  bridge's masquerade rule, which kills egress and contradicts
  `networks.md § Egress` ("Nothing project-specific or doctrine-emitted is
  involved") as well as elastic's allow-all SG egress.
- Cite mod 110.

Keep the existing "Per mod 030's naming unification…" and `web`/mod-036
paragraphs as they are.

Follow [`practices/comments.md`](../../../../doctrine/practices/comments.md): this
is a WHY comment about a non-obvious *absence*, which is exactly the case that
doc says to document.

---

## Step 2 — `tests/unit/test_compose_emitter.py`

**2a.** `test_web_network_is_project_env_external_and_others_are_project_scoped`
(line ~187) asserts `internal.get("internal") is True` at line ~211. Invert it
to assert the key is **absent**, and say why in the assertion:

```python
        # Mod 110: no ``internal: true``. It buys no ingress protection
        # (inter-bridge isolation and the absent published ports already
        # give that) and its only real effect is killing egress, which
        # contradicts networks.md § Egress and elastic's allow-all SG.
        assert "internal" not in internal, internal
```

Update the test's docstring, which currently says other networks keep
`internal: true` — it must now say they are plain project-scoped bridges, citing
mod 110 alongside the existing mod 036 reference. Keep the `name` assertion and
the whole `web` branch unchanged.

**2b.** Add a regression test in the same file. Name it for the *bug*, not the
flag, so its purpose survives:

```python
def test_non_web_only_service_is_not_egress_isolated(tmp_path: Path):
```

It must assert, for all four envs, that **no** network in the emitted
`networks:` block carries an `internal` key — iterate the block rather than
naming `internal` specifically, so a project that adds a third non-`web` network
is covered too. Docstring should name the two concrete failures this prevents,
both from `overview.md`: the fixed `stage`/`prod` OTel sidecar unable to reach
`OBSERVABILITY_BACKEND_URL` (it shares its partner's netns via
`network_mode: service:<container>`, so a `[internal]`-only partner strands it),
and a `worker` unable to reach a third-party API.

Match the file's existing fixture idiom — `_copy_fixture(tmp_path)`,
`load_project_context`, `run_compile`, then read
`infra/output/<env>/docker-compose.yml`. Do not invent a new fixture.

---

## Step 3 — `doctrine/infrastructure/specifics/networks.md`

**Operator-approved edit.** Surgical: one sentence, no restructuring.

In `### networks: [internal] (and any other non-special name)` (line ~56), the
**Fixed** bullet (line ~60) currently ends with "Docker enforces network
isolation." Append one sentence naming the mechanism and the deliberate absence,
so the flag cannot drift back in. It must convey: the network is a plain
user-defined bridge and the isolation comes from Docker's inter-bridge rules plus
the absence of published ports — Docker's `internal: true` flag is deliberately
**not** used, because it would additionally strip egress, which
[§ Egress](#egress) forbids.

Constraints:

- Match the surrounding register — dense declarative prose, no bullets, no
  hedging.
- Do **not** touch `§ Egress`; it is already correct and is the rule this cites.
- Do **not** touch the Elastic bullet.
- Do not add a mod number (doctrine prose does not carry them; only docex code
  and core docs do).

---

## Step 4 — Verify

From the repo root:

```bash
cd docex && python -m pytest tests/unit -q
```

Then the full suite including integration:

```bash
cd docex && python -m pytest -q -m integration
```

Both must be green. The unit suite was 994 passing at the 1.6.0 cut and the
integration suite 17; expect those counts plus your one new test.

If any *other* test asserted the old flag, that is a real finding — fix it the
same way (invert + explain) and report it in your summary rather than silently
adjusting.

---

## Out of scope

- Do **not** add a second bridge network, a `gw_priority` key, or any
  per-container egress mechanism. `overview.md § Rejected alternative` explains
  why; implementing it would contradict the approved design.
- Do **not** touch the `web` branch of `_network_section`, the projinfra network
  emission, or anything on the elastic side.
- Do **not** update `CHANGELOG.md`, `VERSION`, or any core planning doc — the
  mod cycle's documentation step and the release handle those.
