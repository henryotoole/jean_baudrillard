# Advance 008 — Fixed Smoke-Walk Mod 144 Evidence

Candidate: `docex:2.1.0` (advance-008 branch HEAD code; in-source version string still `2.0.1` by design).
Fixed project pinned `docex_version: "2.1.0"`, inner repo `main` @ `v0.0.21`.
Walk date: 2026-08-24. Deploy target: dev machine (single-machine fixed).

## The Mod 144 fix under test

The fixed release playbook now **pulls without starting**, so migration runs
**before** the app stack comes up. Confirmed in the emitted
`infra/output/{stage,prod}/playbook.yml`, task order:

1. `Pull all images` — `community.docker.docker_compose_v2_pull` with `policy: always`
   (pull only, no start). **Previously** this was `docker_compose_v2` with
   `state: present`, which brought the stack UP before migration.
2. `Run migrations for api` — `docker compose run --rm ...-api-exec /service/migrate.sh`
3. `Bring up the stack` — `docker_compose_v2` with `state: present`

Diff vs. the previously-committed output (pre-Mod-144):
```
-      community.docker.docker_compose_v2:
+      community.docker.docker_compose_v2_pull:
         project_src: "{{ deploy_root }}"
         project_name: "docex-smoke-fixed-prod"
-        pull: always
-        state: present
+        policy: always
```

## Gate assertion: migration completes BEFORE app containers start

### STAGE (exact, from `docker events` on the `--rm` migrate exec)

| Event | Time (UTC) |
| ----- | ---------- |
| appdb (backing) StartedAt | 15:53:07.581 |
| migrate exec created | 15:53:19 |
| migrate exec started | 15:53:20 |
| **migrate exec died (migration COMPLETE)** | **15:53:20** |
| migrate exec destroyed | 15:53:21 |
| api-clock StartedAt | 15:53:26.076 |
| api-web StartedAt | 15:53:26.090 |
| api-worker StartedAt | 15:53:26.095 |

**ASSERT PASS:** migration completed at 15:53:20, ~6 s BEFORE all three app
containers started at 15:53:26.

### PROD (ordering by container StartedAt + playbook task sequence)

| Event | Time (UTC) |
| ----- | ---------- |
| appdb (backing) StartedAt | 15:56:19.996 |
| probe / events StartedAt | 15:56:19.990 / 15:56:20.003 |
| [migration ran here — ansible `Run migrations for api` = changed] | (15:56:20 – 15:56:40 window) |
| api-worker-2 StartedAt | 15:56:40.453 |
| api-clock StartedAt | 15:56:40.460 |
| api-web StartedAt | 15:56:40.476 |
| api-worker-1 StartedAt | 15:56:40.483 |

**ASSERT PASS:** a 20 s gap separates backing-service start (15:56:20) from
app-container start (15:56:40). Migration ran inside that window, and the
playbook runs `Run migrations for api` to completion (register result, no
failure) strictly before `Bring up the stack`. The exact migrate-exec `die`
timestamp had rolled off the docker daemon's event buffer by capture time, but
the ordering is fixed by the task sequence and corroborated by the gap and by
the clean clock first-fire below.

## Gate assertion: clock's first fire raises NO UndefinedTable

On a first release the clock's heartbeat must enqueue against an
already-migrated schema. If migration ran after app-up (the old bug), the
clock's first fire would throw `UndefinedTable`.

### STAGE clock (`docker logs ...-stage-api-clock`)
```
15:53:33 clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: heartbeat, prune_pings
15:53:33 clock: starting loop (tick=5.0s, tick file=/tmp/clock.tick); listens on nothing
15:54:03 jobs: 'heartbeat' fired
15:54:03 jobs: 'heartbeat' deferred as job a8710857-b476-497d-8850-522a992c2a40
```
Grep for `UndefinedTable|does not exist|relation`: **NONE (clean).**

### PROD clock (`docker logs ...-prod-api-clock`)
```
15:56:49 clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: heartbeat, prune_pings
15:56:49 clock: starting loop (tick=5.0s, tick file=/tmp/clock.tick); listens on nothing
15:57:04 jobs: 'heartbeat' fired
15:57:04 jobs: 'heartbeat' deferred as job 5bd96087-2593-48dd-96c8-b99d08c850ad
```
Grep for `UndefinedTable|does not exist|relation`: **NONE (clean).**
Clock started 15:56:40; first fire 15:57:04 enqueued cleanly against a migrated
schema. **ASSERT PASS** (both envs).

## Corroborating prod checks

- Three `/health` URLs all 200 with `{"version":"0.0.21"}`:
  `api-web.prod.…`, `prod.…` (bare-env), `docex-smoke-fixed.luxrnd.tech` (bare-project).
- Replica unroll: `api-worker-1` and `api-worker-2` both present, each with an
  otelcol sidecar; both carry the shared network alias
  `docex-smoke-fixed-prod-api-worker` on `...-prod-internal`.
- All 4 core probes `healthy` (api-web, api-worker-1, api-worker-2, api-clock).
- `POST /pings {"payload":"walk-ping"}` → 201; `{"message":...}` → 422.
  DB: `pings` row `walk-ping` has `processed_at` non-NULL (a worker replica processed it).
- defer→drain: worker-2 logged `'heartbeat' performed (job 5bd96087-… result 0)` —
  same uuid the clock deferred. DB `jobs` row `5bd96087-…`: `finished_at` non-NULL, `error` NULL.

## Mod 143 (ACME) — cert issuance clean

- stage: `api-web.stage.docex-smoke-fixed.luxrnd.tech` issued by Let's Encrypt (CN=YR2).
- prod:  `api-web.prod.docex-smoke-fixed.luxrnd.tech` issued by Let's Encrypt (CN=YR2),
  valid Aug 24 – Nov 22 2026.
- registry-traefik (constrained with `docex.project=registry`) did not poach the
  smoke project's ACME challenges. Path clear. (traefik image: `traefik:v3.6`.)

## Walk step exit codes

| Step | Result |
| ---- | ------ |
| compile | exit 0 (16 files, 4 envs) |
| projinfra up development / production | exit 0 |
| containerize | exit 0 — one repo `registry.luxrnd.tech/docex_smoke_fixed/api:0.0.21` |
| release stage | exit 0 |
| stagetest | exit 0 — orchestrator pre-step: 3 core services / 3 instances healthy on 0.0.21; 5 tester probes passed |
| release prod | exit 0 |

**VERDICT: Mod 144 gate PASS on both stage and prod. Clock first-fire clean (no
UndefinedTable) on both. All C steps exit 0.**
