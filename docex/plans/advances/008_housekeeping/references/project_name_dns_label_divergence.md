# A capitalized project name compiles to two disagreeing spellings

`naming.dns_label` (`naming.py:127-135`) is the single expression of the
underscores→hyphens, lowercase rule: `name.replace("_", "-").lower()`. Four HCL
template sites re-derive the project segment inline instead, and they **do not
agree**:

| Site | Expression | `\| lower`? |
| ---- | ---------- | ----------- |
| `project.tf.j2:325` | `{{ project \| replace('_', '-') }}-traefik` | **no** |
| `main.tf.j2:63` | `{{ project \| replace('_', '-') }}-{{ env }}-{{ short }}` | **no** |
| `main.tf.j2:128` | `{{ project \| replace('_', '-') \| lower }}-{{ env }}` | yes |
| `main.tf.j2:130` | same, inside the description string | yes |

The root cause is that `emit_hcl_project`'s template context is assembled ad hoc
at its single call site (`cicl/compile.py:1372-1379`), and `project_dns_label`
never enters HCL template context — it reaches only `emit/compose.py` and
`emit/ansible.py`. So no template site is the shared expression, and the two
without `| lower` are not even equivalent to it.

**This is a failure mode, not an inconsistency.** A project named `MyProject`
compiles, in one `docex compile` run, to two spellings of its own project segment
— `MyProject-traefik` and `MyProject-prod-…` from the no-`lower` sites,
`myproject-prod` from the rest and from the entire fixed side (which goes through
`project_dns_label`). On a case-sensitive AWS name (`aws_security_group.name`, ASG
names) `MyProject-prod-web` and `myproject-prod-web` are **different resources**,
and the two halves of the emitted stack disagree about which one exists. Nothing
catches it: no fixture or seed uses a capital letter, and `ProjectManifest.name`
is a bare `str` with no pattern (`cicl/model.py:122`).

## Decision (plan review) — reject at entry

Reject a non-conforming project name where it enters `docex`
(`context.py` / `ProjectManifest`), so a name that is not already a clean DNS
label fails its next `compile` with a clear message. Chosen over silent
normalization (which would change the identity of already-deployed resources
invisibly) and over a `check`-time gate. It is a breaking validation in principle
— a capitalized name that compiles today would error — but no real project carries
one, so it functions as a bugfix that aligns names to the doctrine's own DNS-label
rule.

## Changes to make

1. Validate the project name at load (`context.py` / `ProjectManifest.name`
   pattern): it must already be a valid DNS label, so `dns_label` is idempotent on
   it. Reject with a clear message otherwise.
2. Pass `project_dns_label` into HCL template context, and have the four template
   sites use it instead of re-deriving — so no fifth/sixth author invents the rule
   again. The number of re-derivations is the defect; equalizing their current
   values is not the fix.
3. Add a fixture whose project name would previously have diverged (or, post-
   rejection, one that exercises the new rejection), so the divergence can never
   pass silently again.

## Where to look

- `naming.py:127-135` — `dns_label`, the expression all sites should be.
- `emit/templates/project.tf.j2:325`, `emit/templates/main.tf.j2:63,128,130` — the
  four re-derivations.
- `cicl/compile.py:1372-1379` — the hand-assembled context that never passes
  `project_dns_label`.
- `context.py` / `cicl/model.py:122` — where a project name enters and where the
  pattern goes.
- `emit/compose.py`, `emit/ansible.py` — the emitters that already receive
  `project_dns_label`.
- `plans/core/compiler.md § Emit` and § *Project segment on data-plane names*.
