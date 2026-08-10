# Four `doctrine_excerpts/` entries are stale from releases nobody swept

## Summary

Mod 131's completeness pass over all eighteen excerpts — the second pass
[`docex_process.md § Additional Artifacts`](../../core/docex_process.md#additional-artifacts)
now mandates, reading every entry that names a **set** and asking whether the set is
still complete — surfaced four entries that are wrong for reasons **unrelated to
advance 006**. Each is stale from an earlier release that never swept this artifact.

Verified against the doctrine, not inferred. Ordered by how badly a reader is misled.

### 1. `secrets.md` describes a file `docex` no longer creates — **worst of the four**

The entry's tree shows:

```
example.env       # auto-emitted by `docex compile`; committed
```

and a paragraph explains the workflow: *"The compiler reads each backing service's
transfer-table `env:` block and emits `example.env` with one section per service
listing every required key. The operator copies it to `<env>.env` and fills in real
values per environment."*

**Mod 092 removed that emit.** Nothing writes `example.env`; the key set is derived
on demand by `docex secrets scaffold <env>` / `status <env>`. So `docex why secrets`
currently tells an operator to look for a file that will never appear, and to perform
a copy-and-fill workflow that no longer exists. Every other artifact — `cicl.md`,
`configurable.md`, `PRE_CUT_CHECKLIST.md` A.8 — has the current model; this one did
not move.

Also missing: the entry predates the **three-category** configurable model entirely.
It does not mention `infra/config/` or `infra/tte/`, so a reader learns that all
per-deploy values are secrets — which is the distinction
[`configurable.md`](../../../../doctrine/infrastructure/configurable.md) exists to
draw, and the reason `POSTGRES_PASSWORD` is a minted TTE value rather than a secret.

### 2. `dns.md`'s subdomain scheme is from before `apex_domain`

Three separate errors in one small table:

| Claim | Reality |
| --- | --- |
| *"a single `domain:` field in `infra.yml`"* | The field is **`apex_domain:`**, and it holds a bare apex (`example.com`) with no project segment. |
| `dev → dev.<domain>`, `prod → www.<domain>` | [`cicl.md § Domain`](../../../../doctrine/infrastructure/cicl.md) fixes `<codebase>-<service>.<env>.<project_name>.<apex_domain>` — so `api-web.dev.myproject.example.com`. The **project segment is missing entirely**, the core-service segment is missing, and `prod` takes `prod.`, never `www.`. |
| *"Apex (`<domain>` itself) is never served"* | The **bare project name** routes to `prod`'s `domain_default_service`. The smoke seeds rely on this — `docex-smoke-fixed.luxrnd.tech` answers as prod's default, and `PRE_CUT_CHECKLIST.md` A.4.1 holds a standing A-record for exactly that. |

The whole point of the doctrine's hostname scheme is that *"any machinery with no
further context can determine the destination project name, environment, and
service"* from the domain alone. An excerpt that omits two of those three segments
teaches the reader that the property does not hold.

### 3. `registrar.md` carries the same stale list

Its fixed bullet routes `dev.<domain>`, `test.<domain>`, `stage.<domain>`,
`www.<domain>` to the host machine's IP — same missing project segment, same `www.`.
Fix the two together; they are one claim written twice.

### 4. `environment_config.md` names a retired command

*"The output is consumed by `docex up` (fixed dev loop)"* — the command is
**`docex envinfra up`**. A one-word fix, listed only because leaving it while fixing
the other three would be arbitrary.

## Why mod 131 did not fix these

Mod 131's territory was an **alignment sweep**: replacing statements that went false
during advance 006. It did fix, in the same pass, every defect it could correct with
a verifiable clause — the dead citation in `service_discovery.md`, the missing shim
in `codebase.md`, and the inverted traefik topology across `reverse_proxy.md`,
`cert_manager.md`, `host_machine.md`, and `network_web.md`.

These four are different in kind. `secrets.md` needs a **rewritten section** plus new
coverage of a model it never had; `dns.md` needs its table rebuilt from
`cicl.md § Domain`. That is authorship, and authorship in an off-subject file is how
a sweep quietly becomes an advance. The operator's ruling at mod 131's design review
was to fix verifiable clauses and book anything needing prose.

## Why it matters

`docex why <resource>` exists so an operator does not have to read the doctrine to
orient. Two of these four actively mislead rather than merely under-inform:

- An operator following `why secrets` **waits for a file that is never emitted**, and
  the natural conclusion is that `compile` failed.
- An operator following `why dns` provisions **`dev.example.com` instead of
  `dev.myproject.example.com`**, which fails at `preinfra development` with *"dev host
  does not resolve in public DNS"* — a failure whose cause is nowhere near its symptom.

## Shape of the fix

One mod, four files, no code. Per file: read the current rule of record, rewrite the
stale claim, and leave a `Doctrine reference:` line pointing at it.

| File | Rule of record to read first |
| --- | --- |
| `secrets.md` | [`configurable.md`](../../../../doctrine/infrastructure/configurable.md) (the three categories) + [`specifics/config_and_secrets.md`](../../../../doctrine/infrastructure/specifics/config_and_secrets.md) |
| `dns.md` | [`cicl.md § Domain`](../../../../doctrine/infrastructure/cicl.md) |
| `registrar.md` | same as `dns.md` |
| `environment_config.md` | [`docex.md`](../../../../doctrine/infrastructure/docex.md) for the command name |

**Do the whole directory while you are in it.** Mod 131's pass covered the entries a
sweep would reach; a mod whose *subject* is this artifact should re-read all eighteen
against current doctrine rather than only these four, because the evidence below says
the base rate of staleness here is high.

## The standing lesson, and the number that makes the argument

Counting mod 131's fixes and these four, advance 006's sweep found defects in
**nine of eighteen** entries — and the vocabulary grep three mods relied on found
**one**. The inverted traefik topology had propagated to four files; the subdomain
scheme predates `apex_domain`; `example.env` outlived mod 092 by a full advance.
**None of those was caused by advance 006.**

The generalization is now stated in
[`docex_process.md`](../../core/docex_process.md#additional-artifacts): an artifact
with no automated consumer does not drift at the rate its subject changes — it drifts
at the rate nobody looks. So a sweep of `doctrine_excerpts/` should expect to find
damage from *other* releases, and a completeness pass is the only thing that finds it.

## Not blocking the 1.7.0 cut

None of the four is caused by this cut and none affects `docex`'s behavior — `why` is
a prose server. The cut is not gated on them. But they should not wait for the *next*
advance's sweep either, since the evidence is that the next sweep will be keyed on the
next advance's vocabulary and will find them exactly as often as this one's grep did.
