# docex test layout

## Unit tests (`tests/unit/`)

Fast, no external dependencies. The orchestrate-layer tests use the
`FakeDockerClient` fixture in `tests/conftest.py` to record/script
docker calls without spawning real subprocesses.

Run them:

```bash
pytest tests/unit/
# or simply
pytest    # default `addopts` skips integration tests
```

## Integration tests (`tests/integration/`)

Two categories:

1. **Compile/describe tests** — exercise the Phase 1 compiler end-to-end
   against the fixtures. No docker dependency. Always run.
2. **Real-docker tests** (`test_*_real.py`) — spin up real containers
   via the sample fixture and assert end-to-end behavior. Marked with
   `@pytest.mark.integration`; **skipped by default**.

Run the real-docker tests explicitly:

```bash
pytest -m integration
```

They will additionally self-skip if `docker info` fails at collection
time (see `tests/integration/conftest.py`).

## Fixtures (`tests/fixtures/`)

* `sample_project/` — fixed-foundation project with one core service
  (`api`) and one backing service (`database`). Phase 2 wired in real
  `core/api/` source so up/build/test/migrate have something to chew on.
* `sample_project_elastic/` — elastic project for the Phase 1 compiler
  tests. No `core/` tree because Phase 2 only exercises fixed envs.

The committed `infra/secrets/<env>.env` files in `sample_project/` are
**fixture-only placeholders**. Real projects must gitignore them; the
project README in the fixture spells this out.
