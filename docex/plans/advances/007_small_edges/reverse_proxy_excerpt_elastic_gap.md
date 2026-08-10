# `why reverse_proxy` presents the ALB as elastic's only answer

## Summary

[`doctrine_excerpts/reverse_proxy.md`](../../../doctrine_excerpts/reverse_proxy.md)'s
elastic bullet reads *"**Elastic: AWS ALB.** One ALB per environment …"* as though the
ALB were the only elastic ingress primitive the doctrine offers. It is not. CICL's
`reverse_proxy:` field accepts **`alb`** *and* **`ec2_traefik`**, and `docex` implements
both — the ECS-provider `traefik.*` labels on `web` task definitions
(`emit/hcl.py::render_task_definition`, the `dockerLabels` block) plus the instance's
static config in `templates/ec2_traefik_user_data.sh.j2`. Both were verified end to end
against real AWS in the 1.4.3 campaign. The excerpt predates the option and has never
been updated.

## Why mod 131 did not fix it

Mod 131 was an **alignment sweep**: replacing statements that went false during advance
006 with what shipped. Covering `ec2_traefik` means writing *new* prose about a
foundation option — when to pick it, what it costs, how it differs from an ALB — which is
authorship, not sweeping. The operator ruled it out of scope at that mod's design review
and booked it here instead.

Mod 131 *did* fix the same file's other defect, an **inverted** fixed-side topology claim
("exactly one traefik instance per host machine — *not* one per project", the opposite of
the project-tier traefik `shape.md` specifies). That one was one clause, verifiable, and
directly contradicted sentences mod 131 was itself writing.

## Why it matters

`docex why reverse_proxy` is precisely what an operator asks *while choosing* an ingress
primitive. Today it cannot surface the choice: the reader concludes the decision has been
made for them and reaches for an ALB, which is the more expensive of the two and the wrong
answer for a small elastic project that would rather pay for one t-class instance than an
hourly ALB.

## Shape of the fix

Rewrite the elastic bullet as a two-option bullet, mirroring how the fixed bullet now
reads:

1. **`alb`** — the default. One ALB per environment in the env's public subnets, 443 with
   the project's ACM cert, doctrine-provisioned rather than declared. Doubles as the load
   balancer for replicated `web` core services in `prod`.
2. **`ec2_traefik`** — a single small EC2 instance running traefik, discovering routes
   from the `traefik.*` `dockerLabels` the compiler emits onto `web` task definitions.
   Label-driven, not release-pushed: there is no SSM routing parameter.
3. What the choice turns on, in one sentence each — cost, TLS termination point, and
   whether ECS-native target-group health checking is wanted.

Rule of record to cite: `cicl.md`'s `reverse_proxy:` field and
`infrastructure/specifics/projinfra/ec2_traefik.md`. Read them before writing; this brief
deliberately does not restate them.

## The standing lesson

This is one of the defects advance 006's sweep found in **nine of the eighteen**
excerpts, of which the vocabulary grep three mods relied on found exactly **one** — and
it is among the eight found only by the completeness pass, since it is an omission rather
than a changed claim and predates the advance entirely. (The four still open are booked
at [`doctrine_excerpts_stale_entries.md`](./doctrine_excerpts_stale_entries.md); note the
count is cited here as a **proportion** rather than an ordinal, because "the third defect"
is exactly the kind of static number that goes wrong the moment a fifth is found.) That is
the evidence behind
[`docex_process.md § Additional Artifacts`](../../core/docex_process.md#additional-artifacts)'s
sweep rule: the vocabulary grep answers "did a claim change", and a second pass must read
every entry naming a **set** and ask whether the set is still complete.

## Not blocking

Nothing is broken. Both primitives work; only the excerpt is incomplete, and an operator
who reads `cicl.md` directly finds the option. The argument for closing it is that
`docex why` exists so an operator does not have to.
