# Mod 062 — EC2-traefik user_data HCL-escaping

## Problem

`reverse_proxy: ec2_traefik_eip` (and `_pip`) emit **invalid HCL** at the
project tier. `docex compile` succeeds, but `tofu init`/`validate` on
`infra/output/project/production/main.tf` fails:

```
Error: Extra characters after interpolation expression
  on main.tf ..., in resource "aws_instance" "project_traefik":
  ... awk -v v="${VOLUME_ID//-/}" ...
```

The EC2-traefik path (mod 044) was written but never exercised end-to-end —
every prior elastic smoke walk used the default `alb` reverse proxy. First
real use of the `ec2_traefik` variant surfaced the break.

## Root cause

The instance's `user_data` shell script is rendered from
`emit/templates/ec2_traefik_user_data.sh.j2` (Jinja fills `{{ project }}`,
`{{ traefik_acme_email }}`, etc.) and injected verbatim into
`emit/templates/project.tf.j2` inside an HCL heredoc:

```
user_data = <<-USER_DATA
{{ traefik_user_data }}
  USER_DATA
```

**HCL heredocs interpolate `${…}` and `%{…}`.** The rendered script is pure
bash — every `${…}` is a shell expansion (`${PROJECT}`, `${REGION}`,
`${VOLUME_ID}`, `${VOLUME_ID//-/}`, `${TRAEFIK_VERSION}`, `${DEVICE_NAME}`,
plus more inside the nested `<<EOF` config heredocs) and **none** are HCL
references. OpenTofu tries to parse `${VOLUME_ID//-/}` as an HCL expression
and fails. `${VOLUME_ID//-/}` is what trips the parser first, but all such
sequences collide.

Scope: **project tier only.** The env-tier `stage`/`prod` HCL validates clean
on both variants (verified). The bug is confined to the one heredoc.

Why nothing caught it: the mod-044 tests
(`tests/integration/test_compile.py`, the `test_mod044_*` battery) assert only
substring **presence** in the rendered text (`assert "..." in tf`). None ever
parse or `tofu validate` the emitted HCL, so structurally-invalid output
passed every test.

## Fix

Escape the two HCL interpolation triggers in the fully-rendered user_data
before it enters the heredoc, in `emit/hcl.py` immediately after the
`ud_tpl.render(...)` call:

```python
traefik_user_data = traefik_user_data.replace("${", "$${").replace("%{", "%%{")
```

OpenTofu un-escapes `$${`→`${` and `%%{`→`%{` when it evaluates the heredoc,
so the instance receives the exact intended bash script. The script's bare
`$(…)` / `$VAR` uses are untouched (HCL only interpolates `${` and `%{`), so
they reach the instance unchanged.

Verified: with this change, both `ec2_traefik_eip` and `ec2_traefik_pip`
compile and `tofu validate` clean at every tier (`project/production`,
`stage`, `prod`); the full existing suite (625 tests) still passes.

### Why targeted `${`/`%{`, not `$`→`$$`

`_hcl_value` (mod 026) escapes `$`→`$$` for **quoted-string** values — safe
there because those payloads (e.g. `OTEL_CONFIG_YAML`) only use `$` as part of
`${…}`. The traefik user_data contains bare command substitutions (`$(curl …)`,
`$(mktemp)`) and `$$`-based PID-safe temp handling that must survive
un-doubled. Doubling **all** dollars would corrupt the script. Only `${` and
`%{` are HCL triggers, so only those are escaped.

### Fix location

The escape lives in Python (`hcl.py`), where `traefik_user_data` is already
assembled, rather than as a Jinja filter in `project.tf.j2`. This keeps the
escaping close to the render, testable in isolation, and consistent with the
precedent that HCL-escaping is a Python concern (`_hcl_value`).

## No doctrine change

The doctrine (`projinfra/ec2_traefik.md`) describes the *behavior* — a
doctrine-managed user_data that attaches the ACME EBS volume, installs
traefik, wires the SSM config sync, etc. That behavior is unchanged; HCL
heredoc escaping is an emit-mechanics detail below the doctrine's abstraction
level. The doctrine already correctly describes what the instance does. No
doctrine prose is touched.

## Tests (close the gap)

Two regression tests, per the operator's decision:

1. **Unit assertion (default suite).** After compiling an `ec2_traefik_eip`
   project, assert the emitted `project/production/main.tf`'s user_data heredoc
   region contains no bare `${` (all escaped to `$${`) and that a known bash
   expansion appears in escaped form (e.g. `$${PROJECT}`). Fast, no external
   tool. Guards the specific escaping.

2. **`tofu validate` (integration-marked).** Compile both `ec2_traefik_eip`
   and `ec2_traefik_pip`, run real `tofu init -backend=false` + `tofu validate`
   on `project/production` (and the env tiers for completeness), assert
   success. This is the test that would have caught the original bug and will
   catch *any* future HCL-validity regression on this path — not just this one
   escaping issue. Marked `integration` and skipped gracefully when `tofu` is
   absent.

## Out of scope

- Broader "validate all emitted HCL" coverage for the `alb` path and other
  elastic outputs. Worth doing, but this mod is scoped to the ec2_traefik
  break the operator hit. The `tofu validate` helper this mod introduces makes
  that a natural follow-up.
- Surfacing the ACME registration email via `infra.yml` (already flagged as a
  follow-up in `hcl.py`'s existing comment). Untouched here.
