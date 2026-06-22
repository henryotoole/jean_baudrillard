# host_machine

The primary discrete machine carrying a fixed-foundation project's stack. Always Linux, always runs docker, and runs the machine-wide traefik that all projects on it share. Prerequisite infrastructure — the doctrine does not provision the host itself; it assumes one is in place with docker installed, a `deploy` user, and traefik watching the docker socket.

The doctrine commits to **one host per environment** for now. Multi-host fixed support (docker swarm or otherwise) is deferred — see `infrastructure.md` § Deferred.

Doctrine reference: `infrastructure/shape.md` § Fixed-Foundation.
