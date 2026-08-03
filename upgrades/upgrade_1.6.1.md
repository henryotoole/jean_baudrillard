---
version: "1.6.1"
severity: patch
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 1.6.1

A one-line compiler fix with a real behavioral consequence: **services attached
only to non-`web` networks now have internet egress.** The compiler had been
emitting every non-`web` env network with Docker's `internal: true`, which strips
the bridge's masquerade rule and denied all outbound access to any container
whose only attachment was such a network. See the
[1.6.1 CHANGELOG entry](../CHANGELOG.md) for the full description and the
measurements behind it.

No `infra.yml` change, no CICL change, no new field. The only action is repin,
recompile, and bring the env back up — but the bring-up **restarts containers**,
so read § Project upgrade before doing it to a live stage or prod.

## Machine sync

Run the **`doctrine-update`** skill (or by hand): `git pull` in
`~/.claude/jean_baudrillard`, then `bash setup.sh`. That lands:

- **`docex:1.6.1` is built.** `docex` code *did* change this release, so this is
  a real rebuild, not a version-only one.
- **`RESIDENT.md` is regenerated.** One resident-stratum file is unchanged in
  substance but `doctrine/infrastructure/specifics/networks.md` (conditional
  stratum) gained a sentence; expect no resident diff.
- **The shim is unchanged** from 1.6.0.

## Project upgrade

### 1. Repin

```bash
bash ~/.claude/jean_baudrillard/docex_install.sh .
```

Writes `docex_version: 1.6.1` into `project.yml`. Idempotent.

### 2. Recompile

```bash
./bin/docex compile
```

The only diff you should see in `infra/output/*/docker-compose.yml` is the
removal of `internal: true` from each non-`web` network block:

```diff
 networks:
   internal:
     name: myproject-dev-internal
-    internal: true
   web:
     name: myproject-dev-web
     external: true
```

If anything else moved, stop — that is not this release.

### 3. Bring the env up — **this restarts containers**

Compose reconciles the changed network config automatically; no manual
`docker network rm` is needed. But a Docker network's `internal` flag is
immutable after creation, so reconciliation means **remove and recreate**, and
compose must stop the attached containers to do it. Verified sequence on
`docex envinfra up <env>`:

```
Container myproject-dev-api-worker  Stopped
Network   myproject-dev-internal    Removed
Network   myproject-dev-internal    Creating
Network   myproject-dev-internal    Created
Container myproject-dev-api-worker  Starting
```

So:

- **`dev` / `test`** — `./bin/docex envinfra up <env>`. The restart is
  immaterial.
- **fixed `stage` / `prod`** — the release playbook's `docker compose up -d`
  performs the same reconciliation, which means **a brief interruption of every
  service on a non-`web` network**, not a rolling replacement. Treat this
  release as a maintenance window rather than an ordinary image-tag deploy. If
  that is unacceptable right now, staying on 1.6.0 is safe — nothing else in
  this release is load-bearing.
- **elastic `stage` / `prod`** — **nothing to do.** Env networks on elastic are
  security groups, and the elastic `internal` SG already carried allow-all
  egress; the bug was fixed-only. Repin and recompile for version hygiene; the
  emitted HCL does not change.

If network removal fails with a "has active endpoints" error, a container
outside the env's compose project is attached to it — not a shape the doctrine
emits. Find it with `docker network inspect <network>`, detach it, and re-run.

## Doctrine / behavior notes

**What this does not change.** A non-`web` network is still not reachable from
other docker networks, and still not reachable from the public internet — it
publishes no host ports. Those properties never came from the `internal` flag:
cross-network isolation comes from Docker's own inter-bridge isolation rules,
and the flag gave no protection against the host either, since the bridge
gateway sits in-subnet. The flag's *only* effect was the egress loss. Measured
on Engine 29.4.1:

| Property | `internal: true` | plain bridge (now) |
| --- | --- | --- |
| Egress to internet, incl. DNS | BLOCKED | OK |
| Reachable from another docker network | BLOCKED | BLOCKED |
| Reachable from the host by container IP | REACHABLE | REACHABLE |
| Reachable by container name, same network | OK | OK |

**Two things you may have been working around.** If your project carries either
of these hacks, you can now remove it:

1. A `worker` or `scheduler` process type given `networks: [web, internal]`
   purely so it could reach an external API. Drop `web` — and note that
   [rule 27](../doctrine/infrastructure/cicl.md#validation-rules) forbids `web`
   on those roles anyway, so if you had this, you had it on a `web`-role process
   type standing in for a worker.
2. Anything routing outbound calls through a service that happened to be on the
   `web` network.

**A telemetry break you may not have noticed.** On fixed `stage`/`prod`, the OTel
sidecar shares its partner's netns (`network_mode: service:<container>`), so a
`worker`/`scheduler` on `networks: [internal]` had a sidecar with **no route to
`OBSERVABILITY_BACKEND_URL`** — Class-1 telemetry silently dropped. It hid in
`dev`/`test` because the exporter there is `debug` (sidecar stdout). After this
upgrade, check your observability backend for signals from non-`web` process
types you had assumed were reporting.

**Egress-less networks remain deferred.** If you *wanted* the old behavior for a
particular network, there is currently no way to declare it. Per
[`networks.md § Egress`](../doctrine/infrastructure/specifics/networks.md#egress)
and [`infrastructure.md § Deferred`](../doctrine/infrastructure/infrastructure.md#deferred),
constraining egress per network is deferred; when it lands it will be a declared,
opt-in field with an elastic half, not a compose-flag side effect. Say so if you
need it.

## Verification

```bash
# 1. The flag is gone from every env's output.
grep -r "internal: true" infra/output/ && echo "STILL PRESENT — recompile" || echo "clean"

# 2. The live network is no longer internal.
docker network inspect <project>-<env>-internal -f '{{.Internal}}'   # want: false

# 3. A non-web-only container can actually get out.
docker exec <project>-<env>-<svc>-<proc> \
  sh -c 'wget -q -T3 -O- https://example.com >/dev/null && echo EGRESS_OK'
```

On elastic `stage`/`prod`, step 1 applies (dev/test output is compose on every
foundation); steps 2-3 have no elastic analog, and no SG change should appear in
`tofu plan`.
