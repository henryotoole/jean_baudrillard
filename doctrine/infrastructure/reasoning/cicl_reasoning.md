---
stratum: conditional
---

# CICL

## Core Services

### Field Scoping

This is relevant both for existing fields and new ones which might be developed in the future. A field can either be scoped to the whole codebase (and so to all of its core services) or to one specific core service. The following heuristic determines how a service field gets scoped.

> A field belongs to the **codebase** iff its value is determined by the source code. It belongs to the **core service** iff its value is determined by the invocation.

| Codebase Scoped | Core Service Scoped |
| --------------- | ------------------- |
| `core_services:` | `role`, `command` |
| `secrets:`, `config:` | `resources`, `replicas` |
| migration ownership (`migrate.sh` runs once per codebase) | `networks`, `port` |
| `env:` (shared) | `depends_on`, `consumes` |
| | `env:` (merges over codebase-level) |
| | every role-specific field (`health_check_path`, `schedule`, …) |

Applying it: the *code* is what reads `STRIPE_API_KEY`, so `secrets:` is codebase-scoped. `migrations/` lives in the source tree, so migration ownership is too. **Role-specific fields follow `role`**, which is invocation-determined, so they are service-scoped by derivation — the table never needs revisiting when a role gains a field.

`env:` is the one field that straddles the principle, because some variables are code-determined (`DATABASE_HOST` — the code needs a database) and some are invocation-determined (a worker's concurrency knob). It is therefore valid at **both** levels, and a core service's effective environment is the codebase-level block merged under its own, the service-level block winning on a key collision. It is the only such exception, and it exists because the principle genuinely lands on both sides rather than as an oddity.