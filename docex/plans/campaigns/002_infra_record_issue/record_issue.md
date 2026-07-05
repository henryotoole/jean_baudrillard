# docex teardown: child hosted zone won't delete (`HostedZoneNotEmpty`)

**Audience:** docex developer, cutting a patch release.
**Component:** `docex projinfra down production` (elastic foundation, Route53 child zone).
**Severity:** teardown-blocking — leaves orphaned AWS resources and a stuck retire.
**Observed on:** docex **1.4.3**, 2026-07-05, project `tactical_lifecycle_test`
(elastic, single `web` service, `apex_domain: luxedo.cc`).

---

## Symptom

`docex projinfra down production` destroys everything except the last resource, then
fails:

```
aws_route53_zone.project: Destroying... [id=Z0730163OOQWCNVRXH7O]
Error: deleting Route53 Hosted Zone (Z0730163OOQWCNVRXH7O): operation error
  Route 53: DeleteHostedZone, StatusCode: 400, HostedZoneNotEmpty:
  The specified hosted zone contains non-required resource record sets and so
  cannot be deleted.
error: project-tier 'tofu destroy' exited 1
```

At that point the whole prod-tier stack (VPC, NAT, ALB, ACM, ECR, ECS, state backend)
is already gone — **only the child hosted zone survives**, and it can't be deleted
because it still holds records that are **not in tofu state**.

The records blocking it, in this run:

```
tactical-lifecycle-test.luxedo.cc.        NS    (required — fine)
tactical-lifecycle-test.luxedo.cc.        SOA   (required — fine)
dev.tactical-lifecycle-test.luxedo.cc.    A     <-- blocks delete
web.dev.tactical-lifecycle-test.luxedo.cc. A    <-- blocks delete
```

## Root cause — a zone-ownership / lifecycle mismatch

This is **not** a stray-record fluke; the ordering of the doctrine flow forces those
records into the child zone, where tofu doesn't own them:

1. **Inception** routes dev DNS. At that point no child zone exists, so the dev `A`
   records (`dev.<project>.<apex>`, `web.dev.<project>.<apex>`) are created in the
   **parent** apex zone (`luxedo.cc`).
2. **`projinfra up production`** creates the child hosted zone
   `<project>.<apex>` and writes an **`NS` delegation** for it into the parent zone.
   From that moment the parent is no longer authoritative for *anything* under
   `<project>.<apex>` — **including `dev.<project>.<apex>`**. The dev records in the
   parent are now shadowed by the delegation, and **dev DNS breaks**.
3. To restore dev resolution, the dev `A` records get **re-created inside the child
   zone** (in this run the on-box inception agent did this explicitly, noting the
   "delegation shadows dev DNS" interaction). They are created **out-of-band** — via
   the AWS API / dev routing, **not** through the production-tier tofu that owns the
   zone.
4. **Teardown** (`projinfra down production`) `tofu destroy`s the zone, but tofu only
   knows about the records *it* created (NS/SOA). The out-of-band dev `A` records
   remain, so AWS rejects the zone delete → `HostedZoneNotEmpty`.

**Key point:** you cannot fix this by "putting the dev records somewhere else." Once
the entire `<project>.<apex>` subtree is delegated to the child zone, dev *must* live
in the child zone or it stops resolving. The dev records legitimately belong there;
what's wrong is that **the teardown assumes the zone only contains tofu-managed
records**, which is not true whenever dev DNS (or anything else added out-of-band, e.g.
lingering ACM validation CNAMEs) touches the zone.

## Two related teardown gaps (same lifecycle seam)

Whatever fix you choose, please also close these — they showed up in the same run and
have the same "docex created it but doesn't clean it" shape:

- **Dangling parent NS delegation.** After the child zone is (eventually) destroyed,
  the `NS` delegation record docex wrote into the parent apex zone
  (`<project>.<apex> NS ...`) is **left behind**. Any later run then SERVFAILs on that
  subtree (a delegation to now-dead nameservers). docex created the delegation on
  `up`; it should delete it on `down`.
- **Stale ACM DNS-01 validation records.** ACM validation CNAMEs written into the zone
  during cert issuance are another class of "non-required" record that can block the
  same delete if they aren't torn down in the right order. A force-empty (below) covers
  these too.

## Suggested fix — make zone teardown robust, don't try to police who writes records

Trying to guarantee "nothing ever writes to the zone out-of-band" is a losing battle
(dev DNS legitimately needs to). Instead, make the destroy tolerant:

1. **Set `force_destroy = true` on the child-zone resource** that docex emits for the
   production-tier Route53 zone (the `aws_route53_zone` that becomes
   `aws_route53_zone.project` in the compiled `infra/output/project/production` HCL).
   `force_destroy` makes the AWS provider delete *all* records in the zone (not just
   NS/SOA) before deleting the zone — so any out-of-band dev `A` records, stray ACM
   CNAMEs, etc. are swept automatically and `HostedZoneNotEmpty` cannot occur.
   *This is the one-line, highest-leverage change.*

2. **Delete the parent-zone `NS` delegation on `projinfra down production`.** docex owns
   the delegation record it created in the apex zone on `up`; the corresponding `down`
   should remove it (ideally as a tofu-managed resource in the same config so destroy
   handles it, rather than an imperative step). This closes the dangling-delegation
   SERVFAIL for the next run.

### Why `force_destroy` is safe here

- The zone is a **per-project, production-tier resource** docex fully owns; on
  `projinfra down production` the operator's intent is unambiguously "destroy the
  project's DNS." There is no case where we want to keep the zone but drop its records.
- It only affects **destroy**; normal operation is unchanged.
- It removes an entire class of manual-cleanup toil (today the operator has to
  `aws route53 change-resource-record-sets` the leftover records by hand, then re-run
  `projinfra down`, then hand-delete the parent NS record).

### Acceptance criteria

- `projinfra down production` succeeds in **one pass** on a project whose child zone
  contains dev `A` records and/or ACM validation CNAMEs (i.e. reproduce the scenario:
  inception → `projinfra up production` → dev routing lands records in the child zone →
  `projinfra down production`). No `HostedZoneNotEmpty`.
- After `down`, the parent apex zone (`luxedo.cc`) contains **no** `NS` (or other)
  records for `<project>.<apex>`.
- No orphaned Route53 zones or delegation records remain; a subsequent fresh
  inception/`up` for the same name resolves dev/stage without SERVFAIL.

## Manual workaround (until the patch ships)

For anyone tearing down before the fix lands:

1. `aws route53 list-resource-record-sets --hosted-zone-id <child-zone-id>` → delete
   every non-`NS`/`SOA` record (`change-resource-record-sets` with `DELETE`).
2. Re-run `./bin/docex projinfra down production` → the now-empty zone destroys and the
   state backend is removed (exit 0).
3. Delete the leftover parent delegation:
   `aws route53 change-resource-record-sets` `DELETE` the
   `<project>.<apex> NS` record from the apex zone.

## Out of scope for this doc (related but separate bug)

The **UI retire flow** (`Torpedo`) separately wedges on docex 1.4.3 because the
backend-orchestrated teardown appears to cancel/kill long-running `tofu destroy` steps
(`envinfra down stage`, `projinfra down production`) partway — distinct from the record
problem above (which only surfaced when teardown ran to completion over SSH). That's an
orchestration-timeout issue on the Periscope side, not a Route53/docex-template issue;
flagging it here only so the two aren't conflated. The record fix above is what frees
the `docex`/tofu teardown itself.
