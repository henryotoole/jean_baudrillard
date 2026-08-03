# Mod 110 — Non-`web` networks regain egress

## Problem

`emit/compose.py::_network_section` emits every non-`web` env network with
`internal: true`. Docker's `internal` flag removes the bridge's masquerade rule
and drops traffic to/from off-subnet addresses, so a container attached **only**
to non-`web` networks has **no route to the internet at all**.

That is not what the doctrine says a non-`web` network is.
[`networks.md § networks: [internal]`](../../../../doctrine/infrastructure/specifics/networks.md)
promises ingress isolation and nothing about egress, and
[`networks.md § Egress`](../../../../doctrine/infrastructure/specifics/networks.md#egress)
states the fixed rule explicitly:

> outbound requests leave each container via Docker's normal `iptables`-managed
> NAT through the host's default route. **Nothing project-specific or
> doctrine-emitted is involved.**

The flag *is* a doctrine-emitted thing involved in egress. `internal: true`
appears nowhere in `doctrine/`, nowhere in `tables/`, and nowhere in
`plans/core/` — only at `emit/compose.py:136` and one test assertion. **This is
code drift from an already-correct rule of record, not a gap in the rule.**

## What the flag actually buys

Measured on Docker Engine 29.4.1:

| Property | `internal: true` | plain bridge, no published ports |
| --- | --- | --- |
| Egress to internet (incl. DNS) | **BLOCKED** | OK |
| Reachable from another docker network | BLOCKED | **BLOCKED** |
| Reachable from the host by container IP | **REACHABLE** | REACHABLE |
| Reachable by container name, same network | OK | OK |

Cross-network isolation does not come from the flag — it comes from Docker's
`DOCKER-ISOLATION-STAGE` rules between bridges. The host can reach into an
internal network exactly as easily as a plain one, because the gateway address
is in-subnet. **The flag's only effect is blocking egress.** Every ingress
property the doctrine's non-`web` network promises is already delivered by a
plain user-defined bridge with no published ports.

## Design

Stop emitting the flag. One line in `_network_section`. A plain bridge already
*is* the doctrine's non-`web` network.

### Rejected alternative: second bridge + `gw_priority`

The obvious workaround is to keep the `internal: true` network and attach every
internal container to a *second*, plain bridge carrying a high `gw_priority` to
supply the default route. Rejected on five grounds:

1. **`gw_priority` imposes a host version floor.** It needs Engine 28+. Under
   [DooD](../../core/masterplan.md#docker-outside-of-docker) it is the *host's*
   daemon that runs the compose stack, so docex's pinned in-image CLI does not
   cover it — every dev machine and every fixed prod host would have to clear
   the bar. If the key is ignored rather than rejected, default-route selection
   falls back to Docker's own ordering and egress becomes nondeterministic per
   env: works here, fails on the prod host.
2. **It doubles the network surface and adds a colliding identity.** Rule 5's
   uniqueness check already seeds five appended derivatives; a per-env egress
   bridge is a sixth. Deleting a flag adds none.
3. **Every internal container gains a second interface**, which apps that
   enumerate or bind interfaces — and the netns-sharing OTel sidecar — would see
   for no gain.
4. **The flagged network survives doing nothing.** Its isolation was never
   load-bearing, so the workaround preserves a flag whose sole effect it exists
   to route around.
5. **Blast radius.** Flag removal touches the emitter, one test, and a
   docstring. The two-network version touches the network section, every
   service's attachment list, the uniqueness rule, `describe`, and teardown.

The one thing the rejected design *can* express is per-**container** egress
(attach the bridge only where needed). That expressiveness is unreachable:
CICL has no syntax for "this process type gets egress", and egress is allow-all
on elastic. See [Non-goals](#non-goals).

## Consequences

**Foundation parity is restored.** On elastic the `internal` SG is self-ingress
plus **allow-all egress** (`0.0.0.0/0`) — deliberately, since Fargate tasks need
SSM and ECR to start. Today the same `infra.yml` yields a service that reaches a
third-party API on elastic `stage` and fails on fixed `stage`, violating
[masterplan goal 5](../../core/masterplan.md#goals) (foundation parity). After
this mod fixed matches elastic exactly.

**A latent fixed stage/prod telemetry break is closed.** The OTel sidecar pairs
via `network_mode: "service:<container>"`, so it inherits its partner's netns and
nothing else. A `worker` or `scheduler` process type on `networks: [internal]`
therefore had a sidecar with no route to `OBSERVABILITY_BACKEND_URL` —
doctrine-mandated Class-1 telemetry, silently dead in fixed `stage`/`prod`. It
hid in `dev`/`test` because the exporter there is `debug` (sidecar stdout, no
egress needed). Same hole for a worker calling an external API, and for
`build.sh` pulling dependencies inside the exec container.

**Why the bug read as obscure:** `-web` is projinfra-owned and a plain bridge, so
anything on `[web, internal]` has had egress all along. Only services on
non-`web` networks exclusively were ever affected.

**Migration is automatic but not hot.** Verified: on the next `up`, compose
detects the changed network config and reconciles it — stop container, remove
network, recreate, start. No manual `docker network rm`. But containers *do*
restart, so it is a brief env interruption rather than a no-op. Recorded in the
upgrade guide.

## Non-goals

Genuinely egress-less networks stay **deferred**, exactly as
[`networks.md § Egress`](../../../../doctrine/infrastructure/specifics/networks.md#egress)
("Constraining egress per network … is deferred") and
[`infrastructure.md § Deferred`](../../../../doctrine/infrastructure/infrastructure.md#deferred)
item 4 already have them. When that lands it must be a **declared, opt-in**
concept with an elastic half (SG egress rules) so the two foundations stay
symmetric — not the accidental byproduct of a compose flag nobody chose.

## Scope

| Artifact layer | Change |
| -------------- | ------ |
| `doctrine/.../networks.md` | One clarifying sentence naming the mechanism, so the flag cannot drift back. **Operator-approved.** |
| `docex/plans/core/*` | No change — no core doc mentions the flag. |
| `tables/roles/*.yml` | No change — networks are structural, not engine-emitted. |
| `src/docex/**` | `emit/compose.py::_network_section` — drop `"internal": True`; correct the docstring, which currently states the flag as if it were doctrine. |
| `tests/**` | Invert the existing assertion; add a regression test for the non-`web`-only case. |

## Design questions

None outstanding. The approach and the doctrine edit were both approved by the
operator before implementation.
