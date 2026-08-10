# Contract spec-version minimums are stated by doctrine and read by nothing

## Summary

[`contracts.md § Standards`](../../../../doctrine/infrastructure/contracts.md#standards)
fixes a **minimum specification version per contract format** — OpenAPI **3.2 or
later**, AsyncAPI **3.0 or later**. `docex` never reads it. `_parse_contract_filename`
keys on the *format segment of the filename*, and `_gate_contract_health_path` is the
only gate that opens a contract at all, reading `paths` and nothing else. So the
declared spec version inside a contract document is unconstrained: a project may ship
`openapi: "2.0"` and pass `docex check` green forever.

Raised by mod 129 (advance 006), which found **both seed projects in violation** —
`openapi: "3.0.3"` and `asyncapi: "2.6.0"` — and fixed the seeds. It did **not** build
the gate: mod 126 owned the contract gate and was closed, and reopening a closed mod's
territory for an unplanned check is how a scope holds until it doesn't.

## Why this one is worse than an ordinary ungated rule

Most ungated doctrine prose is at least *visible* in the project it governs. This one
had survived every green smoke walk **inside the doctrine's own worked examples** — the
two trees downstream projects copy from and the two trees the pre-cut walk exercises end
to end. The seeds were the last place the violation should have been able to hide, and
they are exactly where it hid, because nothing anywhere compares the number in the
document against the number in the doctrine.

This is advance 005's recurring defect in yet another costume: *something that could not
have detected the failure reported success.*

## Why the versions matter rather than being pedantry

Not a formatting preference — each minimum is load-bearing for a style the table
promises:

| Format | Minimum | What the minimum buys |
| --- | --- | --- |
| `openapi` | 3.2 | `itemSchema`, which is how the `stream` style is expressed at all. 3.1 buys top-level `webhooks` for the `webhook` style. |
| `asyncapi` | 3.0 | `reply`, which is how the `rpc` style is expressed at all. 3.0 also lifts `operations` out of `channels`. |

So a project on AsyncAPI 2.6 cannot write a conforming `rpc` contract, and a project on
OpenAPI 3.0 cannot write a conforming `stream` one. The version floor is what makes the
`api_styles` table implementable. Mod 129 hit this directly: the seeds' AsyncAPI bump
was *required* by the worker's new `rpc` surface independently of the doctrine
violation, which is a small piece of evidence that the floors are chosen rather than
decorative.

## Shape of the fix

Small, and it belongs in `pipeline/check.py` beside the gate that already parses these
documents.

1. A `_FORMAT_MIN_SPEC_VERSION` map — `{"openapi": (3, 2), "asyncapi": (3, 0)}` —
   transcribed from `contracts.md § Standards` with the same "this is the doctrine's
   table" comment `_FORMAT_EXTENSIONS` carries.
2. Read the version key each format declares in its own root (`openapi:` / `asyncapi:`),
   parse `major.minor`, compare.
3. Report per contract file, naming the declared and required versions.

Open questions for whoever takes it:

- **Its own gate, or an arm of `contracts_exist`?** A separate gate reports more
  legibly; an arm avoids opening every contract twice. `_gate_contract_health_path`
  already reads them, but only the `openapi` ones — so neither existing gate covers the
  whole set.
- **What about a malformed or absent version key?** Consistent with
  `_gate_contract_health_path`'s handling of unreadable YAML: report it once, and do not
  additionally report the consequence as a second defect.
- **`graphql` / `proto` have no version key at all** (they are SDL and IDL, not
  versioned documents), so the map covers two of four formats and must not be read as
  incomplete. Both are `IMPLEMENTED_CONTRACT_FORMATS`-excluded anyway.

## Not blocking

Nothing is broken today. Both seeds now conform, so the pre-cut walk is not exposed, and
the gap costs a downstream project only a contract that claims a version it does not
need. The argument for closing it is that the doctrine states a rule it cannot enforce
in the one artifact class it enforces most rules on.
