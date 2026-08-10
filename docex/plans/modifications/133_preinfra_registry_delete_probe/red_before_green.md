# Mod 133 — red before green

Evidence for design Part 5's standing requirement: the honest failure and
three can't-answer modes, each observed failing **before** the verdict
mapping existed.

## What was in place, and what was not

At the moment of this run, everything except the verdict logic was built:
`registry/client.py`, `registry/urllib_client.py`, `FakeRegistryClient`,
`run_preinfra`'s `registry=` parameter, the `declined` list, and the
`Declined` output block. Only `_check_registry_manifest_delete` was
missing its ladder — it stood as:

```python
def _check_registry_manifest_delete(ctx, registry):
    """STUB — the verdict mapping does not exist yet (red-before-green)."""
    host = ctx.infra.container_registry
    registry.delete_manifest(host, _DELETE_PROBE_REPOSITORY, _DELETE_PROBE_DIGEST)
    return [], []
```

That is deliberately the shape design Part 5 asks the arms to be run
against: *a verdict function that has not yet learned to distinguish
them.* The probe fires and the observation is discarded.

## The load-bearing detail in the output below

**All four arms produce byte-identical output** —
`preinfra development side: all checks passed.` — from four materially
different observations:

| Arm | Scripted observation |
| --- | --- |
| 1 | `status=405, error_code="UNSUPPORTED"` (the registry refusing a real delete) |
| 2 | `status=401` (auth middleware ahead of the handler) |
| 3 | `failure="no_credential"` |
| 4 | `status=405, error_code=None` (a proxy rejecting the method) |

A delete-disabled registry, a rejected credential, an absent credential,
and a proxy that blocks DELETE were all read as a pass. That is the exact
defect class this advance is under orders not to ship, and it is why the
distinction had to be *demonstrated* rather than asserted: arm 1 and arm 4
differ only in a field the stub never reads, and arm 2 is the mode that
concealed the original defect for several releases.

## The run

```
$ .venv/bin/python -m pytest tests/unit/test_pipeline_preinfra.py \
    -k "registry_delete_disabled or registry_401 or registry_no_credential or registry_405_without_code" \
    -v --tb=line -p no:randomly

============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0 -- /home/ubuntu/.claude/jean_baudrillard/docex/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/ubuntu/.claude/jean_baudrillard/docex
configfile: pyproject.toml
collecting ... collected 29 items / 25 deselected / 4 selected

tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_delete_disabled_fails FAILED [ 25%]
tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_401_declines_without_verdict FAILED [ 50%]
tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_no_credential_declines FAILED [ 75%]
tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_405_without_code_declines FAILED [100%]

=================================== FAILURES ===================================
E   assert 0 == 1
---------------------------- Captured stderr setup -----------------------------
warning: project pins docex_version '0.5.0', but this is docex 1.7.0. (this is a
warning in Phase 1; will be enforced later.)
----------------------------- Captured stdout call -----------------------------
preinfra development side: all checks passed.
/home/ubuntu/.claude/jean_baudrillard/docex/tests/unit/test_pipeline_preinfra.py:287: assert 0 == 1
E   AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
---------------------------- Captured stderr setup -----------------------------
warning: project pins docex_version '0.5.0', but this is docex 1.7.0. (this is a
warning in Phase 1; will be enforced later.)
/home/ubuntu/.claude/jean_baudrillard/docex/tests/unit/test_pipeline_preinfra.py:312: AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
E   AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
---------------------------- Captured stderr setup -----------------------------
warning: project pins docex_version '0.5.0', but this is docex 1.7.0. (this is a
warning in Phase 1; will be enforced later.)
/home/ubuntu/.claude/jean_baudrillard/docex/tests/unit/test_pipeline_preinfra.py:346: AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
E   AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
---------------------------- Captured stderr setup -----------------------------
warning: project pins docex_version '0.5.0', but this is docex 1.7.0. (this is a
warning in Phase 1; will be enforced later.)
/home/ubuntu/.claude/jean_baudrillard/docex/tests/unit/test_pipeline_preinfra.py:369: AssertionError: assert 'Declined' in 'preinfra development side: all checks passed.\n'
=========================== short test summary info ============================
FAILED tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_delete_disabled_fails
FAILED tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_401_declines_without_verdict
FAILED tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_no_credential_declines
FAILED tests/unit/test_pipeline_preinfra.py::test_preinfra_dev_registry_405_without_code_declines
======================= 4 failed, 25 deselected in 0.83s =======================
```

Arm 1 fails on the exit code (`assert 0 == 1`) — the stub could not
produce the finding. Arms 2–4 fail on the absent `Declined` block, each
against the same `all checks passed` string, which is the demonstration
that no distinction existed to be relied on.

The ladder in `_check_registry_manifest_delete` was written after this
run; all four then pass, and the full unit-test coverage of design Part
3's remaining enumeration was added alongside.
