# Mod 086 — Core-doc alignment + upgrade guide + changelog

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 11 of 11). The documentation-alignment mod: brings the `docex`
core planning docs into sync with mods 076-085, writes the `upgrade_1.5.0.md`
project-upgrade guide, adds the changelog entry, and marks the campaign
implemented.

## Why

Per [docex_process.md § Additional Artifacts](../../core/docex_process.md#additional-artifacts),
the five layers (doctrine ⇄ core docs ⇄ tables ⇄ src ⇄ tests) must stay aligned.
Mods 076-085 changed doctrine + tables + src + tests; the `docex/plans/core/*`
narrative is the remaining layer. And a MINOR cut ships a project-upgrade guide.

## What each artifact needs

- **`docex/plans/core/compiler.md`** — the `kind` schema (`EnvVarSpec`),
  `generation_policies` + `cicl/generate.py`, the `$[VAR]` fixed-inlining, the
  `config:` block wiring, `cicl/categories.py` (classifier + manifests +
  `minted_policies`), `envfile.py`, and validation rules 13/14/16/20. Update the
  key-types list, the substitution-grammar note, the validation section, and the
  "where to look" table. `example.env` is now a secrets-only manifest via
  `secret_manifest`.
- **`docex/plans/core/release_flow.md`** — the SSM push is now `aggregate_elastic`
  (TTE put-if-absent `SecureString`, secrets overwrite `SecureString`, config
  `String`); the fixed playbook renders `.env` from the aggregate + a host
  `tte.env` from the SSH-read authoritative store; the migrate step reads the
  host `.env` a prior release rendered. Update the flow prose + the "where to
  look" tables (aggregation entry points, `SSHClient.capture`,
  `ssm_get_parameter`).
- **`docex/plans/core/masterplan.md`** — add `secrets` + `config` to the
  subcommand surface table; note the aggregate/tte/config paths in the
  filesystem surface; note the shim's conditional `-it`.
- **`upgrades/upgrade_1.5.0.md`** (new) — `severity: minor`, `kind: incremental`,
  `scope: [machine, project]`. An existing project repins to 1.5.0, splits its
  `<env>.env`, adds `infra/{tte,config}/`, recompiles, redeploys. **Not a
  rebuild:** the existing TTE credential is preserved (elastic SSM / fixed host
  `tte.env` are read put-if-absent), so no infra teardown and no DB lockout.
- **`CHANGELOG.md`** — a `## [1.5.0]` entry (envmageddon). Dated + the version
  artifacts (`docex/pyproject.toml`, `__init__.py`) bumped **at the cut**
  (`RELEASING.md`), not here — this run stops ready-to-cut.
- **`003_envmageddon/plan.md`** — status → implemented (pending cut).

## Split of work

The delicate, operator-facing pieces — `upgrade_1.5.0.md`, the `CHANGELOG` entry,
the campaign-status flip — are authored by the orchestrator (full campaign
context, migration-subtlety reasoning). The mechanical core-doc table/section
alignment (`compiler.md`, `release_flow.md`, `masterplan.md`) is delegated to a
sub-agent against a precise per-doc spec (see implementation.md), then reviewed.

## The deferred cleanups — status

- The `emit/secrets.py` `TELEMETRY_API_KEY` dedup (Mod 078 flag #1) was already
  resolved in Mod 083 (the `secret_manifest` refactor). No action.
- `docex.md § config` (Mod 084 flag) was added by the orchestrator in Mod 084.
- The parts-only-rule comment framing (Mod 077 flag) — a `compile.py` comment
  note that the guard now bites only runtime refs — folded into this mod's
  compiler.md pass if it still reads stale.

## Scope

**In:** the six artifacts above. **Out:** the version-artifact bump, `v1.5.0`
tag, image build, and smoke walk — all `RELEASING.md` cut steps (operator).

## Doctrine anchors
- `docex_process.md § Additional Artifacts` (the five-layer alignment discipline).
- `RELEASING.md` (what the cut does vs. what ready-to-cut leaves).
- `upgrades/README.md` (guide schema: version/severity/kind/scope + body sections).
