# Mod 069 — Implementation steps

Bring docex code into alignment with the already-applied doctrine
changes for naming-policy `overflow`. All paths are relative to the
docex project root (`~/.claude/jean_baudrillard/docex`).

## 1. `src/docex/naming.py` — add the `overflow` field + behavior

1. Add `"overflow"` to `_ALLOWED_POLICY_KEYS`.
2. Add `overflow: str` to the `NamingPolicy` dataclass (values:
   `"error"` | `"hash_truncate"`).
3. In `parse_policies`, read `overflow = body.get("overflow", "error")`,
   validate it is one of `("error", "hash_truncate")` (raise
   `TransferTableError` with the same message shape as the `separator`/
   `case` checks otherwise), and pass it to the `NamingPolicy(...)`
   constructor.
4. In `apply_policy`, replace the `max_len` overflow branch:
   - When `policy.max_len is not None and len(out) > policy.max_len`:
     - If `policy.overflow == "hash_truncate"`:
       - `import hashlib` (top of module).
       - `h = hashlib.sha256(name.encode()).hexdigest()[:6]` — hash the
         **`name`** argument (the full internal underscore-joined form),
         *not* `out`.
       - `keep = policy.max_len - len(h) - 1` (the `-1` is the joining
         hyphen).
       - `prefix = out[:keep].rstrip("-")` (strip trailing hyphens so we
         never emit `foo--<hash>`).
       - `out = f"{prefix}-{h}"`.
       - Return `out` (it now fits `max_len`).
     - Else (`"error"`): raise the existing `TransferTableError`
       unchanged.
   - Keep the existing behavior identical when the name is within
     `max_len`.
   - Update the `apply_policy` docstring to mention the `hash_truncate`
     path (currently it says overflow always raises).

Note: the separator translation and case-lowering happen *before* the
overflow handling, exactly as today — only the final length branch
changes.

## 2. `tables/naming_policies.yml` — opt the `alb` policy in

Add `overflow: hash_truncate` to the `alb` policy block (leave
`separator: hyphen`, `case: any`, `max_len: 32` as-is). Do **not** add
`overflow` to any other policy — they inherit the `error` default.

## 3. `src/docex/emit/hcl.py::render_target_group` — add the tag block

The function currently emits `aws_lb_target_group` with no `tags`. Add
the standard envinfra tag block immediately before the closing `}` of
the `aws_lb_target_group` resource (i.e. after the `health_check` block,
before `out.append("}")`).

Build the tags via `standard_tags` (already imported at the top of
`hcl.py` as `from docex.emit.tags import render_hcl_tags, standard_tags`):

```python
out.append(render_hcl_tags(standard_tags(
    "environment",
    shape_name="core_service",
    descriptor="ALB-TG",
    project=ctx.project,
    env=ctx.env,
    service=svc.name,
    role=svc.role,
)))
```

Place this on the target-group resource only — **not** on the
`aws_lb_listener_rule` (listener rules don't take tags and the ALB-only
branch stays as-is). Target groups are only emitted for web-network core
services, so `shape_name="core_service"` is always correct here.

## 4. Tests

### `tests/unit/` — naming policy overflow

Add to the existing naming-policy test module (find it under
`tests/unit/` — likely `test_naming.py`; if absent, create
`test_naming_overflow.py`):

- `hash_truncate` fits: a name that overflows `max_len=32` under a
  hyphen policy with `overflow: hash_truncate` returns a string of
  length ≤ 32, ending in `-` + 6 hex chars.
- Determinism: same input → same output across two calls.
- Distinct inputs sharing a truncated prefix produce **different**
  outputs (the hash differs). Use two long names identical in their
  first 25 chars but differing later.
- No trailing double-hyphen: assert the result does not contain `--`.
- `error` default unchanged: a policy with no `overflow` (or
  `overflow: error`) still raises `TransferTableError` on overflow.
- Within-limit names are returned untouched regardless of `overflow`.
- `parse_policies` rejects an unknown `overflow` value with
  `TransferTableError`, and accepts `error`/`hash_truncate`.

### emit test — target-group name + tags

Find the existing target-group / ALB emit test (search
`tests/` for `render_target_group` or `aws_lb_target_group`). Add/extend:

- A long-project-name compile no longer raises and the emitted
  `aws_lb_target_group` `name` is ≤ 32 and ends with a 6-hex-char hash
  suffix.
- The emitted `aws_lb_target_group` now contains a `tags = { ... }`
  block carrying `Name = "<project>_<env>_<service>"`,
  `descriptor = "ALB-TG"`, `infra_tier = "environment"`.
- A short-project-name target group still emits the plain
  `<project>-<env>-<service>-tg` name (no hash), proving no regression.

## 5. Run the suite

From the docex root, run the unit + emit tests (the project's standard
`pytest` invocation; integration/`-m integration` tests are not needed
for this mod — no real boundary is crossed). All must pass.

## Contracts

No core-service contract changes — this is compiler/emit-internal.
