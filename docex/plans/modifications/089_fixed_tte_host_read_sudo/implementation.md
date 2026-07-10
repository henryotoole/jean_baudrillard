# Mod 089 — Implementation steps

Docex project root: `~/.claude/jean_baudrillard/docex`.

## 1. Fix the host TTE read

File: `src/docex/orchestrate/aggregate.py`, `ensure_tte_fixed`.

Change the capture command to read the root-owned host store via `sudo`:

```python
# before
rc, out = ssh.capture(host, key, f"cat {remote} 2>/dev/null || true")
# after
rc, out = ssh.capture(host, key, f"sudo cat {remote} 2>/dev/null || true")
```

Update the adjacent comment to explain WHY sudo: the playbook renders `tte.env`
`root:root 0600` (become=root), so the `deploy` SSH user must `sudo` to read it;
reading without sudo returns "Permission denied" (masked by `2>/dev/null`) →
empty → a false re-mint that clobbers the live DB credential (the exact lockout
the authoritative-store rule prevents). `deploy` has passwordless sudo per
release_mechanism.md. Keep the existing `if rc == 255: raise` SSH-unreachable
handling.

## 2. Test guard

File: `tests/unit/test_aggregate.py`.

The module-local `_StubSSH.capture` already records the command in `calls`. Add
(or extend) a test asserting the fixed TTE read is performed **with sudo**, so a
regression that drops `sudo` is caught:

- `test_ensure_tte_fixed_reads_host_store_with_sudo`: call `ensure_tte_fixed`,
  then assert some recorded `capture` call's command string contains
  `sudo cat` and the `tte.env` remote path. (Mirror the existing
  `test_ensure_tte_fixed_mints_when_host_store_empty` setup.)

Keep the existing tests passing (the command still contains `tte.env`; the
`preserves_host_value_no_remint` test is unaffected since the stub returns the
canned value regardless of sudo).

## 3. Verify

From `~/.claude/jean_baudrillard/docex`:

```
python -m pytest tests/unit/test_aggregate.py -q
python -m pytest -q       # full unit suite green; do NOT run -m integration
```

Do NOT touch version artifacts, CHANGELOG, doctrine, or other core docs. Do NOT
git commit (the driver commits).

## Acceptance

- `ensure_tte_fixed` reads the host store with `sudo cat`.
- New test asserts the sudo read; full unit suite green.
- (Walk-level, driver-verified) a second fixed prod release reuses the host TTE
  value with no re-mint and no migration auth failure.
