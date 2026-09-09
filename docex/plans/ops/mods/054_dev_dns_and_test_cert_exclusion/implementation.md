# Mod 054 — Implementation steps

Doctrine is already edited (see overview § Doctrine status). These steps cover
the `docex` code + tests only. Work from the repo root `~/.claude/jean_baudrillard/docex`.

## 1. Suppress traefik labels for the `test` env

`src/docex/emit/compose.py`, in `_service_block`'s label-assignment block
(currently ~lines 351–357):

```python
project_label = _docex_project_label(compiled.project_dns_label)
if svc.web_hosts and compiled.env != "test":
    block["labels"] = _traefik_labels(
        svc, compiled.project_dns_label, compiled.env,
    ) + [project_label]
else:
    block["labels"] = [project_label]
```

The only change is `and compiled.env != "test"`. Effect: a `test`-env web
service keeps its `docex.project` label (still needed so the project traefik's
docker-provider constraint behaves) but gets no router/`tls`/`certresolver`
labels, so traefik never issues an LE cert for it. Do **not** change
`_traefik_labels` itself — other envs still call it unchanged.

Update the comment above the block to note the `test` exclusion and why (per
`cicl.md § TLS Implications` / `fixed_reverse_proxy.md`).

## 2. New `DnsResolver` seam

Mirror the existing client pattern (`docker/client.py` Protocol +
`docker/subprocess_client.py` impl).

**`src/docex/dns/__init__.py`** — empty package marker.

**`src/docex/dns/client.py`**:

```python
from __future__ import annotations
from typing import Protocol


class DnsResolver(Protocol):
    """Abstraction over public-DNS resolution. The runtime impl is
    dnspython-backed (``dnspython_resolver.py``); unit tests inject a
    fake. Deliberately queries configured nameservers, NOT ``/etc/hosts``
    — the check must see what Let's Encrypt sees."""

    def resolves(self, hostname: str) -> bool:
        """True iff ``hostname`` has at least one A/AAAA record in public
        DNS. False on NXDOMAIN / empty answer. Network/transient errors
        propagate (the caller treats an exception as a check it could not
        complete, distinct from a confirmed non-resolution)."""
        ...
```

**`src/docex/dns/dnspython_resolver.py`**:

```python
from __future__ import annotations
import dns.resolver


class DnspythonResolver:
    """Default ``DnsResolver`` — queries the system's configured
    nameservers via dnspython. Ignores ``/etc/hosts`` by construction."""

    def resolves(self, hostname: str) -> bool:
        for rdtype in ("A", "AAAA"):
            try:
                answer = dns.resolver.resolve(hostname, rdtype)
                if len(answer) > 0:
                    return True
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                continue
        return False
```

(NXDOMAIN/NoAnswer → keep trying the other rdtype, then `False`. `NoNameservers`
/ `Timeout` etc. should propagate so the caller can distinguish "couldn't check"
from "confirmed missing" — handle that in step 4's wording.)

## 3. Host-derivation helper (single source of truth)

`src/docex/cicl/compile.py` — add a public function reusing the existing
`_web_hosts`, `_env_subdomain`, `_bare_project_subdomain`:

```python
def web_hostnames_for_env(doc, project_name: str, env: str) -> list[str]:
    """Every public web hostname for ``env``, order-stable + deduped.
    Same derivation the compiler uses for routing, so the preinfra DNS
    check and the emitted traefik routers never drift."""
    subdomain = _env_subdomain(doc.apex_domain, project_name, env)
    bare_project = _bare_project_subdomain(doc.apex_domain, project_name)
    hosts: list[str] = []
    for name, svc in _iter_services(doc):   # mirror compile_env's own iteration
        hosts.extend(_web_hosts(
            name, svc.networks, subdomain, doc.domain_default_service,
            env=env, bare_project=bare_project,
        ))
    return list(dict.fromkeys(hosts))
```

Match the real model field/iteration names against `cicl/model.py` and how
`compile_env` walks `core_services` + `backing_services` (around compile.py
:700–735). If there is no existing `_iter_services`, inline the same
`{**core, **backing}` walk the compiler already uses.

## 4. Dev-DNS check in `preinfra`

`src/docex/pipeline/preinfra.py`:

- Add import: `from docex.dns.client import DnsResolver`.
- Extend `run_preinfra` signature with `dns: DnsResolver | None = None`.
- After the existing `development`-side bridge check, add a development-side
  branch:

```python
if side == "development" and ctx.infra is not None:
    if dns is None:
        failures.append(
            "development side requires a DNS resolver but none was "
            "provided (this is a dispatcher bug)."
        )
    else:
        failures.extend(_check_dev_dns(ctx, dns))
```

- New helper:

```python
def _check_dev_dns(ctx: ProjectContext, dns: DnsResolver) -> list[str]:
    """Verify every `dev` web hostname resolves in public DNS.

    `dev` is brought up with HTTP-01 cert issuance; unresolved hostnames
    trip LE's failed-authorization limit. We check `dev` only — `test` is
    no longer routed/TLS'd, and stage/prod resolve at release time.
    """
    from docex.cicl.compile import web_hostnames_for_env
    hosts = web_hostnames_for_env(ctx.infra, ctx.project.name, "dev")
    failures: list[str] = []
    for host in hosts:
        try:
            ok = dns.resolves(host)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash
            failures.append(
                f"could not check DNS for dev host {host!r} ({exc}); "
                f"resolve transient resolver issues and re-run."
            )
            continue
        if not ok:
            failures.append(
                f"dev host {host!r} does not resolve in public DNS. "
                f"Route it to the dev machine (registrar or Route53) "
                f"before `envinfra up dev` — unresolved dev hosts trip "
                f"Let's Encrypt's failed-authorization rate limit. See "
                f"inception.md PART III."
            )
    return failures
```

Update the module docstring's "What gets checked" list: under "Any project,
`development` side", add the dev-web-hostname DNS resolution check.

## 5. Wire the resolver at the dispatcher

`src/docex/__main__.py` — pass a `DnspythonResolver` to `run_preinfra` at the two
development-side call sites:

- The `envinfra up` gate (~line 200): `run_preinfra(ctx, docker, aws=None, side="development", dns=DnspythonResolver())`.
- `_cmd_preinfra` (~line 252): construct `dns = DnspythonResolver()` and pass
  `dns=dns`. (Harmless to pass on the production side too; `run_preinfra` only
  uses it on the development branch.)

Import: `from docex.dns.dnspython_resolver import DnspythonResolver`.

## 6. Dependency

`pyproject.toml` — add `dnspython` to `dependencies` (a recent stable pin, e.g.
`dnspython>=2.6`). Confirm the `Dockerfile` installs project deps from
`pyproject.toml` (it does via the `pip install .`/equivalent in the build stage);
if so the image picks it up with no Dockerfile edit. Verify nothing else is
needed.

## 7. Tests

- **`tests/.../emit`** (the compose emit suite): add/extend a test asserting a
  `test`-env web service block carries `docex.project=<label>` but **no**
  `traefik.*` label, while the same service in `dev`/`stage`/`prod` carries the
  full traefik label set. (Find the existing traefik-label test and parametrize
  by env.)
- **`tests/.../pipeline/test_preinfra*.py`** (or wherever preinfra is tested):
  - `_check_dev_dns` with a fake `DnsResolver` returning `False` for one host →
    that host enumerated as a failure; `run_preinfra(side="development")` returns 1.
  - All hosts resolve → no DNS failures.
  - `ctx.infra is None` → DNS check skipped entirely (no failures, no resolver
    call).
  - Fake resolver that raises → surfaced as a "could not check" failure, not a
    crash.
  - Assert the resolver is **only** asked about `dev` hosts (never `test`/`stage`
    /`prod`).
- **`web_hostnames_for_env`**: a small unit test (default service gets per-service
  + bare-env in dev; non-default gets only per-service; bare-project absent in
  dev). Reuse fixtures from existing compile tests.

A fake `DnsResolver` (records the hostnames it was asked about; returns a
configured verdict) belongs in the test support module alongside the existing
fake docker/aws clients.

## 8. Verify

`pytest` (unit) green. Then `pytest -m integration` is **not** required for this
mod (no new docker/AWS/git boundary is crossed by unit-testable code; the
resolver is faked). Run the full unit suite and a `docex compile` against both
smoke projects to confirm `test`-env compose no longer emits traefik labels and
`dev`/`stage`/`prod` are unchanged.
