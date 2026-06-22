---
stratum: conditional
---

# Elastic Route53 Zone

This file describes the Route53 hosted zone created on the production side of every elastic-foundation project, and the NS-delegation step that necessitates `projinfra up production`'s two-phase apply.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Resource

One hosted zone per project, covering `<project>.<apex_domain>` (e.g., `myproject.example.com`). Tags follow the doctrine-wide pattern from [transfer_tables.md § Per-resource (elastic)](../transfer_tables.md#per-resource-elastic).

The zone is created by `./bin/docex projinfra up production`. Once it exists, it owns all of the project's DNS records:
- The project ACM cert validation records (`_acme-challenge.*` CNAMEs) — populated when [`elastic_acm_certs.md`](./elastic_acm_certs.md) applies.
- The project's bare-form A-records (`<project>.<apex_domain>`, `prod.<project>.<apex_domain>`, `*.prod.<project>.<apex_domain>`, `stage.<project>.<apex_domain>`, `*.stage.<project>.<apex_domain>`) — populated by env-tier release alongside the reverse proxy.
- Any other env-tier per-service records added by future doctrine extensions.

Projects sharing an apex domain each get their own zone delegated from the parent. Multiple projects can coexist on `example.com` without colliding because each one owns only its `<project>.example.com` subtree.

## NS Delegation

The zone is only reachable from the public DNS chain once the operator NS-delegates from the parent. Until that delegation is in place, no public resolver can find any of the records in this zone — and that includes ACM's validation queries when it tries to verify the cert.

`./bin/docex projinfra up production` cannot perform the delegation itself. The parent zone might be:
- An apex domain at a third-party registrar (NameSilo, GoDaddy, etc.) — `docex` has no creds there.
- A parent Route53 zone in a different AWS account — `docex`'s project creds may not span it.
- A parent Route53 zone in the same account but managed by a different team — out of `docex`'s scope by policy.

The doctrine therefore makes delegation an explicit operator step, surfaced at the precise moment the operator needs to act on it.

### Operator workflow

1. Run `./bin/docex projinfra up production`. On the first invocation, it creates the state backend, then creates the Route53 zone via `tofu apply -target=aws_route53_zone.project`. The command prints the zone's NS records — typically four `ns-N.awsdns-NN.{com,net,org,co.uk}` names — along with next-step instructions, and exits cleanly.
2. The operator NS-delegates by going to the parent registrar (or parent zone), finding the `<project>` subdomain record, and setting its NS records to the four names printed in step 1.
3. The operator waits a few minutes for delegation to propagate (typical: 1–5 minutes; worst-case: an hour at some registrars).
4. The operator re-runs `./bin/docex projinfra up production`. Phase 2 begins.

## Two-Phase Apply Rationale

Without the split, `tofu apply` would attempt to create the ACM certs in parallel with the zone, and would hang at the validation step for up to 72 hours (ACM's validation timeout) waiting for DNS records that public resolvers can't see. The operator would learn of the problem only when the apply finally failed.

Splitting the apply into two phases — zone first, everything else after delegation — surfaces the delegation requirement at exactly the right point: after the zone exists and its NS records can be read, before any resource that depends on the zone being reachable starts trying.

### Phase 1 — zone only

If `aws_route53_zone.project` is not yet in OpenTofu state, the projinfra command runs:

```
tofu apply -target=aws_route53_zone.project
```

After the targeted apply succeeds, `docex` reads the zone's NS records from the apply output (or by `aws_route53_zone.project.name_servers`) and prints them with the next-step instructions. Exit code 0; phase 1 complete.

### Phase 2 — full apply

On the next invocation, `docex` observes that `aws_route53_zone.project` is already in state (via `tofu state list`), skips phase 1, and runs an untargeted `tofu apply`. The ACM certs validate against the now-reachable zone; the rest of the project-tier resources come up.

If the delegation hasn't actually propagated yet, ACM cert validation will fail the apply within its own retry window (much shorter than 72 hours when the zone is unreachable). The projinfra command surfaces the ACM error and hints at the delegation requirement — distinct from the original "I haven't done the delegation yet" error of phase 1.

### Phase detection

Phase detection is observed from `tofu state list`, not stored separately. The operator's mental model is single-command: `./bin/docex projinfra up production`, do the delegation work it asks for, `./bin/docex projinfra up production` again, done.

## Outputs Consumed Downstream

The project's `main.tf` declares the following outputs, all consumed by env-tier `main.tf` files via `data "terraform_remote_state" "project"`:

| Output | Used by |
| ------ | ------- |
| `zone_id` | Env-tier resources that add A-records or other records to the zone |
| `zone_name_servers` | The operator (via `terraform output`) when re-checking delegation |

The zone itself is never destroyed by `./bin/docex projinfra down production` *if any env still has resources in the zone* — the down command refuses to proceed in that case, matching the general projinfra-vs-envinfra layering rule from [projinfra.md](./projinfra.md#bindocex-projinfra-direction-side).

## Out of Scope

- **Apex zones.** The doctrine does not provision the apex zone (`example.com`). That's prerequisite infrastructure, owned by whoever owns the apex domain.
- **NS delegation itself.** As discussed; the operator does this manually between phase 1 and phase 2.
- **Cross-account DNS.** When the parent zone lives in a different AWS account, the operator's options for automating delegation (cross-account IAM, organizational delegation) are out of scope. They handle it the same way they would handle a registrar-side delegation.
