# Mod 178 — Implementation Steps

Fix the web-only-codebase exec-service network-orphan leak. All paths are
absolute from the repo root `~/.claude/jean_baudrillard` unless noted. The docex
project root is `~/.claude/jean_baudrillard/docex`.

Run tests from the docex root with the venv interpreter:
`cd ~/.claude/jean_baudrillard/docex && .venv/bin/python -m pytest tests`
(NOT bare `pytest`, NOT `tests/unit`). If you add an integration-marked test, run
`-m integration` **alone**.

---

## Step 1 — Code: the `else` branch in `emit/compose.py`

File: `docex/src/docex/emit/compose.py`, the exec-service pass (~line 595).

Current:

```py
        exec_nets = sorted({
            n for p in svcs for n in p.networks if n != "web"
        })
        if exec_nets:
            # Never `web`: the exec container is a one-off operations shell
            # and is never publicly routed.
            exec_block["networks"] = exec_nets
```

Change to:

```py
        exec_nets = sorted({
            n for p in svcs for n in p.networks if n != "web"
        })
        if exec_nets:
            # Never `web`: the exec container is a one-off operations shell
            # and is never publicly routed.
            exec_block["networks"] = exec_nets
        else:
            # Empty-set fallback (mod 178). A web-only codebase — a frontend
            # whose only core service is on `web` and uses no backing service —
            # has NO non-`web` network, so the union above is empty. Emitting
            # neither `networks:` nor `network_mode:` would drop the exec
            # container onto Compose's implicit, auto-created `<project>_default`
            # bridge (never declared in the top-level `networks:` block); every
            # `compose run --rm …-exec` then mints an unreaped `_default`, and
            # `--slots N` multiplies it until the host address pool exhausts.
            # WHY `none` and not an `internal` attachment: a one-off build/test/
            # ops shell for a web-only codebase needs no intra-stack network at
            # all — dependencies install at image-build, not at exec — and there
            # is no `internal` for it to join. `none` creates ZERO networks.
            # See doctrine/infrastructure/specifics/exec_service.md § What the
            # block carries (Networks).
            exec_block["network_mode"] = "none"
```

Do not change the non-empty `if` branch — the fix is purely additive.

---

## Step 2 — Tests: web-only fixture + compiled-output assertions

File: `docex/tests/unit/test_exec_service.py`.

Add a web-only-codebase project builder and a module-scoped compiled fixture
beside the existing `_multi_service_project` / `fixed_root` (the suite compiles
projects programmatically; no `core/` folder is needed — compile is
offline-pure). Then add assertions.

1. After the `_WORKER` dict, add the builder:

```py
def _web_only_project(fixture: Path, dest: Path) -> Path:
    """`sample_project` plus a frontend-like codebase whose ONLY core service
    sits on `web` and uses no backing service — so its exec service's non-`web`
    network union is empty. This is the shape that reproduced the mod-178 leak;
    the stock `api` codebase (on `internal`) does not."""
    root = dest / "project"
    shutil.copytree(fixture, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)
    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["codebases"]["frontend"] = {
        "core_services": {
            "web": {
                "role": "web",
                "command": ["node", "/service/dist/server.js"],
                "port": 3000,
                "networks": ["web"],
                "health_check_path": "/health",
                "resources": {"cpu": 0.5, "memory": "512MB"},
            }
        }
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return root


@pytest.fixture(scope="module")
def web_only_root(tmp_path_factory) -> Path:
    root = _web_only_project(_FIXED, tmp_path_factory.mktemp("exec_web_only"))
    assert run_compile(load_project_context(root)) == 0
    return root
```

2. Add tests (place near `test_6` / `test_7`):

```py
def test_8_web_only_codebase_exec_gets_network_mode_none(web_only_root: Path):
    """Mod 178. A web-only codebase's exec service has an empty non-`web`
    network union. It must NOT be emitted network-less (that lands it on
    Compose's implicit `<project>_default`); it carries explicit
    `network_mode: none` and no `networks:` key, so it creates zero networks."""
    for env in ("dev", "test", "stage", "prod"):
        services = _services(web_only_root, env)
        fe = services[f"sample-{env}-frontend-exec"]
        assert fe.get("network_mode") == "none", (env, sorted(fe))
        assert "networks" not in fe, (env, sorted(fe))
        # Anti-vacuity: the frontend really is a web-only codebase.
        assert services[f"sample-{env}-frontend-web"]["networks"] == ["web"]


def test_8b_no_service_falls_onto_the_implicit_default(web_only_root: Path):
    """The leak's mechanism: a service with NEITHER `networks:` nor
    `network_mode:` attaches to the auto-created `<project>_default`, which the
    top-level `networks:` block never declares. Assert no emitted service is in
    that state, and that `default` is never a declared network."""
    for env in ("dev", "test", "stage", "prod"):
        doc = yaml.safe_load(
            (web_only_root / "infra" / "output" / env / "docker-compose.yml")
            .read_text()
        )
        assert "default" not in (doc.get("networks") or {}), env
        for name, block in doc["services"].items():
            has_intent = "networks" in block or "network_mode" in block
            assert has_intent, (env, name)


def test_8c_non_empty_exec_nets_still_networks_no_network_mode(
    web_only_root: Path,
):
    """SC2 guard: the `internal`-bearing exec service (the non-empty union) is
    unchanged — it carries `networks:` and NEVER `network_mode:`. The mod is a
    pure `else`-branch addition."""
    for env in ("dev", "test", "stage", "prod"):
        api_exec = _services(web_only_root, env)[f"sample-{env}-api-exec"]
        assert api_exec["networks"] == ["internal"], env
        assert "network_mode" not in api_exec, env
```

Note: `test_8b` iterates **all** services including the otelcol sidecars, which
carry `network_mode: service:<app>` — that satisfies `has_intent`, so the guard
is correct for them too.

Do **not** add the web-only variant to `test_21_all_fixtures_still_compile` —
that test parametrizes over the *bundled* fixture directories, and this variant
is built programmatically, not shipped as a directory.

---

## Step 3 — Doctrine: `exec_service.md` Networks rule (empty-set fallback)

File: `doctrine/infrastructure/specifics/exec_service.md`, the "What the block
carries" table, Networks row (line 32).

Replace:

```md
| Networks | The union of the codebase's networks **less `web`**. A one-off operations shell is never publicly routed. |
```

with:

```md
| Networks | The union of the codebase's networks **less `web`** — a one-off operations shell is never publicly routed. When that union is **empty** (a web-only codebase: its only core service is on `web` and it uses no backing service), the block instead declares **`network_mode: none`** — an exec shell with nothing internal to reach needs no network, and explicit intent keeps Compose from auto-attaching it to an undeclared `<project>_default` bridge. |
```

This is the only edit to this file.

---

## Step 4 — Doctrine: `default-address-pools` stanza in `fixed_master_network.md`

File: `doctrine/infrastructure/preinfra/fixed_master_network.md`.

Add a new top-level section **after** the `## The `docex-ingress` Network`
section and **before** `## Other Concerns` (i.e. insert immediately before the
line `## Other Concerns`). Section content:

```md
## The Docker Address Pool

Every env stack, every `docex test --slots N` shard, and every ephemeral `check`
worktree creates Docker networks on this host. Docker's built-in default address
pools subnet out at roughly **31** user networks — a ceiling a busy dev machine
reaches quickly: standing `dev` + `stage` + `prod` stacks, a `--slots 8` test run
(each slot its own `internal` + per-slot `web` bridges), and a check worktree's
networks together blow past it, and the failure is opaque —
`all predefined address pools have been fully subnetted` mid-`compose up`.

Raise the ceiling with a `default-address-pools` stanza in the host's
`/etc/docker/daemon.json` — the **same file** the observability-backend log-cap
stanza configures (see
[`telemetry_preinfra.md § HyperDX Installation, step 6`](./telemetry_preinfra.md#hyperdx-installation));
merge both keys into one object rather than writing the file twice:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "100m", "max-file": "3" },
  "default-address-pools": [
    { "base": "10.200.0.0/16", "size": 24 }
  ]
}
```

`base: 10.200.0.0/16` + `size: 24` yields 256 `/24` subnets — an order of
magnitude over the default ceiling. Then restart the daemon so it takes effect:
`sudo systemctl restart docker`.

Three caveats, the first two shared with the log-cap stanza:

- **Applies only to networks created *after* it is set.** Existing networks keep
  their current subnets until recreated (`docker compose down` / `up`, or
  `docker network rm` + recreate).
- **On a shared host the daemon default applies machine-wide**, and restarting
  the daemon **bounces every container on the host**, not just this project's —
  schedule the restart accordingly.
- **The pool must not overlap** the master network / `docex-ingress` bridge or
  any existing subnet on the host (`docker network inspect` the existing bridges
  to confirm their subnets sit outside `10.200.0.0/16`; adjust `base` if they
  collide). An overlapping pool breaks routing for the colliding networks.

This is operator host configuration, not something `docex` emits or applies.
```

Adjust the exact insertion point if the file's headings differ, but keep it as a
sibling `##` section co-located with the network/subnet material it concerns.

---

## Step 5 — Design doc: `compiler.md` exec-service section

File: `docex/plans/design/specifics/compiler.md`, the per-codebase exec-service
paragraph (~line 310-318, sentence "It carries the codebase's image ref …").

In that paragraph, the clause "the union of the codebase's non-`web` networks"
must note the empty-set fallback. Replace that clause so the sentence reads (edit
just the networks clause, leave the rest of the paragraph intact):

```md
bind mounts in `dev`, the union of the codebase's non-`web` networks (or
`network_mode: none` when that union is empty — a web-only codebase, mod 178,
so Compose never auto-attaches the exec container to an undeclared
`<project>_default`), and the
```

---

## Step 6 — Run the suite

From the docex root:

```
.venv/bin/python -m pytest tests
```

Expect green. If anything in `test_exec_service.py` fails, fix the test or code
per the intent above — the compiled-output assertions in Step 2 are the mod-level
gate for SC1/SC6.

No integration test is required for this mod (the live `--slots` check is Phase D
step 0). Do not add or run one unless trivial.

---

## Out of scope / do NOT do

- No contract changes: `docex` has no `infra.yml`/surfaces of its own.
- No `tables/roles/*.yml` change (the exec service is a compiler derivative, not
  a role).
- No `doctrine_excerpts/*.md` or `index.yml` change (no new infrastructural
  resource; no existing excerpt describes exec-service networks).
- No version-artifact, `CHANGELOG.md`, or `RELEASING.md` edits (Phase D).
- Do NOT touch `telemetry_preinfra.md`, any other doctrine file, or the
  untracked `skills/doc-cohere/SKILL.md`.
- No `--remove-orphans` / reaper change (report fix #2 is dropped by decision).
