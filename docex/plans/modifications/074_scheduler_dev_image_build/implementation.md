# Mod 074 — Implementation steps

## 1. `src/docex/orchestrate/_common.py`

Add `scheduler_services(ctx) -> list[str]`: the sorted simple names of every
core service whose `role == "scheduler"`. Mirrors `core_services`.

## 2. `src/docex/orchestrate/up.py`

- Import `scheduler_services`.
- Add `_ensure_scheduler_image(ctx, docker, svc)`: builds `core/<svc>` with
  `target="prod"` and tags it the dev-local ref from `_image_ref(...,
  env="dev", foundation="fixed")` (byte-identical to Ofelia's INI `image =`).
  Raise `BuildFailed` on non-zero. Do NOT tolerate a missing Dockerfile — a
  scheduler with no image is a real error.
- In `run_up`, the `env == "dev"` block:
  - Skip scheduler services in the `_ensure_initial_dev_build` loop.
  - After it, call `_ensure_scheduler_image` for each `scheduler_services(ctx)`.

Why `prod` stage: Ofelia launches the job via `docker run` with no compose
bind-mounts, so the job image must be self-contained (artifact baked in) — the
`dev` stage's bind-mount model can't apply. See overview.md.

## 3. `tests/unit/test_orchestrate_up.py`

Add a fixture-ctx that loads `sample_project_scheduler_fixed` (has a scheduler
`nightly_cleanup`, project `sample` v`0.1.0`) and a test:

- `run_up(dev)` with `fake_docker` issues a `build_image` call with
  `target="prod"` and `tag="sample/nightly_cleanup:0.1.0"`.
- No `build_image` with `target="build"` is issued for `nightly_cleanup`
  (the scheduler is skipped in the initial-dev-build path).

Load the fixture the same way `sample_ctx` does (copytree into tmp_path, drop
`infra/output/`).

## 4. Run tests

`python3 -m pytest tests/unit/test_orchestrate_up.py -q`, then the full unit
suite.
