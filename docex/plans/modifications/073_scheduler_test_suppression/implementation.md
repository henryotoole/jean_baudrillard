# Mod 073 — Implementation steps

## 1. `src/docex/emit/compose.py` — suppress the Ofelia emit in `test`

In `emit_compose`, the scheduler emit loop (the "Mod 055: ofelia scheduler
containers + their rendered INI configs" block near the end of the function)
iterates every scheduler service and appends an Ofelia container + an
`ofelia_<svc>` config entry.

Guard that entire loop so it is skipped for the `test` env. Concretely, wrap the
`for name in sorted(compiled.services): ... if svc.role != "scheduler": continue`
scheduler loop with `if compiled.env != "test":`, mirroring the mod-054 web-label
exclusion already present in the same file (`if svc.web_hosts and compiled.env
!= "test":`).

Add a `# Mod 073:` comment explaining that `test` drops the scheduler trigger
(the only trigger `test` can carry, since `dev`/`test` are always fixed →
compose) so the job never fires in the test window, and pointing at
`scheduler.md § Caveats`.

The scheduler service block is already skipped in the main services loop for all
envs, and the otelcol-config gate already excludes scheduler services — neither
needs changing. Net effect in `test`: a scheduler service contributes nothing to
the compose file.

No other emit site changes: `emit/hcl.py` is never reached for `test`
(dev/test are always fixed), so its `scheduled_task` path needs no guard.

## 2. `tests/unit/test_scheduler.py` — add suppression tests

Add tests using the existing fixtures (`_FIXED`, `_ELASTIC`). Both fixtures'
`test` env compiles to compose (dev/test always fixed), so a helper that loads
the `test` compose works for both:

```python
def _test_compose(root: Path) -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / "test" / "docker-compose.yml").read_text()
    )
```

Tests to add:

- `test_test_env_omits_ofelia_fixed`: compile `_FIXED`; assert
  `sample-test-nightly_cleanup-scheduler` is NOT in `services`, and no
  `ofelia_nightly_cleanup` key exists under top-level `configs` (guard for
  `configs` possibly absent). Assert the ordinary web service
  `sample-test-api` IS still present (suppression is scheduler-scoped).
- `test_test_env_omits_ofelia_elastic`: same assertions against `_ELASTIC`'s
  `test` compose (its `test` env is fixed/compose too), proving suppression
  holds for an elastic-foundation project.
- `test_dev_still_emits_ofelia` (regression): compile `_FIXED`; assert
  `sample-dev-nightly_cleanup-scheduler` IS present in the `dev` compose and
  `ofelia_nightly_cleanup` IS in its `configs` — dev is unchanged.

Keep the existing elastic `stage`/`prod` HCL tests as the guard that the
EventBridge path is untouched.

## 3. Run tests

`cd docex && python -m pytest tests/unit/test_scheduler.py -q`, then the full
unit suite `python -m pytest -q -m "not integration"`. All green expected; the
change only removes emit for one env.
