# Mod 089 — Fixed TTE host-store read must use sudo (DB-lockout fix)

## Problem (critical)

On a fixed-foundation project, the **second** `docex release stage`/`prod` of an
env locks the running containers out of their own database. The migration fails:

```
Run migrations for web → pq: password authentication failed for user "appuser"
```

Surfaced by the 1.5.0 pre-cut fixed smoke walk (PRE_CUT_CHECKLIST C.10): first
prod release (0.0.11) succeeded; the second (0.0.12) re-minted the postgres
password and diverged from the persisted database volume.

## Root cause

`orchestrate/aggregate.py::ensure_tte_fixed` implements the doctrine's
authoritative-store rule (config_and_secrets.md § authoritative-store rule): the
**host** `/opt/<project>/<env>/tte.env` is authoritative; docex SSH-reads it and
re-mints only the minted keys that are **missing**, so a running DB's credential
is never clobbered.

But the read is:

```python
rc, out = ssh.capture(host, key, f"cat {remote} 2>/dev/null || true")
```

`ssh.capture` runs as the **`deploy`** user. The playbook renders `tte.env`
`root:root` mode `0600` (the play runs `become: true`). So `deploy`'s `cat` gets
**"Permission denied"**, which `2>/dev/null || true` swallows into an **empty**
read. docex concludes the store is absent and **re-mints every minted key on
every release** — clobbering the host store and diverging from the live
database's persisted credential. Postgres ignores `POSTGRES_PASSWORD` on an
existing data dir, so the DB keeps the *first* release's password while the new
`.env`/migration carry the re-minted one → authentication failure → lockout.

Unit tests never caught it: they mock `ssh.capture` to *return* the canned host
value, so the real-host permission mismatch is invisible. Only a live second
release exposes it — precisely what the smoke walk is for.

Pre-existing in the envmageddon advance (mod 081 introduced `ensure_tte_fixed`);
the doctrine's rule is correct, docex simply fails to read its own store.

## Design

Read the root-owned host store with `sudo`. The `deploy` user is required by the
doctrine to have passwordless sudo (release_mechanism.md § Fixed Foundation:
Ansible; PRE_CUT_CHECKLIST A.7) — the same privilege the playbook's `become:
true` relies on. Change the capture command to:

```python
rc, out = ssh.capture(host, key, f"sudo cat {remote} 2>/dev/null || true")
```

- **Present store** (steady state): `sudo cat` reads the real value → reused, no
  re-mint, no lockout.
- **Absent store** (first release): `sudo cat` of a missing file fails →
  `2>/dev/null || true` → empty → mint (correct, unchanged).
- **SSH unreachable**: `ssh.capture` returns 255 → existing `if rc == 255: raise`
  path is preserved.

`sudo` eliminates the permission-denied case that the `2>/dev/null` was masking,
so the mask is now benign (it only absorbs the intended absent-file case).

### Scope of impact

Only the **fixed** stage/prod path is affected:
- **Elastic** stage/prod reads SSM (`ensure_tte_elastic`) — no host file, no
  permission issue.
- **dev/test** reads the operator-owned local `infra/tte/<env>.env`
  (`ensure_tte`) — readable, no sudo needed.

So the fix is a single line in `ensure_tte_fixed`, plus its WHY comment.

## Doctrine / artifact alignment

- **Doctrine**: no change — config_and_secrets.md already prescribes the correct
  behavior; this is a docex conformance fix.
- **src** (`orchestrate/aggregate.py`) + **tests** (`tests/unit/test_aggregate.py`)
  as below.

## Non-goals

- Not changing the host store's ownership/mode (keeping it `root:root 0600` is
  correct; sudo is the right read path).
- Not hardening every masked-error path beyond this fix; the sudo read removes
  the permission-mask that caused the lockout.
