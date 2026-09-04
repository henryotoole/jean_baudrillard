---
id: 0003
title: docker_outside_of_docker
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [runtime, docker, security]
---

## Context

`docex` runs inside a container but must build, tag, push, and run containers on behalf of
the project — dev stacks, build images, migration one-offs. There are two ways to give a
container access to Docker: run a nested daemon inside it (Docker-in-Docker, DinD), or have
the in-container `docker` CLI talk to the **host's** daemon over a mounted socket
(Docker-outside-of-Docker, DooD). DinD requires `--privileged`, is slower, and adds a
second daemon to reason about. It also raises a hard question DooD raises too: containers
that `docex` starts reference project paths (build contexts, bind-mount sources), and those
paths must resolve identically for the client that reads them and the daemon that mounts
them.

## Decision

Use **DooD**: mount `/var/run/docker.sock` and run the host's daemon. Do not use DinD, do
not use `--privileged`. To make paths agree, the shim **mirrors the host project path
inside the container** — `$PROJECT_ROOT` is mounted at `$PROJECT_ROOT` (not a fixed
`/project`), and the in-container user is set to the host user (`--user`, mounted
`/etc/passwd`/`/etc/group`, mirrored `$HOME`).

## Consequences

- **Sibling containers.** Containers `docex` spawns attach to the host daemon and outlive
  the `docex` invocation — exactly what a long-lived dev stack needs. It also means a
  durable job cannot be a host process (it would die with the `--rm` foreground container),
  which forces the container-vessel design in
  [ADR 0005](./0005_durable_job_substrate.md).
- **Path agreement in both directions.** Any path `docex` emits is simultaneously a valid
  in-container path (compose's client-side reads) and a valid host path (the daemon's
  bind-mount resolution). Compose receives the project directory via `--project-directory`
  because docker compose v2 ignores `COMPOSE_PROJECT_DIR`.
- **Host-owned files, coherent identity.** Files docex writes are operator-owned (no
  `chown -R`), `git` doesn't trip on dubious-ownership, and `getpwuid()`-based tools (ssh)
  find a home directory matching the credential mounts.
- **Cost / caveat:** the container shares the host's Docker daemon, so it is as trusted as
  the operator. The Compose **project name** must be pinned explicitly (not derived from the
  directory basename) or re-runs and teardowns drift — see
  [`../concepts_and_decisions.md § Docker-outside-of-Docker`](../concepts_and_decisions.md#docker-outside-of-docker)
  point 4.
