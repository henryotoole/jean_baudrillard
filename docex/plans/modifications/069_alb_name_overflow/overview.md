# Mod 069 — ALB / target-group name overflow

## Problem

The elastic ALB path forms AWS `name` identifiers for the ALB
(`aws_lb`), the ALB security group (`aws_security_group`), and each
web-network service's target group (`aws_lb_target_group`). All three
go through `apply_policy(..., alb_policy)`, and the `alb` policy caps at
`max_len: 32`. Today `apply_policy` **hard-errors** on overflow.

A `${project}-${env}-${service}-tg` target-group name overruns 32 for
all but the shortest project names — e.g. project `tactical-lifecycle-test`
yields `tactical-lifecycle-test-stage-web-tg` (36 chars), which fails
compile. This makes the default (`reverse_proxy: alb`) elastic path
unusable for realistically-named projects.

## Root understanding

The `name` on `aws_lb`, `aws_lb_target_group`, and `aws_security_group`
is an **AWS resource identifier** (unique per account+region, ≤32 chars)
— *not* the doctrine `Name` tag. The human-facing descriptive name
belongs in the `Name` tag, which has no such 32-char ceiling. So we are
free to collapse/truncate the identifier as long as it stays unique and
deterministic, and the descriptive name lives in the `Name` tag.

Two facts drive the fix:
1. The identifier just needs to fit 32 and stay unique/deterministic.
2. `render_target_group` currently emits **no tag block at all** — so
   the descriptive name has nowhere to live today. This already
   violates the elastic tagging convention (`cicl.md § Naming and
   Tagging`); the ALB and ALB-SG at the project tier already carry their
   standard tag blocks.

## Design (approved)

**Naming-policy `overflow` behavior.** Add an optional `overflow` field
to naming policies: `error` (default — today's hard-error, unchanged for
every existing policy) or `hash_truncate`. On `hash_truncate`, when a
rendered name exceeds `max_len`, keep a readable prefix and append
`-<h>`, where `<h>` is the first 6 hex chars of the SHA-256 of the full
internal (underscore-joined) name. Deterministic, always fits, and
collision-resistant across distinct inputs that share a truncated
prefix. The `alb` policy sets `overflow: hash_truncate`; all other
policies keep the implicit `error`.

This single `apply_policy` change fixes all three ALB-path identifiers
at once, because they all resolve through the `alb` policy.

**Target-group tag block.** Add the standard envinfra tag block to
`render_target_group` so the full descriptive name lands in the `Name`
tag (`${project}_${env}_${service}`), consistent with every other
env-tier elastic resource. Descriptor: `ALB-TG`.

## Doctrine (already applied — this mod aligns code to it)

- `transfer_tables.md § Naming Policies` — `overflow` schema field,
  Overflow column in the policy table (`alb` → `hash_truncate`),
  validation-rule note updated.
- `elastic_alb.md § Naming` — identifier-vs-`Name`-tag split documented;
  target-group row added.

## Non-goals

- No change to any policy other than `alb`'s `overflow` value.
- No change to how the `Name` tag itself is formed (it already carries
  the full descriptive name via `standard_tags`).
- ec2_traefik is out of scope (mod 070).

## Hash-collision note

6 hex chars = 24 bits ≈ 16.7M values. A project has a handful of
target groups; birthday-collision probability is negligible. The hash is
of the *full internal name*, so two names only collide if their SHA-256
prefixes collide — not merely if their truncated readable prefixes
match. If a future need for more headroom appears, widen the hash; 6 is
the chosen default.
