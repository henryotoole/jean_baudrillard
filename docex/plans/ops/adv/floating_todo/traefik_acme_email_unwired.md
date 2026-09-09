# The `ec2_traefik` ACME account email is permanently a placeholder

**Deferred:** a proper home for this value is planned but not yet available, so
this stays in `floating_todo` until that lands. Struck from advance 008 at plan
review for that reason.

## The finding

`emit/hcl.py:1167` declares `traefik_acme_email: str | None = None`; `:1253`
falls back to `acme_email = traefik_acme_email or f"docex@{apex_domain}"`; `:1260`
passes it into the user-data template, which writes it as the Let's Encrypt
account email (`ec2_traefik_user_data.sh.j2:142`). **The only production call site
never passes it** (`cicl/compile.py:1372-1379` stops at `reverse_proxy`). So on
both `ec2_traefik` variants the ACME account email is always `docex@<apex_domain>`
— an address that need not exist or be deliverable, and is not the operator's.

Documented-not-implemented: the parameter is in the signature, so a reader
concludes the value is configurable; nothing configures it. It is invisible
because the fallback keeps the artifact valid — no gate fires, both smoke walks
pass (the fixed walk never uses this template; the elastic walk because LE issues
certs without verifying the account address). The failure surface is entirely
after issuance and off-machine.

Why it is minor: LE uses the address only for expiry-notice mail and account
recovery — not validation or issuance. So the placeholder's cost is that nobody is
warned about a renewal that has stopped working, and the account cannot be
recovered. Real but narrow.

## The open question — where the email belongs

Deferred pending the planned configurable-values home. The candidates weighed so
far:

- **`infra.yml`** — per-project infra config, and the reverse proxy is declared
  there. Against: not a *shape* fact, and CICL has kept operator contact details
  out.
- **`project.yml`** — project identity like `name`. Against: `project.yml` is
  deliberately tiny and read by everything.
- **config** (`infra/config/<side>.env`) — "a value likely to vary between
  deploys". Against: it is needed at *compile* time, not container start, so it
  would be the first compile-time read of a config `.env`, and project-tier output
  is per-side not per-env.

Cheaper and also open: whether `traefik_acme_email` should keep its default at
all. A required keyword argument with no fallback would have made this a compile
error at the one call site the day the parameter was added.

## Where to look

- `emit/hcl.py:1167` — the `traefik_acme_email` parameter; `:1253` — the fallback;
  `:1260` — where it is passed on.
- `emit/templates/ec2_traefik_user_data.sh.j2:142` — where the address lands.
- `cicl/compile.py:1372-1379` — the only production call site, which never passes
  it.
