# Mod 072 — Robust Route53 child-zone teardown

## Origin

Campaign [`002_infra_record_issue`](../../campaigns/002_infra_record_issue/record_issue.md).
An elastic project (`tactical_lifecycle_test`, apex `luxedo.cc`) could not complete
`./bin/docex projinfra down production` on docex 1.4.3: `tofu destroy` tore down the
whole prod tier except the Route53 child zone, which failed with
`HostedZoneNotEmpty` and left an orphaned zone plus a dangling parent NS
delegation.

## Root cause

The child zone `<project>.<apex_domain>` legitimately ends up holding records that
the production-tier tofu — which owns the zone — never created:

- `dev`/`test` are always fixed-style and run on the dev machine, so their public
  DNS is routed **out-of-band** during inception. Once `projinfra up production`
  creates the child zone and the operator NS-delegates the *entire*
  `<project>.<apex_domain>` subtree, `dev.<project>.<apex_domain>` **must** resolve
  from the child zone — so the dev `A`-records come to live inside the child zone
  but outside tofu state.
- Stale ACM validation CNAMEs from renewal, and any other out-of-band record.

`tofu destroy` deletes only what tofu created (NS/SOA), so AWS refuses the zone
delete whenever an out-of-band record is present.

A second, related gap: the parent-zone NS delegation is left dangling after
teardown, `SERVFAIL`ing the subtree on the next run.

## Design decision (already settled with the operator)

Two changes, matching the doctrine edits already applied to
[`elastic_route53_zone.md § Teardown`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md#teardown)
and [`projinfra.md`](../../../../doctrine/infrastructure/specifics/projinfra/projinfra.md#two-phase-production-side-apply-elastic):

1. **`force_destroy = true` on the emitted `aws_route53_zone.project`.** The one-line,
   highest-leverage fix. On destroy the AWS provider sweeps *every* record in the
   zone (out-of-band dev `A`-records, stray ACM CNAMEs, everything) before deleting
   the zone, so `HostedZoneNotEmpty` cannot occur. Safe because the zone is a
   project-owned, production-tier resource and `projinfra down production` carries an
   unambiguous "destroy the project's DNS" intent; affects **destroy only**.

2. **Symmetric teardown reminder** printed on a successful `projinfra down
   production`. This is the corrected form of the campaign's "delete the parent NS
   delegation" suggestion. The campaign doc assumed *docex* created that delegation
   and should tofu-manage its removal — but docex **never** writes the parent
   delegation. Per doctrine ([`elastic_route53_zone.md § NS Delegation`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md#ns-delegation))
   the parent zone may be a third-party registrar, a different AWS account, or
   another team's zone — docex has no creds/scope there, so delegation is a **manual
   operator step** on `up`. Removal is therefore symmetrically a manual operator
   step on `down`. docex's role is to **print a reminder** — the mirror of the
   phase-1 `up` NS-record instructions — telling the operator to delete the
   `<project>.<apex_domain> NS` record from the parent zone.

### What is explicitly *not* done

- No attempt to make the parent delegation a tofu-managed resource (would break the
  third-party-registrar / cross-account delegation design).
- No transfer-table change. The zone is a **structural** project-tier resource
  emitted directly in `project.tf.j2`, not via a role/engine table.
- No policing of who writes records into the zone. `force_destroy` makes teardown
  tolerant instead — the correct posture given dev DNS legitimately writes there.

## Scope / versioning

Patch-sized (`1.4.3` → `1.4.4`). Two small changes (one template line, one print
helper) plus tests. No smoke-walk required for a patch cut. The cut itself is a
separate step (`RELEASING.md`), not part of this mod.

## Acceptance

- Compiled elastic project-tier `main.tf` carries `force_destroy = true` on
  `aws_route53_zone.project`.
- `projinfra down production` clean path prints a reminder naming the
  `<project>.<apex_domain> NS` record and the parent zone; reminder appears **only**
  on the success path (not on either refuse gate).
- Existing elastic-down refuse/clean tests still pass; new assertions cover both
  additions.
