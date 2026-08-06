# Advance Brief: `docex preinfra` should probe registry manifest deletion

**Status: deferred to advance 006; not a 1.7.0 cut blocker.** Raised as the
follow-on half of mod 122's Finding 4 and ruled defer by the operator at that
mod's design review (Q2). Logged here so the ruling is not silently dropped
between advances — the doctrine half of Finding 4 landed in mod 122, this half
did not.

## The gap

[`./bin/docex preinfra development`](../../../doctrine/infrastructure/preinfra/container_registry.md#verification-by-docex-preinfra)
already verifies the registry's **credential** side: it checks that
`~/.docker/config.json` carries an entry for the registry on the hosts that push
and pull. It does **not** verify that the registry will accept a manifest
`DELETE`.

Every `fixed` project's `teardown.sh` depends on that capability. Without
`REGISTRY_STORAGE_DELETE_ENABLED: "true"` on the registry container, every
`DELETE /v2/<repo>/manifests/<digest>` returns `405 Method Not Allowed`, teardown
deletes nothing, and the project leaks one registry tag per release. Mod 122's
doctrine edit made the requirement *stated*
([`container_registry.md § Registry container`](../../../doctrine/infrastructure/preinfra/container_registry.md#registry-container));
it did not make it *checked*.

The absence is invisible until someone counts tags. On this machine the flag was
never set, so image deletion 405'd for every `fixed` project across several
releases — and the smoke project's own `verify_clean.sh` reported clean
throughout, because its registry query was unauthenticated and could not tell a
`401`/`405` from an empty registry. The two defects concealed each other. Mod 122
fixed the check; nothing yet fixes the *detection of the misconfiguration
itself*.

## The ruling, with reasoning

**Yes in principle.** `preinfra` exists to verify that prerequisite
infrastructure is in the form the project needs
([`infrastructure.md § Infrastructure Tiers`](../../../doctrine/infrastructure/infrastructure.md#infrastructure-tiers):
"`docex` can perform proactive checks on prerequisite infrastructure to check
whether or not it exists in the needed form"). Teardown provably depends on the
flag, and the flag is a property of a shared, machine-wide preinfra resource that
no single project controls. That is exactly the shape of thing a preinfra probe
is for.

**Not now.** It is `docex` code rather than a doctrine edit, so it needs its own
unit and integration tests; mod 122 was scoped to tests, two shell scripts, one
checklist and one doctrine file, and its verification budget was already spent on
a re-walk. It also sits between the 1.7.0 fixed walk and an elastic walk that was
blocked behind mod 122, and a `docex` change at that point would invalidate the
image both walks run against.

## Recommended shape

The probe is the same three calls mod 122 added to the doctrine as
[`§ Verifying Reachability` step 4](../../../doctrine/infrastructure/preinfra/container_registry.md#verifying-reachability):

1. Push (or reuse) a throwaway tag under `preinfra-smoke/`.
2. `HEAD` its manifest offering **both** `application/vnd.oci.image.index.v1+json`
   and `application/vnd.docker.distribution.manifest.v2+json`, and read
   `docker-content-digest`. An empty digest is itself a finding: buildx pushes an
   OCI index, so the narrower `Accept` resolves nothing.
3. `DELETE` the digest and require `202`. A `405` is the failure this probe
   exists to catch, and its resolution line should name
   `REGISTRY_STORAGE_DELETE_ENABLED` and the compose block that sets it.

**The design question a builder must answer.** A probe that *pushes an image* is
substantially heavier than everything else `preinfra development` does — the rest
is DNS resolution and file-presence checks, and this would pull, tag, push and
delete a layer over the network on every invocation. Two alternatives are worth
weighing:

- **Read the registry container's environment directly**
  (`docker inspect registry`). Cheap and exact, but only works when the registry
  runs on the same host as the command, which is true for the development side
  and false in general.
- **Probe only on demand** — a `--deep` flag, or fold it into
  `preinfra production` where the cost is amortised over a much rarer call.

Whichever is chosen, note that a `405` from a *real* delete is the only evidence
that is impossible to fake; the `docker inspect` route trusts the container's env
to reflect the running registry's behaviour.

## Reading

- [`container_registry.md § Verification by docex preinfra`](../../../doctrine/infrastructure/preinfra/container_registry.md#verification-by-docex-preinfra)
  — the existing probe this would extend, and the precedent for what a preinfra
  registry check looks like.
- [`container_registry.md § Garbage Collection`](../../../doctrine/infrastructure/preinfra/container_registry.md#garbage-collection)
  — the procedure whose first phase is impossible without the flag.
- [`container_registry.md § Verifying Reachability`](../../../doctrine/infrastructure/preinfra/container_registry.md#verifying-reachability)
  — step 4, the manual form of the probe recommended above.
- [`PRE_CUT_CHECKLIST § A.5`](../../test_projects/PRE_CUT_CHECKLIST.md) — the
  operator-side registry prerequisites the walk already asserts.
- [Mod 122 overview § Finding 4](./122_walk_findings/overview.md) — the finding
  as escalated, the drafted doctrine change (landed), and this follow-on (not).
