# `emit_hcl_project`'s context is assembled by hand, and two things fell out of it

**Found:** advance 006, mod 134b, while verifying `compiler.md`'s claim that "the
templates do not do naming translation themselves". **Not fixed there** — mod 134b is a
prose-only pass, and both findings below need a behavior change.

Two findings in one file because they share a root cause: `emit_hcl_project`'s template
context is assembled **ad hoc at its single call site** (`cicl/compile.py:1372-1379`)
rather than derived from the compiled document. A parameter the call site forgets is
silently defaulted; a value the call site never passes is silently re-derived inside the
templates. Splitting these into two briefs would hide that they are the same shape.

---

## Finding 1 — the ACME account email is permanently a placeholder

`emit/hcl.py:1167` declares the parameter:

```python
    reverse_proxy: str | None = None,
    traefik_acme_email: str | None = None,
) -> None:
```

`:1253` resolves it, with a comment that already anticipates this brief:

```python
        # WHY: ACME registration email — LE needs *something*; use a
        # project-derived placeholder when the operator hasn't supplied
        # one. A real follow-up mod can surface this via infra.yml.
        acme_email = traefik_acme_email or f"docex@{apex_domain}"
```

`:1260` passes it into the user-data template, which writes it at
`emit/templates/ec2_traefik_user_data.sh.j2:142` as the Let's Encrypt account email:

```yml
certificatesResolvers:
  doctrine:
    acme:
      email: {{ traefik_acme_email }}
```

**The only production call site never passes it.** `cicl/compile.py:1372-1379` passes
`project`, `project_version`, `apex_domain`, `codebase_names`, `naming_policies`,
`out_path`, `reverse_proxy` — and stops. So on both `ec2_traefik` variants the ACME
account email is always `docex@<apex_domain>`: an address that need not exist, need not
be deliverable, and is not the operator's.

Class-3 — **documented, not implemented**. The parameter is in the signature, so a
reader of `emit_hcl_project` concludes the value is configurable. Nothing configures it.

### Why it is invisible

The fallback makes the emitted artifact **valid**. There is no missing key, no empty
string, no HCL that fails to parse, so no gate can fire: `docex compile` succeeds,
`docex check` succeeds, and both smoke walks pass — the fixed walk because it does not
use this template at all, the elastic walk because Let's Encrypt issues certificates
without ever verifying the account address. The failure surface is entirely *after*
issuance and entirely off-machine.

### The real question — stated, not answered

**Where does an ACME account email belong?** Three candidates, each with a different
owner:

- **`infra.yml`** — it is per-project infrastructure config and the reverse proxy is
  declared there already. Against: it is not a *shape* fact, and CICL has so far kept
  operator contact details out.
- **`project.yml`** — it is project identity, like `name`, not per-environment. Against:
  `project.yml` is deliberately tiny and read by everything.
- **config** (`infra/config/<side>.env`) — it is exactly "a value likely to vary between
  deploys". Against: the value is needed at *compile* time, not container-start time, so
  it would be the first compile-time read of a config `.env`, and project-tier output is
  per-side rather than per-env.

The prior question, which decides how much any of this matters: **what does Let's
Encrypt actually use the address for?** Expiry-notice mail and account recovery — not
validation, not issuance. So the cost of the placeholder is that nobody is warned about
a renewal that has stopped working, and that the account cannot be recovered. That is a
real but narrow cost, and it should be weighed before spending a CICL field on it.

Also open, and cheaper: whether `traefik_acme_email` should keep its default at all. A
required keyword argument with no fallback would have made this a compile error at the
one call site the day the parameter was added.

---

## Finding 2 — two template sites diverge from `naming.dns_label`

`naming.dns_label` (`naming.py:127-135`) is the single expression of the
underscores→hyphens, lowercase rule:

```python
    return name.replace("_", "-").lower()
```

Four HCL template sites re-derive the project segment inline instead, and **they do not
agree with each other**:

| Site | Expression | `\| lower`? |
| ---- | ---------- | ----------- |
| `project.tf.j2:325` | `{{ project \| replace('_', '-') }}-traefik` | **no** |
| `main.tf.j2:63` | `{{ project \| replace('_', '-') }}-{{ env }}-{{ short }}` | **no** |
| `main.tf.j2:128` | `{{ project \| replace('_', '-') \| lower }}-{{ env }}` | yes |
| `main.tf.j2:130` | same, inside the description string | yes |

`project_dns_label` **never enters HCL template context** — it appears only in
`emit/compose.py` and `emit/ansible.py`; neither `emit_hcl` nor `emit_hcl_project`
passes it. So none of the four sites is the shared expression, and the two without
`| lower` are not even equivalent to it.

### This is a failure mode, not an inconsistency

A project named `MyProject` compiles, **in one `docex compile` run**, to two spellings
of its own project segment:

| Resource | Site | Rendered segment |
| -------- | ---- | ---------------- |
| project traefik ASG / instance name | `project.tf.j2:325` | `MyProject-traefik` |
| env-tier security groups and friends | `main.tf.j2:63` | `MyProject-prod-…` |
| Service Connect namespace | `main.tf.j2:128` | `myproject-prod` |
| its description string | `main.tf.j2:130` | `myproject prod` |

Everything routed through `naming.apply_policy` / `dns_label` gets `myproject`, and so
does the **entire fixed side**, which goes through `project_dns_label`. So the
divergence is not template-vs-template: it is **template-vs-the-rest-of-docex**. On a
case-sensitive AWS name (`aws_security_group.name`, ASG names) `MyProject-prod-web` and
`myproject-prod-web` are *different resources*, and the two halves of the emitted stack
disagree about which one exists.

Nothing catches it, for two independent reasons:

1. **No fixture has a capital letter.** Every test project, every unit fixture, and both
   seeds use lowercase underscore names, so every existing assertion passes under either
   expression.
2. **Nothing rejects a capital letter.** `context.py` applies no pattern to
   `project.yml`'s `name`, so `MyProject` is a legal project name today and compiles
   without a warning.

### The fix is not to patch four Jinja sites

Adding `| lower` to `project.tf.j2:325` and `main.tf.j2:63` makes the four sites agree
today and leaves **the fifth author** to re-derive the rule from scratch — which is how
there came to be four. The number of re-derivations is the defect; equalizing their
current values is not a fix.

The fix is to **normalize or validate the project name where it enters `docex`**, so
that `dns_label` is idempotent on it and every downstream spelling collapses to one
regardless of which expression produced it. `context.py` is the one place a project name
enters.

**Name the cost honestly: that is a behavior change.** It either rejects project names
that compile today, or silently rewrites them — and a silent rewrite changes the
identity of already-deployed resources for any project currently carrying a capital
letter. That is why mod 134b booked it instead of taking it, and corrected
`compiler.md`'s prose to *describe* the four re-derivations rather than deny they exist.

**Left open: reject or normalize?** Rejection is loud, cheap, and safe on existing
projects (a project with a capital letter fails its next `compile` with a clear
message). Normalization is silent, requires no operator action, and is the more
dangerous of the two precisely because it is invisible. There is also a third position —
validate in `check` rather than `context.py`, making it a pipeline gate rather than a
load-time error — which changes who sees the failure and when.

Whichever lands, `project_dns_label` should then be passed into HCL template context so
the templates have the shared value available and no sixth site needs to invent it.

---

## Where to look

- `src/docex/emit/hcl.py:1167` — the `traefik_acme_email` parameter declaration.
- `src/docex/emit/hcl.py:1253` — the fallback, and the comment anticipating this brief.
- `src/docex/emit/templates/ec2_traefik_user_data.sh.j2:142` — where the address lands.
- `src/docex/cicl/compile.py:1372-1379` — the only production call site; the argument
  list that assembles the context by hand.
- `src/docex/emit/templates/project.tf.j2:325` and
  `src/docex/emit/templates/main.tf.j2:63,128,130` — the four re-derivations.
- `src/docex/naming.py:127-135` — `dns_label`, the expression they should all be.
- `src/docex/emit/compose.py`, `src/docex/emit/ansible.py` — the two emitters that *do*
  receive `project_dns_label`.
- `src/docex/context.py` — the one place a project name enters `docex`, and where a
  pattern would go.
- `plans/core/compiler.md` § *Emit* — the corrected prose describing the four sites, and
  § *Project segment on data-plane names*, the rule they are supposed to follow.
