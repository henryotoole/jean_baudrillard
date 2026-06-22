# Mod 054 — Dev DNS gate + `test` cert/route exclusion

First mod of the `001_skill_update` campaign. Closes the planner's "DNS and
Certs for development-side" item.

## The problem

Bringing up a fixed-style env (any `envinfra up dev`, and historically every
`docex test`) makes the per-project traefik fire an ACME **HTTP-01** challenge
for each `web`-service hostname in that env. HTTP-01 only succeeds if the
hostname resolves publicly to the machine on `:80`. Two failure shapes follow
from the current behaviour:

1. **`dev` with no DNS.** The inception flow never required dev DNS before the
   dev smoke test, so the first `envinfra up dev` on a fresh project routinely
   hits hostnames that don't resolve. Each failed challenge counts against
   Let's Encrypt's **5-failed-authorizations-per-hour** limit; once tripped, it
   also blocks *legitimate* issuance for an hour.
2. **`test` fetching certs at all.** The `test` env is ephemeral and exercised
   entirely by `test.sh` running inside containers, reaching peers on the
   internal network by container name. It never needs public TLS — yet today it
   carries the same `tls.certresolver=doctrine` labels as every other env, so it
   burns LE authorizations for hostnames nobody will ever browse to.

## Decisions (from design discussion)

- **`test` is removed from web routing entirely** (not merely from TLS). `test`
  web services get *no* traefik discovery labels — no router, no `tls`, no
  certresolver. They still join the `-web` network (harmless); they're simply
  not proxied. Truest reading of the planner's "remove the mapping to `test`
  entirely from both DNS and cert fetching."
- **Dev DNS is operator-routed and verified, not auto-created.** Rather than
  have the AWS-free dev side reach into Route53, both foundations treat dev DNS
  uniformly: the operator routes it (registrar or Route53, per the project), and
  `preinfra development` **verifies** that each `dev` web hostname resolves in
  public DNS, failing loudly if not. Because `envinfra up dev` already refuses
  when `preinfra development` fails, this gate sits exactly upstream of the LE
  risk.
- **Resolution uses `dnspython`, not stdlib `getaddrinfo`.** `getaddrinfo`
  consults `/etc/hosts`; a dev who added local host entries would get a false
  pass, then `envinfra up dev` proceeds and LE — which resolves *publicly* —
  still NXDOMAINs and trips the limit. `dns.resolver` queries the configured
  nameservers and ignores `/etc/hosts`, so it sees what LE sees. It is bundled
  in the docex image; no burden on projects.

## Doctrine status

Doctrine changed first, per `docex_process.md`. All edits are landed:

- `cicl.md § TLS Implications` (operator): "TLS is only maintained for the
  `dev`, `stage`, and `prod` env-domains. The `test` env is not accessed via SSL
  in practice."
- `inception.md` PART III (operator): added "Route DNS to `dev`" as a step
  before the `preinfra development` check, and `projinfra up development` before
  the dev bring-up.
- `docex.md § preinfra` (this mod): documents that the `development` side
  verifies each `dev` web hostname resolves in public DNS, and why.
- `specifics/projinfra/fixed_reverse_proxy.md` (this mod): dropped `test` from
  the cert-issuance clauses (now `dev`/`stage`/`prod` on fixed; `dev`-only on the
  elastic dev side) and noted `test` web services are not routed.

No further doctrine gap surfaced. If implementation uncovers one, stop and raise
it before editing any doctrine file.

## Why the gate is a no-op during inception step 3

The operator's inception ordering runs `preinfra development` (step 3) *before*
`infra.yml` is written (step 4). At that point there are no dev hosts to derive,
so the DNS check is skipped (`ctx.infra is None`). The protective gate is the
*second* invocation — the one `envinfra up dev` performs (step 9), by which time
`infra.yml` exists. The standalone step-3 run still does its job: checking the
`docex-ingress` bridge. This matches every other `ctx.infra is not None`-guarded
check already in `preinfra.py`.

## Artifacts touched

- `doctrine/**` — see above (rule of record).
- `src/docex/emit/compose.py` — suppress traefik labels for `test`.
- `src/docex/dns/{client,dnspython_resolver}.py` — new `DnsResolver` seam.
- `src/docex/cicl/compile.py` — public `web_hostnames_for_env` host-derivation
  helper (single source of truth, reused by the preinfra check).
- `src/docex/pipeline/preinfra.py` — `_check_dev_dns` development-side branch.
- `src/docex/__main__.py` — construct + inject the resolver at the dev-side
  `run_preinfra` call sites.
- `pyproject.toml` — add `dnspython`.
- `tests/**` — emit label exclusion + preinfra DNS-check behaviour.
