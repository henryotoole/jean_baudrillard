# Mod 074 — Build the dev scheduler job image

## Problem

A `scheduler` core service on fixed compiles to an Ofelia container that
launches the job as a **one-off `docker run`** of the service's image
(`<project>/<svc>:<version>` in dev, per `_image_ref`). But nothing ever builds
that image in `dev`:

- The compose services loop in `emit/compose.py` `continue`s past scheduler
  services (they never become a compose service), so `docker compose up --build`
  never builds them.
- `orchestrate/up.py`'s `_ensure_initial_dev_build` only populates the host
  `dist/` for bind-mounted dev services — irrelevant to a scheduler.

So `docex up dev` on a scheduler-bearing project leaves Ofelia referencing an
image that does not exist locally, and every fire fails with "No such image".
The fixed scheduler path has therefore never actually run end-to-end. (Elastic
is unaffected: stage/prod pull the registry image built by `containerize`.)

## Why the dev-stage bind-mount model doesn't work for a scheduler

Every long-running dev core service runs from the Dockerfile's **`dev` stage**,
which carries build tools and expects `src/`+`dist/` to be **bind-mounted** at
runtime (compose supplies the mounts). Ofelia launches the job with a bare
`docker run` over the docker socket — **no compose bind-mounts reach it**. A
`dev`-stage image run without its bind-mounts has an empty `/service/dist` and
the job command finds nothing to execute.

The job image must therefore be **self-contained** — the artifact baked in — which
is exactly what the Dockerfile's **`prod` stage** produces (`COPY --from=build
/service/dist`). This is the correct stage for a run-to-completion job that gets
no bind-mounts, and it is consistent with stage/prod, where the scheduler already
runs the registry image (also built from the `prod`-equivalent path).

## Change

In `orchestrate/up.py`, for the **`dev`** env only (dev is the only env where
`docex up` emits an Ofelia trigger — `test` now suppresses schedulers per mod
073; stage/prod go through `release`, not `up`):

1. **Skip schedulers in `_ensure_initial_dev_build`.** They aren't bind-mounted
   and never run as a compose service, so populating a host `dist/` for them is
   wasted work.
2. **Build each scheduler service's image from the `prod` stage** and tag it the
   dev-local ref (`<project>/<svc>:<version>`, via the same `_image_ref` the
   compiler uses so the tag is byte-identical to Ofelia's INI `image =`). Ofelia
   then finds the image and can launch the job.

## No doctrine change

`scheduler.md § Fixed Foundation` already states the image is "derived exactly as
for any core service: a local build tag in `dev`/`test`". *Which Dockerfile stage
docex builds that local tag from* is an implementation detail, not a doctrine
rule — so no doctrine edit is required. The rationale above lives here and in the
code comments.

## Scope / non-goals

- Not a change to compose emit (mod 073 already handles `test`; dev/stage/prod
  emit is unchanged).
- Not an elastic change (registry image already built by `containerize`).

## Verification

- Unit: `run_up(dev)` on a scheduler-bearing fixture issues a `build_image`
  with `target="prod"` and the dev-local tag, and does **not** run the
  initial-dev-build for the scheduler.
- Live: covered by the smoke-project bring-up (see the advance notes) — a real
  `docex up dev` builds the scheduler image and Ofelia fires the job.
