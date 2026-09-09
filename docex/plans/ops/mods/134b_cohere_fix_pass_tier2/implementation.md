# Mod 134b — Implementation

## Read this first

You are executing the Tier 2 half of the advance-006 cohere fix pass. `overview.md`
in this folder is the design and the record of what was verified; read it before you
start, because several steps below deliberately do *less* than an obvious reading
would suggest, and the reasons are there.

**The governing constraint: you may not change what any rule means.** Every step
repairs prose, corrects a claim to match measured behavior, fixes an example so it
obeys a rule already written, completes a list that has silently lost a member, or
repoints a citation. If a step seems to require deciding what a rule *should* say,
**stop and report it** rather than deciding.

**Three standing prohibitions:**

1. **Do not change behavior.** Every edit in §1–§6 is to a comment, docstring, or
   markdown file. **No `.py` statement, no `.j2` expression, no `.yml` value.** The
   one exception is §7, which creates three new markdown briefs.
2. **Do not "fix" the things this mod deliberately leaves alone.** In particular: do
   not add `| lower` to any Jinja template, do not wire `traefik_acme_email`, do not
   delete `MigrationFailed`, and do not touch rule 33 in `doctrine/infrastructure/cicl.md`.
   All four are booked or settled decisions.
3. **Do not touch doctrine prose** (anything under `doctrine/`). The only citation
   *targets* you need from there are given inline below; you are repointing citations
   *at* the doctrine, never editing it.

**On core planning docs.** The mod process normally forbids implementation steps that
update core planning docs. This mod is the exception and it is deliberate: the
corrections to `plans/core/{masterplan,compiler,release_flow,test_projects}.md` **are
the mod's substance**, not a reflection of a code change made elsewhere. Make them.
The `CHANGELOG.md` entry is still reserved for the mod cycle's documentation step and
is **not** yours.

All paths are relative to `/home/ubuntu/.claude/jean_baudrillard/docex/` unless they
begin with `doctrine/` or `test_projects/`.

### Spot check before you begin

Run this one test by name. It is the proof behind §1.1, and if it does not exist or
does not pass, stop and report — the premise of the whole first step is wrong.

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
./.venv/bin/python -m pytest tests/unit/test_validate.py::test_rule_33_keys_on_network_membership_not_role -q
```

---

## §1. Rule 33's negative arm — two sites claiming a check does not exist

Both sites say the negative arm is enforced "by rule 4, with no second rule". False:
`src/docex/cicl/validate.py:1886` emits a dedicated `rule_33_health_check_path_off_web`
in the `elif not on_web and declared is not None` branch, and it is **load-bearing**
because rule 4 acts at the *table* layer — it rejects the field on the `worker` /
`clock` engines and cannot see a `role: web` core service (whose engine declares the
field legally) sitting off the `web` network. That case is exactly
`tests/unit/test_validate.py::test_rule_33_keys_on_network_membership_not_role`.

### 1.1 `plans/core/compiler.md` — the probe section

Replace lines 498-500. Current text:

```
It is gone from `worker` and `clock` entirely, which is how
[rule 33](#validation)'s negative arm is enforced at the table layer by rule 4, with no
second rule.
```

Two defects here, not one — fix both in this edit:

- The "no second rule" claim.
- **The citation.** `[rule 33](#validation)` resolves to `compiler.md`'s own
  `## Validation` heading (`:589`), not to `cicl.md § Validation Rules` where rule 33
  lives. Line `:493`, six lines above, cites it correctly with the full doctrine path;
  copy that form. Note for your own understanding: `linkcheck` cannot catch this
  because the anchor **does** resolve — just not to what the words claim.

Replacement (keep the surrounding paragraph intact; this is the tail of it):

```
It is gone from `worker` and `clock` entirely, which is how
[rule 33](../../../doctrine/infrastructure/cicl.md#validation-rules)'s negative arm is
enforced at the table layer by rule 4 — for those two roles. Rule 4 cannot enforce the
whole arm, because it only ever rejects a field the *engine* does not declare: a
`role: web` core service off the `web` network declares `health_check_path` legally as
far as the table is concerned. `cicl/validate.py`'s dedicated
`rule_33_health_check_path_off_web` is what catches that case, and it is the only thing
that does — see
`tests/unit/test_validate.py::test_rule_33_keys_on_network_membership_not_role`. The
rule keys on network membership, not on role, so the table layer and the validator each
cover a case the other structurally cannot.
```

### 1.2 `tables/roles/worker.yml` — the `fields: {}` comment

Replace the comment at lines 66-70. Current text:

```yml
      fields: {}   # Rule 4 (tt_rule_4_undeclared_field) now REJECTS
                   # `health_check_path` on a worker, which is how rule 33's
                   # negative arm is enforced at the table layer with no
                   # second rule — the same mechanism clock.yml documents for
                   # `schedules`.
```

Replacement:

```yml
      fields: {}   # Rule 4 (tt_rule_4_undeclared_field) REJECTS
                   # `health_check_path` on a worker, which enforces rule 33's
                   # negative arm at the table layer FOR THIS ROLE. It does not
                   # enforce the whole arm: a `role: web` core service off the
                   # `web` network declares the field legally per its own engine,
                   # and only `cicl/validate.py`'s dedicated
                   # `rule_33_health_check_path_off_web` catches that. Rule 33
                   # keys on network membership, not role.
                   #
                   # NOT the same mechanism clock.yml documents for `schedules`:
                   # `schedules` is declared on no other role, so there is no
                   # legal-declaration case for a second rule to catch and rule 4
                   # really is the whole story there.
```

**Do not weaken the `schedules` cross-reference into a bare "see clock.yml".** The
asymmetry between the two fields is the reason they are not the same mechanism, and
naming it is what stops the next reader re-deriving the wrong conclusion.

**Preserve YAML validity**: `fields: {}` must remain the value. Comments only.

---

## §2. Code docstrings and comments

### 2.1 `src/docex/cicl/model.py` — `core_uses()` names a reader that reads neither accessor

At `:265-267`, the docstring says "Both the validator (rule 7) and ``check.py``'s
contract / health gates read through here". `check.py` references neither `core_uses`
nor `backing_uses`. The real readers are both in `validate.py`: `:626` inside
`_validate_refs`'s `scan` (rule 7) and `:885` inside `_validate_uses_addressing`
(rule 32).

Replace:

```
    reports each one once, and a malformed entry must not ALSO surface
    downstream — as a mystifying rule-7 miss, or as a missing contract for a
    target the author plainly named. Both the validator (rule 7) and
    ``check.py``'s contract / health gates read through here, so the
    dots-for-reference parse lives in exactly one place.
```

with:

```
    reports each one once, and a malformed entry must not ALSO surface
    downstream — as a mystifying rule-7 miss, or as a missing contract for a
    target the author plainly named. Two validation rules read through here —
    rule 7 (``_validate_refs``) and rule 32 (``_validate_uses_addressing``) — so
    the dots-for-reference parse lives in exactly one place. ``check.py`` is NOT
    a reader: its contract gates go through ``surfaces`` and ``model_extra``, and
    the health gate that once read this set (``_gate_health_endpoints``) was
    deleted in advance 006.
```

### 2.2 `src/docex/orchestrate/build.py` — the withdrawn `curl` requirement

At `:66-71`. Mods 126/127 withdrew both halves: `infrastructure.md § Codebase
Containers` now requires only that an image "must be able to run
`./health.sh <service>`", and there is no `curl` gate.

**Keep the paragraph's argument.** Its point — an unenforced image requirement is a
claim in the rule of record that nothing verifies — is correct and survives its
expired example. There is a true replacement: `src/docex/pipeline/check.py:592-628`
gates the *presence* of `build.sh` / `test.sh` / `health.sh` in every codebase.

Replace:

```
# is in both coreutils and busybox, so any base carrying a build toolchain has
# it. Deliberately NOT a doctrine rule: the doctrine's one image requirement
# (`curl`) is backed by a `docex check` gate, and an unenforced image
# requirement is a claim in the rule of record that nothing verifies. The
# failure mode here is loud anyway — `find: not found`, non-zero exit, build
# fails immediately.
```

with:

```
# is in both coreutils and busybox, so any base carrying a build toolchain has
# it. Deliberately NOT a doctrine rule: the doctrine's one image requirement is
# that the image can run `./health.sh <service>` (infrastructure.md § Codebase
# Containers), and `docex check` gates the shim's presence — an unenforced image
# requirement is a claim in the rule of record that nothing verifies. (Mods
# 126/127 withdrew an earlier `curl` requirement, which is why the gate covers
# the shim rather than any particular tool inside it.) The failure mode here is
# loud anyway — `find: not found`, non-zero exit, build fails immediately.
```

### 2.3 `src/docex/aws/client.py:415` — dead citation

`cicl.md § Depends-On Relationships` was renamed to **§ Uses Relationships** in
advance 005 (`doctrine/infrastructure/cicl.md:382`). In the `ecs_force_new_deployment`
docstring, change:

```
        up endpoints registered after it started — see mod 109 and
        `cicl.md § Depends-On Relationships`.
```

to:

```
        up endpoints registered after it started — see mod 109 and
        `cicl.md § Uses Relationships`.
```

### 2.4 `src/docex/aws/client.py:1-17` — the module docstring's surface enumeration

Five bullets against **34 declared methods**. Unlisted whole families: ECR (auth token,
image existence, image count), the RDS deletion-protection probe, Service Connect
endpoint discovery, ECS deployment/task inspection (the stagetest pre-step and the
release-time consumer reconcile), and VPC/subnet discovery by tag.

**Generalize the list; do not lengthen it into a second enumeration that will go stale
the same way.** An enumeration nothing keeps current is the defect being repaired.
Also drop the "Phase 4" framing, which dates the claim rather than stating it, and —
per the Q3 rule, since this line is being rewritten anyway — name the CLI verb honestly
in the S3/DynamoDB bullet.

Replace lines 5-11:

```
The Protocol covers the union of AWS operations Phase 4 needs:

  - ``caller_identity`` — STS account-ID lookup for SSM ARN derivation
  - SSM Parameter Store push (used by ``release`` to clobber per-env secrets)
  - S3 + DynamoDB create/inspect (used by ``bootstrap``)
  - ECS task definition register + RunTask + wait (used by elastic migrate)
  - EC2 / ECS lookups for release-time HCL prerequisites
```

with:

```
The Protocol covers **every** AWS operation docex performs, which is what makes
the boto3 ban enforceable. Read the method list below rather than a summary — it
is the surface, and any prose count here would be one refactor from wrong. The
families, for orientation:

  - STS — ``caller_identity``, for SSM ARN derivation
  - SSM Parameter Store — the elastic aggregate (``release``)
  - S3 + DynamoDB — the tofu state backend (``docex projinfra up production``)
  - ECR — registry auth, image existence, image counts (``containerize``,
    ``preinfra``, the rollback image probes)
  - ECS — task-definition register / RunTask / wait (elastic migrate), plus
    cluster, service, deployment and task inspection (the ``stagetest``
    pre-step and the release-time Service Connect consumer reconcile)
  - Cloud Map — Service Connect endpoint discovery, for that same reconcile
  - EC2 — VPC / subnet / security-group discovery for release-time HCL
    prerequisites
  - RDS — the deletion-protection probe that gates ``envinfra down``
```

### 2.5 `src/docex/opentofu/__init__.py:3` — "four operations", five exported

`__all__` lists five and `tofu_destroy` is live (elastic project-tier teardown in
`pipeline/projinfra.py`; elastic `envinfra down` for stage/prod).

Replace lines 3-6:

```
Phase 4 needs four OpenTofu operations — init, validate, plan, apply —
so we follow the Phase 3 ansible-runner pattern: one callable per
operation, no Protocol ceremony. The dispatcher and pipeline modules
import these functions directly; tests substitute a recorder.
```

with:

```
Five operations — init, validate, plan, apply, destroy — following the
ansible-runner pattern: one callable per operation, no Protocol ceremony.
``tofu_destroy`` arrived after the other four (elastic project-tier teardown
and elastic ``envinfra down`` for stage/prod). ``__all__`` below is the
authority on the set. The dispatcher and pipeline modules import these
functions directly; tests substitute a recorder.
```

### 2.6 `src/docex/ssh/client.py:3` — "the single SSH operation", two declared

`run` (exit code only) and `capture` (exit code + stdout). `capture` exists because the
stagetest pre-step needs `docker inspect`'s stdout
(`pipeline/orchestrator_health.py:191`), which `run`'s contract cannot carry.

Replace lines 3-8:

```
Declares the single SSH operation docex needs: run a command on a
remote host as a given user, authenticating with a private key.
Same discipline as ``GitClient`` / ``DockerClient`` — the method
returns an exit code and never raises on a non-zero remote command.
The pipeline layer interprets the code (including SSH's own ``255``
connection-failure code).
```

with:

```
Declares the two SSH operations docex needs, both running a command on a
remote host as a given user, authenticating with a private key:

  - ``run`` — exit code only.
  - ``capture`` — exit code plus stdout. Needed by the ``stagetest``
    pre-step, which reads ``docker inspect`` output over SSH
    (``pipeline/orchestrator_health.py``); ``run``'s contract cannot
    carry a payload.

Same discipline as ``GitClient`` / ``DockerClient`` — neither method
raises on a non-zero remote command. The pipeline layer interprets the
code (including SSH's own ``255`` connection-failure code).
```

### 2.7 `src/docex/pipeline/stagetest.py:5-6` — two defects in one step

The code reads `apex_domain`, not `domain`, and builds a **three-segment** host
(`:88-92`). Replace:

```
  1. Compute STAGING_URL from ``infra.yml``'s ``domain`` field —
     ``https://stage.<domain>``.
```

with:

```
  1. Compute STAGING_URL from ``infra.yml``'s ``apex_domain`` field and the
     project name — ``https://stage.<dns_label(project)>.<apex_domain>``, the
     canonical bare-env host per ``cicl.md § Domain``.
```

### 2.8 `src/docex/pipeline/rollback.py:248-255` — a CICL generation behind

The current generation is `"3"` (`cicl.md:328`, rule 21; `model.py:455-464`), and this
module already reads `CURRENT_CICL_VERSION` at `:319`.

**Drop the three-example parenthetical; do not renumber it.** Its examples are
v1-specific and two now read as false against v3: `core_services:` is the live v3 key
(`test_projects/fixed/infra/infra.yml:39`) and `resources:` is a declared v3
core-service field. Enumerating one superseded generation's failure modes is exactly
what went stale here, so re-deriving the list for v2 would re-arm it.

Replace:

```
    WHY a single-key read rather than ``CICLDocument`` validation: a
    pre-v2 ``infra.yml`` fails full validation for several unrelated
    reasons at once (no ``core_services:``, ``domain_default_service``,
    core-service-level ``resources:`` under ``extra="forbid"``), and which
    one pydantic reports first decides what the operator sees. "You are
    across the v1 boundary" is the only fact that matters here, and it
    is the one a single-key read cannot get wrong. It also has to work
    on a file that is not a valid CICL document at all.
```

(Verified verbatim against the file. Match the line breaks exactly — the docstring is
hard-wrapped.) Replacement:

```
    WHY a single-key read rather than ``CICLDocument`` validation: an
    ``infra.yml`` from any superseded generation fails full validation for
    several unrelated reasons at once, and which one pydantic reports first
    decides what the operator sees. "You are on a generation this docex does
    not compile" is the only fact that matters here — ``CURRENT_CICL_VERSION``
    is the boundary, deliberately not restated as a literal — and it is the one
    a single-key read cannot get wrong. It also has to work on a file that is
    not a valid CICL document at all.
```

### 2.9 `src/docex/errors.py` — three stale claims

**(a) `EnvNotRunning` (`:78-79`).** Mod 099 moved migrate to a one-off container
(`orchestrate/migrate.py:116`, `compose_run_one_off`), and the only
`raise EnvNotRunning` in the tree is `orchestrate/build.py:110`. Replace:

```
    Raised by ``build`` (which needs running dev containers) and by
    ``migrate dev/test`` (which exec into a running container).
```

with:

```
    Raised by ``build``, which needs running dev containers to run
    ``build.sh`` against the bind-mounted source. NOT raised by
    ``migrate dev/test``: since mod 099 that path runs a one-off container
    rather than exec-ing into a running one, so it does not require the
    stack to be up.
```

**(b) `MigrationFailed` (`:88-89`).** No raiser anywhere in `src/` or `tests/`. Do
**not** delete the class — it is exported and removal is a behavior change. Annotate
it *usefully*: an unraised error class misleads only because a reader assumes it is the
channel, so name the real channel. Replace:

```
class MigrationFailed(DocexError):
    """``migrate.sh`` for a service exited non-zero."""
```

with:

```
class MigrationFailed(DocexError):
    """``migrate.sh`` for a service exited non-zero.

    **Currently unraised — nothing in docex constructs this.** Kept because it
    is exported. A migration failure surfaces by RETURN CODE, not by this
    exception: ``dev``/``test`` and fixed ``stage``/``prod`` both print to
    stderr and propagate a non-zero rc out of ``orchestrate/migrate.py``, and
    the elastic path raises ``ECSTaskFailed`` instead. Do not add a
    ``raise MigrationFailed`` to those paths on the strength of this class
    existing — their callers read rc.
    """
```

**(c) `BootstrapFailed` (`:231-233`).** The verb does not exist; the entry point is
`docex projinfra up production` (`__main__.py:368-379`). Replace:

```
class BootstrapFailed(DocexError):
    """``docex bootstrap`` couldn't create or reconcile the project's
    OpenTofu state backend (S3 bucket + DynamoDB table)."""
```

with:

```
class BootstrapFailed(DocexError):
    """``docex projinfra up production`` couldn't create or reconcile the
    project's OpenTofu state backend (S3 bucket + DynamoDB table). The verb
    was ``docex bootstrap`` before mod 034; the internal step is still called
    bootstrap (``pipeline/bootstrap.py::run_bootstrap``)."""
```

### 2.10 The remaining `docex bootstrap` verb sites

Per the approved rule: **fix every site naming a CLI verb an operator types; leave
every site naming the internal step or module.** `src/docex/cicl/compile.py:1369`
already models the honest form ("docex bootstrap (now projinfra up production per mod
034)") — follow it, and do not edit that line.

Five sites, each a minimal in-place replacement of the verb:

| File:line | Change |
| --------- | ------ |
| `src/docex/opentofu/subprocess_runner.py:89` | "Used by ``docex bootstrap``" → "Used by ``docex projinfra up production``" |
| `src/docex/opentofu/subprocess_runner.py:143` | "``docex bootstrap`` to determine which phase" → "``docex projinfra up production`` to determine which phase" |
| `src/docex/opentofu/subprocess_runner.py:161` | "Used by ``docex bootstrap`` to read" → "Used by ``docex projinfra up production`` to read" |
| `src/docex/pipeline/containerize.py:157` | "provisioned by `docex bootstrap`" → "provisioned by `docex projinfra up production`" |
| `src/docex/pipeline/bootstrap.py:1` | "``docex bootstrap`` — idempotent setup for elastic projects." → "The elastic project-tier setup behind ``docex projinfra up production`` — idempotent." |

**Explicitly leave alone:**

- `src/docex/pipeline/bootstrap.py:173-174` — already says "the command is `docex
  projinfra up production`, not the stale `docex bootstrap`". This is the honest form;
  touching it would destroy the record.
- `src/docex/aws/client.py:87, 92, 124, 135` and every bare "bootstrap" that is not
  prefixed `docex ` — these name the internal step, which is still its name. (`:9` is
  handled by §2.4.)
- `src/docex/__main__.py:290`'s "(formerly ``bootstrap``)" — correct as written. The
  *other* half of that docstring is §2.11.

### 2.11 Two "elastic projinfra is stubbed" claims

Elastic projinfra ships: `run_projinfra_elastic_down` exists and `up production` runs
`run_bootstrap`'s two-phase project-tier apply (`pipeline/bootstrap.py:119-166`).

**(a) `src/docex/__main__.py:286-291`.** Replace:

```
    Mod 036 wires the fixed branch end-to-end: ``up`` runs the project-
    tier compose stack (four ``-web`` networks + per-project traefik);
    ``down`` tears it down (refusing if any env-tier compose stack for
    this project is still up). Elastic ``up production`` continues to
    run the existing state-backend setup (formerly ``bootstrap``); the
    rest of elastic projinfra is stubbed until mods 037-039."""
```

with:

```
    Fixed: ``up`` runs the project-tier compose stack (four ``-web``
    networks + per-project traefik); ``down`` tears it down (refusing if
    any env-tier compose stack for this project is still up). Elastic
    ``up production`` (the verb formerly spelled ``bootstrap``) creates the
    tofu state backend and then runs the two-phase project-tier ``tofu
    apply`` — phase 1 the Route53 zone alone, for NS delegation, phase 2 the
    full project tier; ``down production`` tears the project tier down."""
```

**(b) `src/docex/pipeline/projinfra.py:1-3`.** Replace:

```
"""``docex projinfra <direction> <side>`` — project-tier infrastructure
runner. Mod 036 ships the fixed branch (per-project traefik + four
``-web`` networks); mods 037-039 add elastic.
```

with:

```
"""``docex projinfra <direction> <side>`` — project-tier infrastructure
runner. Both foundations are live: fixed brings up a per-project traefik
plus four ``-web`` networks; elastic ``up production`` runs the state
backend and the two-phase project-tier ``tofu apply``
(``pipeline/bootstrap.py``), and ``down`` tears it down.
```

---

## §3. `plans/core/compiler.md`

### 3.1 `:39` — the pipeline diagram's emit list, wrong in both directions

`emit/secrets.py` is **not** on the compile path — `compiler.md:583` says so itself
("retains only ``render_manifest_env``", used by the scaffold commands, "never written
by `compile`"). Three modules that *are* on it are missing: `schedules.py`
(`compose.py:51`, `hcl.py:45`, `compile.py:1264`), `otelcol.py` (`compose.py:50`,
`hcl.py:44`), and `tags.py` (`compile.py:1216`, `hcl.py:46`).

Change the diagram line from:

```
                    │ emit/...         │ compose.py, hcl.py, ansible.py, secrets.py
```

to:

```
                    │ emit/...         │ compose.py, hcl.py, ansible.py,
                    │                  │ schedules.py, otelcol.py, tags.py
```

Keep the box-drawing characters aligned with the lines above and below. `secrets.py` is
**removed**, not moved.

### 3.2 `:58` — `CoreService`'s field list omits `surfaces`

Add it to the parenthetical, in the position it holds in the model. Change:

```
``CoreService`` is one named way of invoking a codebase's build artifact (`role`, `command`, `networks`, `resources`, `port`, `uses`, `replicas`, `env`), per
```

to:

```
``CoreService`` is one named way of invoking a codebase's build artifact (`role`, `command`, `networks`, `resources`, `port`, `uses`, `surfaces`, `replicas`, `env`), per
```

(Preserve the line's existing single-line form and the rest of the bullet verbatim.)

### 3.3 `§ Key types` — no entry for the surface types

Add one bullet immediately after the `CoreService` / `ServiceRef` bullet at `:58`,
before the `In src/docex/naming.py:` line at `:60`. **Route to the doctrine; do not
restate the style table** — it is derived, not tabulated, and a second copy here is the
drift this mod exists to prevent.

```
- **`Surface` / `API_STYLE_FORMATS` / `IMPLEMENTED_CONTRACT_FORMATS`** (`cicl/model.py`, advance 006) — a `Surface` is one described boundary of a core service (`name` + `api_styles`), per [`cicl.md § Surfaces`](../../../doctrine/infrastructure/cicl.md#surfaces). `API_STYLE_FORMATS` maps each style to its contract format and `IMPLEMENTED_CONTRACT_FORMATS` is the subset docex can check today. Rule 29 is **derived** from the first map rather than tabulated against it, so it cannot drift as styles are added; two consumers read the map — the rule-29 validator and `check.py::_gate_contracts` — which is why it lives on the model. Do not restate the mapping here; `cicl.md § Surfaces` is the table and a literal-equality test pins the code to it.
```

### 3.4 `:176` and `:648` — `effective_replicas` has three readers

The third is `pipeline/orchestrator_health.py:172`, which computes replica container
names for the stagetest pre-step and comments that it deliberately does not assume one
(`:170-171`). Only `:176` uses the phrase "both emitters"; `:648` is short by the same
reader without it. Fix both.

`:176`, change:

```
[`shape.md`](../../../doctrine/infrastructure/shape.md)'s Runtime Shape
paragraphs — and both emitters call it, so the prod-only rule is stated once.
```

to:

```
[`shape.md`](../../../doctrine/infrastructure/shape.md)'s Runtime Shape
paragraphs — and all three readers call it (both emitters plus the `stagetest`
pre-step, which computes replica container names to inspect), so the prod-only
rule is stated once.
```

`:648`, change:

```
| How `replicas` becomes containers or tasks | `src/docex/cicl/compile.py::effective_replicas` (the `prod`-only clamp) + `emit/compose.py` (the fixed unroll) + `emit/hcl.py::render_ecs_service` (`desired_count`) |
```

to:

```
| How `replicas` becomes containers or tasks | `src/docex/cicl/compile.py::effective_replicas` (the `prod`-only clamp) + `emit/compose.py` (the fixed unroll) + `emit/hcl.py::render_ecs_service` (`desired_count`) + `pipeline/orchestrator_health.py` (which replica container names the `stagetest` pre-step inspects) |
```

### 3.5 `:587` — the naming-translation claim and the template list

Two defects in one line. Current text:

```
The Jinja templates live in `src/docex/emit/templates/` — `main.tf.j2` (env-tier HCL), `project.tf.j2` (project-tier HCL), `playbook.yml.j2`, `inventory.yml.j2`, `ansible.cfg.j2`. Pre-translated names (state bucket, ALB name, ECS cluster, etc.) are computed in Python and passed to the templates as context; the templates do not do naming translation themselves.
```

- The list omits `ec2_traefik_user_data.sh.j2`, the sixth file in that directory
  (already named at `:642`).
- "the templates do not do naming translation themselves" is **false and
  prescriptively harmful** — it is what would stop an author noticing the divergence.
  Four sites re-derive the project segment inline; two omit `| lower`.

Replace with:

```
The Jinja templates live in `src/docex/emit/templates/` — `main.tf.j2` (env-tier HCL), `project.tf.j2` (project-tier HCL), `ec2_traefik_user_data.sh.j2`, `playbook.yml.j2`, `inventory.yml.j2`, `ansible.cfg.j2`. Pre-translated names (state bucket, ALB name, ECS cluster, etc.) are computed in Python by `apply_policy` and passed to the templates as context — **but four HCL template sites re-derive the project segment inline instead**, and they do not agree with each other: `project.tf.j2:325` and `main.tf.j2:63` render `{{ project | replace('_', '-') }}` with **no `| lower`**, while `main.tf.j2:128` and `:130` include it. `project_dns_label` is never passed into HCL template context (only `emit/compose.py` and `emit/ansible.py` hold it), so none of the four is equivalent to `naming.dns_label`, and the two without `| lower` diverge from it outright on a mixed-case project name — which nothing rejects. Booked as a defect, not fixed here: adding `| lower` to two sites leaves the fifth author to re-derive it, and the real fix is to normalize or validate the project name where it enters docex. Do not add a fifth re-derivation.
```

### 3.6 `§ Naming flow` — `ecs_cluster_name` is undocumented here

Per mod 134's narrowing: `release_flow.md:62` and `:141` document it and its five
readers thoroughly, so this is a `compiler.md`-only gap. Add one row to the "Where to
look when changing things" table (§ starting `:624`), adjacent to the other naming
rows. **Do not add it to `masterplan.md`** — that file enumerates no other naming
helper, so a lone entry would be the inconsistency rather than the fix.

```
| The ECS cluster / Service Connect namespace name | `src/docex/naming.py::ecs_cluster_name` — the only expression (mod 128 lifted it after finding five copies, one in `emit/hcl.py`, the emitter that creates the clusters the others read). Policy-aware; do not re-inline. Readers are enumerated in [`release_flow.md`](./release_flow.md) |
```

### 3.7 `emit/tags.py` appears in no core doc

Every sibling `emit` module has a "Where to look" row. Add one to the same table,
next to the other emit rows (near `:645`'s otelcol row):

```
| What tags every emitted resource carries | `src/docex/emit/tags.py` — `standard_tags` (the per-tier key set) and `render_hcl_tags`. Called from `emit/hcl.py`, `cicl/compile.py` and `pipeline/bootstrap.py`, and reaches both Jinja templates through `env.globals` |
```

---

## §4. `plans/core/release_flow.md`

### 4.1 `:70-76` — § The four sequences omits the consumer reconcile

The same file describes it richly at `:64` ("after the final apply on every branch
including rollback"), with four AWS calls, one of them mutating. The table stops one
step short on both elastic columns.

Add one row after the `| 5 |` row, and a note under the table. The table becomes:

```
|  | Fixed (steady-state or first) | Elastic — first release | Elastic — steady state |
| --- | ----- | ----------------------- | ---------------------- |
| 1 | ansible-playbook (everything below happens inside it) | SSM push | SSM push |
| 2 | docker pull (per codebase) | tofu apply (full) | tofu apply (targeted: migration task-defs only) |
| 3 | render compose.yml + .env | run_migrate (`RunTask` per schema owner) | run_migrate (`RunTask` per schema owner) |
| 4 | docker compose run migrate (per schema owner) | — | tofu apply (full) |
| 5 | docker compose up -d | — | — |
| 6 | — | Service Connect consumer reconcile | Service Connect consumer reconcile |
```

Then immediately after the table, before the "**Why the elastic ordering differs…**"
paragraph, add:

```
Row 6 runs **after the final apply on every elastic branch, including rollback**, and
is the one step in this table that is not an apply, a migrate, or a push: it reads
post-apply AWS state and may issue a *mutating* `forceNewDeployment`. It is detailed at
[§ Elastic-foundation flow](#elastic-foundation-flow) step 4 — the numbering there is
the authority; this row exists so the table cannot be read as the whole sequence.
```

---

## §5. `plans/core/masterplan.md`

### 5.1 `:110`, `:117`, `:120` — three wrong *Reads* columns

**`config` (`:110`)** — `scaffold` / `status` read `infra.yml` + transfer tables via
`config_manifest` (`secretsmgmt/engine.py:71`); the `secrets` row above already records
the analogous fact. Change the Reads cell from:

```
`infra/config/<env>.env`
```

to:

```
`infra.yml` + transfer tables (via `config_manifest`), `infra/config/<env>.env`
```

**`envinfra` (`:117`)** — bring-up reads the whole aggregate, TTE ∪ secrets ∪ config
(`orchestrate/up.py:141-143`). Change:

```
`infra/output/<env>/docker-compose.yml`, `infra/secrets/<env>.env`; for `down`, the running stack
```

to:

```
`infra/output/<env>/docker-compose.yml`, and the whole aggregate at bring-up — TTE ∪ secrets ∪ config (`infra/tte/`, `infra/secrets/`, `infra/config/`); for `down`, the running stack
```

**`migrate` (`:120`)** — `orchestrate/migrate.py:93-100` reads the compiled compose
file, the full aggregate, and `infra.yml` for the schema owners. Change:

```
service images at current version, `infra/secrets/<env>.env`
```

to:

```
service images at current version, `infra/output/<env>/docker-compose.yml`, `infra.yml` (for the schema owners), and the whole aggregate — TTE ∪ secrets ∪ config
```

### 5.2 `:116` and `:219` — elastic `projinfra up production` stops at the state backend

`pipeline/bootstrap.py:119-166` then runs the two-phase project-tier `tofu apply`:
phase 1 targets the Route53 hosted zone alone so the operator can NS-delegate, phase 2
applies the full project tier. Both idempotent; fixed short-circuits before them
(`bootstrap.py:28`).

`:116`, change the Writes cell tail:

```
elastic `up production`: runs `preinfra` as a gate, then the state-backend setup — S3 bucket + DynamoDB table for tofu state
```

to:

```
elastic `up production`: runs `preinfra` as a gate, then the state-backend setup (S3 bucket + DynamoDB table for tofu state), then the two-phase project-tier `tofu apply` — phase 1 the Route53 hosted zone alone so the operator can NS-delegate, phase 2 the full project tier; both idempotent
```

`:219`, change the Elastic cell:

```
`up production` creates `<project>-tofu-state` S3 bucket + `<project>-tofu-locks` DynamoDB table (idempotent)
```

to:

```
`up production` creates `<project>-tofu-state` S3 bucket + `<project>-tofu-locks` DynamoDB table, then applies the project tier in two phases (Route53 zone alone → full tier), pausing between them for NS delegation; all idempotent. `down production` tears the project tier down
```

### 5.3 `:165` — the release/migrate ordering

False on a first release (`release.py:667-670` is apply → migrate) and on rollback
(`pipeline/rollback.py` contains no migrate call at all). Change:

```
- `release` invokes `migrate` against the target env before applying new application state.
```

to:

```
- `release` invokes `migrate` against the target env **before** applying new application state in the steady-state case, which is what preserves zero-downtime. Two exceptions: on a **first release** the order inverts to apply-then-migrate, because migrate needs the env's services and database to exist; and **`rollback` never migrates at all**, since the doctrine's migrations are forward-only. Both are set out in [`release_flow.md § The four sequences`](./release_flow.md#the-four-sequences).
```

### 5.4 `:201` — the `CHANGELOG.md` claim

No code reads `CHANGELOG.md`. **Delete the whole bullet** from the `**Read:**` list
under `## Filesystem Surface`:

```
- `CHANGELOG.md` — referenced by `merge` for version-bump validation
```

Delete the line entirely; do not replace it with an annotation. The finding it
represents is recorded in the brief created at §7.3, which is why deleting it here
loses nothing.

### 5.5 `:222` — the elastic `release` row omits the reconcile

Change:

```
| `release` | `ansible-playbook` over SSH using `infra/deploy_creds/<env>` | SSM push → `RunTask` migration → `tofu apply` |
```

to:

```
| `release` | `ansible-playbook` over SSH using `infra/deploy_creds/<env>` | SSM push → `RunTask` migration → `tofu apply` → Service Connect consumer reconcile (`forceNewDeployment` on any consumer whose deployment predates a name it `uses`) |
```

### 5.6 `:280` — the SSH credential row omits `stagetest`

The stagetest pre-step raises before any SSH if `infra/deploy_creds/<env>` is absent
(`orchestrator_health.py:153-161`) and additionally needs **passwordless sudo** on the
target, because the release playbook runs `become: true` and the containers are
root-owned (`:178-181`). The sudo requirement is host state this table records for
nothing else, so it goes in the row rather than being dropped. Change:

```
| SSH to fixed-foundation hosts | `infra/deploy_creds/<env>` (private key) + `~/.ssh/known_hosts` | `release` (fixed); `preinfra production` (fixed — probes the target host for registry creds) |
```

to:

```
| SSH to fixed-foundation hosts | `infra/deploy_creds/<env>` (private key) + `~/.ssh/known_hosts`; and on the target host, passwordless `sudo` for the `deploy` user | `release` (fixed); `preinfra production` (fixed — probes the target host for registry creds); `stagetest`'s pre-step (fixed — `docker inspect` per core container, which needs the sudo above because the playbook runs `become: true` and the containers are root-owned) |
```

### 5.7 `:302` — worktrees attributed to `check` alone

`pipeline/rollback.py:42-46` imports the same `_worktree` helpers and `:166` creates
`rollback-<target_version>`; the mechanism has its own section at
`release_flow.md § Worktree mechanism`. Rollback's use is not defensive — recompiling
the target version's `infra.yml` with the current `docex` is the point of the command.
Change:

```
`docex check` (and defensively, `docex merge`) needs to perform git operations against a merged state without disturbing the developer's working tree. The mechanism:
```

to:

```
`docex check` (and defensively, `docex merge`) needs to perform git operations against a merged state without disturbing the developer's working tree. `docex rollback` uses the same `pipeline/_worktree` helpers for a different reason: it checks out `v<target_version>` and recompiles that version's `infra.yml` with the *current* `docex`, which is the point of the command rather than a precaution (see [`release_flow.md § Worktree mechanism`](./release_flow.md#worktree-mechanism)). The mechanism:
```

Also, in step 1 of the numbered list immediately below, the path
`.docex/worktrees/check-<sha>/` is `check`'s. Leave it, but change "Create a temporary
worktree under `.docex/worktrees/check-<sha>/`" to "Create a temporary worktree under
`.docex/worktrees/<command>-<discriminator>/` (`check-<sha>`, `rollback-<version>`)".

### 5.8 `:410-433` — the `src/` tree omits `registry/`

`registry/` (`client.py` + `urllib_client.py`) is the only one of the 21 packages under
`src/docex/` unlisted, and the only client seam without a line. Insert it in the
adapter run, after the `secretsmgmt/` line at `:429` (keeping the tree's alignment and
box-drawing characters consistent with its neighbours):

```
│       ├── registry/          (container-registry HTTP adapter)
```

Verify the emitted tree's `├──` / `└──` characters still read correctly after the
insertion — `envfile.py` must remain the `└──` entry.

### 5.9 The Service Connect consumer reconcile is unmentioned in this file

§5.5 adds it to the Foundation-Aware table. Add one more line to
`### Cross-command orchestration` (the bullet list at `:161-166`), after the `release`
bullet §5.3 rewrites:

```
- `release` on elastic ends with a **Service Connect consumer reconcile** — the only step that reads AWS state written by its own apply, and the only one that mutates a service it did not just deploy. It runs on every elastic branch including rollback. See [`release_flow.md § Elastic-foundation flow`](./release_flow.md#elastic-foundation-flow) step 4.
```

---

## §6. `plans/core/test_projects.md` and the seed projects

### 6.1 `plans/core/test_projects.md:9-10` — wrong domains (docex half, no seed cadence)

Every artifact uses `docex-smoke-fixed` / `docex-smoke-elastic`: both seeds'
`project.yml` names, both masterplans, the checklist, `verify_clean.sh`'s
`PROJECT_NAME`. Change `Domain: \`doctrine-fixed.luxrnd.tech\`` to
`Domain: \`docex-smoke-fixed.luxrnd.tech\`` on `:9`, and
`Domain: \`doctrine-elastic.luxrnd.tech\`` to
`Domain: \`docex-smoke-elastic.luxrnd.tech\`` on `:10`. Leave the rest of both bullets
untouched.

### 6.2 Seed edits — apply to BOTH seeds unless a step says otherwise

`test_projects/fixed/` and `test_projects/elastic/` are **separate git repos**. Make
all edits in both, then follow §6.3's cadence.

**(a) `plans/core/api/db_schema.md:13` — `uuid7` (both).** `hex/pings/domain/ping.py:7,24`
imports and calls `uuid4()`. Both the function name and the stated *property* are
false — v4 is random. Change:

```
| `id` | `uuid` | Primary key. Generated by `api.web` at write time (`uuid7` for time-ordered insertion). |
```

to:

```
| `id` | `uuid` | Primary key. Generated by `api.web` at write time with `uuid4` (random; the table's ordering comes from `created_at`, not from the key). |
```

**Before writing this, confirm a `created_at` column exists in that same table.** If it
does not, drop the parenthetical's second clause rather than inventing a column —
report what you found.

**(b) `plans/core/api/db_schema.md:47` — "reversible" (both).**
`doctrine/practices/databases.md § Migrations` requires migrations to be "idempotent and
forward-only — the doctrine never reverses a schema, even on rollback". The *second*
sentence is mechanically true (both migrations in both seeds carry both markers) and is
kept, restated as a dbmate file-format fact rather than as evidence of reversibility.
Change:

```
Doctrine requirement: migrations are idempotent and reversible (`databases.md`). Each migration file declares both `-- migrate:up` and `-- migrate:down`.
```

to:

```
Doctrine requirement: migrations are idempotent and **forward-only** (`databases.md`) — the doctrine never reverses a schema, even on rollback, and `docex rollback` runs no migration at all. Each migration file still declares both `-- migrate:up` and `-- migrate:down` because that is dbmate's file format; the `down` half is not a rollback path the pipeline ever takes.
```

**(c) `elastic/plans/core/masterplan.md:38-41` — hostnames missing the codebase
segment (ELASTIC ONLY).** Compiled output is `api-web.dev.…`. The fixed companion states
the canonical form at `fixed/plans/core/masterplan.md:33`; align to it. Change the four
bullets from `<service>.` to `<codebase>-<service>.`, and add the "two segments in one
DNS label" gloss the fixed seed uses:

```
Per-env hosts compile to the doctrine's canonical form `<codebase>-<service>.<env>.docex-smoke-elastic.luxrnd.tech` — two segments in one DNS label, hyphen-joined:
- `api-web.dev.docex-smoke-elastic.luxrnd.tech` (local, served by the dev-side per-project Traefik)
- `api-web.test.docex-smoke-elastic.luxrnd.tech` (local, same)
- `api-web.stage.docex-smoke-elastic.luxrnd.tech` (project ALB, stage cert)
- `api-web.prod.docex-smoke-elastic.luxrnd.tech` (project ALB, prod cert)
```

`api.web` is the only `web`-network core service in these seeds, so `api-web` is the
right literal. **Confirm that against `elastic/infra/infra.yml` before writing it** —
if another core service is on the `web` network, keep the placeholder form
`<codebase>-<service>` instead of naming one, and report.

**(d) `core/api/test.sh` — five of seven test files (both).** The script globs
`/service/tests`, so behavior is correct and only the comment's enumeration is short.
Missing: `test_jobs_alogic.py` (alogic tier for `jobs`, per its own docstring →
`api.worker`) and `test_jobs_drain.py` ("the drain boundary: `api.web` asking
`api.worker` to drain" → spans both). Change:

```sh
# One suite per codebase, not per core service: this globs the whole
# tests/ folder, covering api.web (test_smoke.py), api.worker
# (test_processor_smoke.py, test_jobs_smoke.py, test_jobs_concurrency.py)
# and api.clock (test_clock_smoke.py) in one run.
```

to:

```sh
# One suite per codebase, not per core service: this globs the whole
# tests/ folder, covering api.web (test_smoke.py), api.worker
# (test_processor_smoke.py, test_jobs_smoke.py, test_jobs_concurrency.py,
# test_jobs_alogic.py), api.clock (test_clock_smoke.py), and the
# api.web -> api.worker drain boundary (test_jobs_drain.py) in one run.
# The glob is the authority: this list is orientation, not a manifest.
```

**Re-count the files before writing** (`find tests -name 'test_*.py'`). If the count is
not seven, list what you found and report rather than adjusting silently.

**(e) `plans/core/api/hex/processor.md:30` — "out of scope for this seed" (both).**
`FOR UPDATE SKIP LOCKED` is implemented at
`core/api/src/hex/jobs/adapters/driven/queue_jobs_postgres.py:68` and treated as
load-bearing by four other seed docs (`db_schema.md:35`, `hex/jobs.md § Concurrency`,
`api.md:127`, `masterplan.md`'s flow 7).

**Keep the module boundary.** `processor` polls `pings` and genuinely does not
coordinate with sibling replicas — that part is true. The false part is the
parenthetical's generalization to the whole seed. Change:

```
- `processor` does not coordinate with sibling replicas. With `replicas: 2` in `prod`, two workers poll the same table; the smoke test tolerates the overlap because the "work" is a no-op. Real multi-worker coordination (advisory locks, `FOR UPDATE SKIP LOCKED`) is out of scope for this seed — and note that `replicas` is honoured in `prod` only, so this is the one shape `dev`, `test`, and `stage` cannot rehearse.
```

to:

```
- `processor` does not coordinate with sibling replicas. With `replicas: 2` in `prod`, two workers poll the same table; the smoke test tolerates the overlap because the "work" is a no-op. Multi-worker coordination is **not** out of scope for the seed — the `jobs` module claims its batch with `SELECT … FOR UPDATE SKIP LOCKED` for exactly this race (see [`jobs.md`](./jobs.md#concurrency)) — it is out of scope for *this module*, whose work is a no-op and so has nothing to contend over. Note also that `replicas` is honoured in `prod` only, so this is the one shape `dev`, `test`, and `stage` cannot rehearse.
```

**Verify the `jobs.md` link target** — check that `plans/core/api/hex/jobs.md` has a
heading whose anchor is `#concurrency`. If the heading differs, use the real anchor.

**(f) Four dead prose citations.** None are markdown links, so nothing mechanical
resolves them. Fix the *text* only; do not convert them into markdown links.

| File:line | Written | Replace with |
| --------- | ------- | ------------ |
| `fixed/infra/infra.yml:30` | `cicl.md § Field scoping` | `cicl_reasoning.md § Field Scoping` |
| `elastic/infra/infra.yml:36` | `cicl.md § Field scoping` | `cicl_reasoning.md § Field Scoping` |
| `fixed/infra/infra.yml:163` | `cicl.md § Three clarifications` | `cicl.md § Validation Rules, rule 7` |
| `elastic/infra/infra.yml:179` | `cicl.md § Three clarifications` | `cicl.md § Validation Rules, rule 7` |
| `elastic/infra/infra.yml:17` | `cicl.md § Container Registry` | `cicl.md § Container Registry and Service Images` |
| `fixed/verify_clean.sh:21-23` | `transfer_tables.md\n§ naming` | `transfer_tables.md\n§ Naming Policies` |

Notes: "Field scoping" appears nowhere in `cicl.md`; the heading is `### Field Scoping`
in `doctrine/infrastructure/reasoning/cicl_reasoning.md:9`. "Three clarifications" is
prose inside rule 7 (`cicl.md:593`), not a heading. The `verify_clean.sh` citation
spans two comment lines — keep the line break where it is and adjust only the section
name.

**These are YAML and shell comments. Do not disturb the surrounding syntax.** After
editing both `infra.yml`s, confirm each still parses (§8 covers this).

### 6.3 Seed cadence — mod 130's, mandatory

Walk precondition A.2.1 is *on `main`, clean, tag at HEAD*, and the smoke walks run
immediately after this mod. For **each** seed, in this order:

1. Confirm the seed is on `main` with a clean tree before you start.
2. Bump `project.yml`'s `version` by one patch: `fixed` `0.0.19` → `0.0.20`,
   `elastic` `0.0.23` → `0.0.24`. **Leave `docex_version: "1.7.0"` alone.**
3. Add a `CHANGELOG.md` entry for the new version in the seed's own changelog, in
   `keepachangelog` form, describing the doc corrections.
4. Commit inside the seed. Message: `docs: correct db_schema, test.sh, processor and citation claims (mod 134b)` — plus, for `elastic` only, the hostname fix.
5. Force-move the tag to the new HEAD: `git tag -f v0.0.20` / `git tag -f v0.0.24`.
6. Verify with `git rev-parse --verify "v<version>^{commit}"` and compare to
   `git rev-parse HEAD`. **Use `--verify`, not a shell `||` fallback** — `git
   rev-parse` prints the ref name to stdout on failure, which silently concatenates
   and produces a false negative.

Then, in the **outer** repo, stage the seed pointer updates as part of §9's commits
(the seeds are nested working trees; the outer repo tracks their contents, so their
changed files appear as ordinary outer-repo changes — stage them normally).

---

## §7. The three bookings — two new brief files

Create these in `plans/advances/007_small_edges/`, matching the existing
file-per-brief prose shape in that directory (read `inert_elastic_defaults.md` for
the register: a "Found" line, the finding with code excerpts, why it is worth a brief,
the real question stated but **not answered**, and a "Where to look" list).

**These are bookings. Do not implement any of them.**

### 7.1 `traefik_acme_email_unwired.md`

Two findings in one file, because they share a root cause: `emit_hcl_project`'s
template context is assembled ad hoc at its single call site rather than derived.

**Finding 1 — the ACME account email is permanently a placeholder.**
`emit/hcl.py:1167` declares `traefik_acme_email: str | None = None`; `:1253` resolves
`acme_email = traefik_acme_email or f"docex@{apex_domain}"`; `:1260` passes it to the
template, which writes it at `ec2_traefik_user_data.sh.j2:142` as the Let's Encrypt
account email. The only production call site — `cicl/compile.py:1372-1379` — never
passes it. So on both `ec2_traefik` variants the ACME account email is always
`docex@<apex_domain>`, an address that need not exist. Class-3: documented, not
implemented. Note *why* it is invisible: the fallback makes the emitted artifact
**valid**, so no gate fires and both smoke walks pass. The real question — whether the
account email belongs in `infra.yml`, in `project.yml`, or in config — is stated and
left open, along with what Let's Encrypt actually uses the address for (expiry notices,
account recovery) and therefore how much it matters.

**Finding 2 — two template sites diverge from `naming.dns_label`.** Four sites
re-derive the project segment inline; `project.tf.j2:325` and `main.tf.j2:63` omit
`| lower` while `main.tf.j2:128` and `:130` include it. `project_dns_label` never
enters HCL template context. `naming.dns_label` is
`name.replace("_", "-").lower()`, and nothing validates `project.yml`'s `name` to
lowercase (`context.py` applies no pattern).

State this as a **failure mode**, not an inconsistency. A project named `MyProject`
compiles, in one run, to two spellings of its own segment: `MyProject-traefik` (the
project traefik ASG/instance) and `MyProject-<env>-<short>` (env-tier security groups)
against `myproject-<env>` (the Service Connect namespace) — and everything routed
through `apply_policy` / `dns_label`, plus the entire fixed side via
`project_dns_label`, gets `myproject`. On a case-sensitive AWS name those are different
resources. No test catches it because **no fixture has a capital letter**, and nothing
rejects one.

Say plainly that the fix is **not** to patch four Jinja sites — that leaves the fifth
author to re-derive it — but to normalize or validate the project name where it enters
docex, so `dns_label` is idempotent on it. Name the cost: that is a behavior change,
rejecting or silently rewriting names that compile today, which is why mod 134b booked
it. Leave open which of reject-vs-normalize is right.

### 7.2 `merge_changelog_gate_unenforced.md`

**Found:** advance 006, mod 134b, while verifying `masterplan.md`'s Filesystem Surface.

`doctrine/infrastructure/version_control.md § Updating`: "Any time a version number is
incremented, an update should be added to the changelog." `docex merge` is the command
that bumps-and-tags `v<version>`. **No code in `docex` reads `CHANGELOG.md`** — grep
across `src/` returns zero hits.

The part worth recording is *how the absence stayed invisible*:
`masterplan.md:201` asserted `CHANGELOG.md` was "referenced by `merge` for version-bump
validation", so the core doc claimed the gate existed. Mod 134b deleted that line; this
brief is what stops the deletion also deleting the finding. This is the advance's
signature defect shape — a documented obligation with no enforcement, and a document
asserting the enforcement — arriving in the release process itself.

State the question and do not answer it: **should `merge` gate on a changelog entry,
and on what?** Name the candidate predicates and the objection to each — a
`## [<version>]` heading matching `project.yml` (brittle if the project's changelog
format drifts from keepachangelog); a non-empty `## [Unreleased]` section (gates the
wrong artifact, since the section is emptied *by* the release); a non-empty diff
against the previous tag (permissive to the point of meaninglessness). Also name the
prior-art constraint: the doctrine's own `RELEASING.md` walks a changelog step by hand,
so a gate here would be the first mechanical enforcement of it, and whether it belongs
in `merge` or in `check` is itself open.

### 7.3 Do not create a third file

§7.1 carries two findings and §7.2 carries one. Three findings, two files, by design.

---

## §8. Verification

Run all four, from `/home/ubuntu/.claude/jean_baudrillard/docex`. **The pytest
invocation form is load-bearing** — three plausible variants report a believable wrong
number. Never bare `pytest`; never both `-m` flags in one invocation; never from the
repo root (`pytest docex/tests` cannot import `tests.conftest`, reports one deselect
short, collects nothing, and does not fail loudly).

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
./.venv/bin/python -m pytest tests -q                    # expect 1199 passed, 21 deselected
./.venv/bin/python -m pytest tests -q -m integration     # expect 21 passed, as a SEPARATE run
```

Then the two cohere-executor scripts, from the repo root (paths verified):

```
cd /home/ubuntu/.claude/jean_baudrillard
python3 skills/cohere/executor/linkcheck.py
python3 skills/cohere/executor/verify_examples.py
```

Both must be green. `linkcheck` is the one most likely to react to this mod — §3.3,
§3.6, §4.1, §5.3, §5.7 and §6.2(e) all add or change markdown links, so a wrong anchor
shows up here. Note that `linkcheck` **cannot** see the prose citations in §6.2(f) or
the one in §1.1, which is exactly why those were found by hand.

**Counts must match the baselines exactly.** This mod changes no behavior, so any
delta in passed/deselected is a defect you introduced — most likely a broken YAML
comment in a seed `infra.yml` or the `worker.yml` table. Report the exact numbers.

Additionally, confirm the two edited seed `infra.yml` files still parse:

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
./.venv/bin/python -c "import yaml,sys; [yaml.safe_load(open(p)) for p in sys.argv[1:]]; print('yaml ok')" \
  test_projects/fixed/infra/infra.yml test_projects/elastic/infra/infra.yml
```

And that `worker.yml` still parses with `fields` as an empty mapping:

```
./.venv/bin/python -c "import yaml; d=yaml.safe_load(open('tables/roles/worker.yml')); print('worker.yml ok')"
```

---

## §9. Commits

**Do not commit until all four verifiers are green.**

Seed commits happen inside each seed per §6.3. In the **outer** repo, make **two**
commits:

1. Everything in §1–§6 (the corrections), including the seed file changes.
2. §7 (the two brief files).

Write real commit messages in the register of this repo's history — state what was
wrong and why it mattered, not a list of files. End each with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

Do **not** update the top-level `CHANGELOG.md` — that belongs to the mod cycle's
documentation step, which is not yours.

## §10. Report back

- Every step you completed, and any you could not, with the reason.
- **The four verifier results as exact numbers.**
- The five places §6.2 asks you to confirm something before writing (`created_at`,
  the `web`-network core service list, the test-file count, the `jobs.md#concurrency`
  anchor, and whether both `infra.yml`s parse) — say what you found in each, even
  where it confirmed the expectation.
- A.2.1's state for both seeds after your commits: branch, clean/dirty, version, and
  the `git rev-parse --verify "v<version>^{commit}"` output against `git rev-parse
  HEAD`.
- Anything you found that looks like the same defect class but is outside these steps.
  **Report it; do not fix it.**
