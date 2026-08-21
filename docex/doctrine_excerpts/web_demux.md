# web_demux

The host-wide ingress front door on a **fixed** foundation. **Prerequisite infrastructure** (HAProxy), stood up once per host machine and shared by every project on it; no project provisions it.

It listens on 443/80 and forwards each request to the correct project's own traefik on the basis of domain — 443 by SNI pass-through (it does **not** terminate TLS; the per-project traefik does), 80 by Host header. It and the project traefiks all sit on the shared `docex-ingress` master network (see `why master_network`), which is how it reaches them.

Routing to a per-project traefik rather than to containers directly is what gives blast-radius protection: one project cannot misconfigure another's routing. The elastic foundation has no `web_demux` — there, DNS routes straight to each project's own reverse proxy.

Doctrine reference: `infrastructure/preinfra/fixed_master_network.md § The web_demux Resource`; `infrastructure/shape.md § Fixed-Foundation`.
