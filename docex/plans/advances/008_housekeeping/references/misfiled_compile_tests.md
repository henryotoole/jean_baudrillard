# A collection hole hides 60 fast tests between the two standard invocations

`tests/integration/test_compile.py` holds 61 test functions, of which exactly one
carries `@pytest.mark.integration` (no file-level `pytestmark`). The other 60 are
fast, hermetic, in-process compile tests — no docker, no AWS, no network — sitting
in a directory named `integration`.

With `pyproject.toml` set to `addopts = "-m 'not integration'"`, the two
conventional invocations each miss those 60:

- `pytest tests/unit` — collects `tests/unit/` only; wrong directory.
- `pytest tests -m integration` — collects the marked tests only; they carry no
  marker.

So the 60 are visible only from `pytest tests`. The directory name says
"integration", the marker says otherwise, and the gap is invisible from both
standard sides — which is how red tests in this file went unnoticed across two
advances. The defect is not the misfiling; it is that a bucket exists that
neither standard invocation collects.

## The durable fix — a guard, not a move

Assert in CI that the buckets partition the suite:

```
collected(tests/unit) + collected(-m integration) == collected(tests)
```

This makes any future hole fail loudly regardless of where a test lives, which is
the property the relocate/re-mark options below are actually trying to buy. Just
moving today's 60 fixes this instance and leaves the instrument able to reopen
the hole the next time someone adds a bucket.

## Make the directory honest — relocate (decided at plan review)

**Relocate the 60 to `tests/unit/`**, alongside the guard. They belong there by
every property that matters — fast, hermetic, no real boundary crossed. Split the
file into `tests/unit/test_compile.py` (60) and whatever the one
genuinely-integration test needs. This makes the directory name true, chosen over
re-marking them in place (a distinct `compile` marker), which would leave them in
the misleadingly-named `integration/` dir.

## Two operational facts to keep

- **`pytest tests -m integration` must run alone.** Run concurrently with other
  pytest processes it produces convincing false-positive docker failures
  (`test_migrate_real`, `test_migrate_cold_stack`, `test_up_down_real`,
  `test_test_real`, `test_build_real` — docker DNS failures resolving
  `sample-dev-appdb`, unset `POSTGRES_PASSWORD`); run alone at the same commit,
  all pass. The integration tests bring up real compose stacks with fixed project
  names and contend for docker's network state — not parallel-safe against
  themselves.
- **The default full suite is `pytest tests`.**
