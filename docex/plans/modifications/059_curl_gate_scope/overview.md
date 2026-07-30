# Mod 059 — curl gate scope fix

Sixth mod of the `001_skill_update` advance. Closes the planner's "Health Checks
And Curl — double check that `docex check` actually checks whether curl is
installed on images which need it."

## Verification result

The gate exists and works for the common case: `_gate_healthcheck_tooling`
(`pipeline/check.py`, mod 051 Gap I) builds each qualifying service's `prod`
image and runs `command -v curl`; it's wired into `run_check`, a failure fails
the run, and an integration test covers both curl-present (pass) and curl-less
(fail) images. The `getattr(svc, "health_check_path", …)` detection was confirmed
correct (pydantic `extra="allow"` surfaces the role field as an attribute).

## The bug found

The gate's scope is **narrower than the doctrine**. It qualifies services on
`on_web AND declares_hc`, but `infrastructure.md` says "**Any** core service that
declares a `health_check_path` must carry `curl`." Only `role: web` services can
declare `health_check_path`, but a web-role service may legitimately sit on a
non-`web` network (e.g. `networks: [internal]`) — nothing forbids it.

Verified by compiling such a service: it gets `web_hosts == []` (so the gate's
`on_web` test is false and **skips it**) yet its compiled body carries the curl
healthcheck `["CMD","curl","-f","http://localhost:8080/health"]`. So a service
that genuinely needs curl escapes the gate. The consequence isn't only a dropped
Traefik route (the original mod-051 framing) — a curl-less healthcheck marks the
container `unhealthy` regardless of web membership, which also breaks any
`depends_on: { condition: service_healthy }` waiting on it.

## Fix (docex only; no doctrine change)

The doctrine (`infrastructure.md`) is already correct — the code was too narrow.
Drop the `on_web` filter: the gate now checks **every** core service that
declares `health_check_path`, matching the doctrine and the actual emit behavior
(the curl healthcheck is emitted whenever the field is set, independent of
network). Docstring updated to explain the curl need follows `health_check_path`,
not web membership.

## Artifacts touched

- `src/docex/pipeline/check.py` — `_gate_healthcheck_tooling` qualifying
  condition + docstring.
- `tests/**` — a unit test (fake DockerClient) asserting a non-`web`
  `health_check_path` service is probed by the gate, plus an integration variant
  if cheap. The existing integration tests (curl-present / curl-less) stay green.
