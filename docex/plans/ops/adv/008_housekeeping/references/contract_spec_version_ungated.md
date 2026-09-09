# Enforce contract spec-version minimums in `docex check`

`contracts.md § Standards` fixes a minimum specification version per contract
format — OpenAPI **3.2 or later**, AsyncAPI **3.0 or later**. Nothing in `docex`
reads it. The one gate that opens a contract body, `_gate_contract_health_path`
(`pipeline/check.py`), reads `paths` and nothing else; `_gate_contracts` reads
only filenames. So the declared spec version inside a contract is unconstrained:
a project can ship `openapi: "2.0"` and pass `docex check` green.

## Why the floors are load-bearing

Each minimum is required by a style the `api_styles` table promises, not a
formatting preference:

| Format | Minimum | What the minimum buys |
| --- | --- | --- |
| `openapi` | 3.2 | `itemSchema`, the only way to express the `stream` style. 3.1 buys top-level `webhooks` for `webhook`. |
| `asyncapi` | 3.0 | `reply`, the only way to express the `rpc` style; also lifts `operations` out of `channels`. |

A project on AsyncAPI 2.6 cannot write a conforming `rpc` contract; one on
OpenAPI 3.0 cannot write a conforming `stream` one. The floor is what makes the
table implementable.

## Changes to make

Add a third contract gate in `pipeline/check.py`, alongside `_gate_contracts`
and `_gate_contract_health_path`.

1. Add a `_FORMAT_MIN_SPEC_VERSION` map — `{"openapi": (3, 2), "asyncapi": (3, 0)}`
   — transcribed from `contracts.md § Standards`, carrying the same "this is the
   doctrine's table" comment `_FORMAT_EXTENSIONS` already carries.
2. Add `_gate_contract_spec_version(ctx, contracts, report)` that iterates the
   `list[ContractExpectation]` already produced by `_gate_contracts` (returned at
   `_gate_contracts(...)` and threaded into `_gate_contract_health_path`). For each
   contract whose `fmt` is in the map, read the version key the format declares in
   its own root (`openapi:` / `asyncapi:`), parse `major.minor`, and compare.
   Report per file, naming the declared and required versions.
3. Call it from the same block that already calls the other two contract gates,
   reusing the materialized list — no second directory walk.

## Constraints

- **Malformed or absent version key:** handle as `_gate_contract_health_path`
  handles unreadable YAML — report it once, and do not additionally report the
  consequence as a second defect.
- **`graphql` / `proto` have no version key** (SDL / IDL, not versioned
  documents), so the map covers two of four formats by design. Both are excluded
  by `IMPLEMENTED_CONTRACT_FORMATS` regardless.
