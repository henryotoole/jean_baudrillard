# host_machine

The primary discrete machine carrying a fixed-foundation project's stack. Always Linux, always runs docker, and runs the host-wide HAProxy `web_demux` that every project on it shares — which forwards 443/80 by domain to the requesting project's **own** traefik (see `why reverse_proxy`), rather than routing to containers itself. Prerequisite infrastructure — the doctrine does not provision the host itself; it assumes one is in place with docker installed, a `deploy` user, and the `docex-ingress` master network plus `web_demux` already running.

The doctrine commits to **one host per environment** for now. Multi-host fixed support (docker swarm or otherwise) is deferred — see `infrastructure.md` § Deferred.

Doctrine reference: `infrastructure/shape.md` § Fixed-Foundation.
