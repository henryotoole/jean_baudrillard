---
id: 0001
title: single_bundled_docex_image
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [distribution, coherence, determinism]
---

## Context

The doctrine ships many deterministic tools: the CICL compiler, the transfer tables, the
CI/CD orchestration, the per-foundation release machinery, and the elastic state-backend
bootstrap. A project needs all of them, and needs them to agree with each other. The
obvious alternatives are to distribute them as a pip package (or several), or to have each
project install OpenTofu, Ansible, the AWS CLI, OpenAPI tooling, and a Python runtime
directly. Both make the versions a project actually runs a function of the machine it runs
on, and let the compiler drift from the release flow drift from the tables.

## Decision

Deliver `docex` as **one versioned container image** that bundles every deterministic
doctrine-shipped tool behind a single command-line surface, plus a ~10-line project-local
shim. A project pins exactly one `docex_version` in `project.yml`; that one pin governs the
compiler, the tables, the containerize step, and the release flow together. No project
carries doctrine source code in its own repository.

## Consequences

- **Coherence by construction.** All bundled tooling moves in lockstep; there is no way for
  a project to run a new compiler against old tables.
- **Zero infra burden.** A developer needs only Docker; the CLI toolchain lives in the
  image.
- **Reproducibility without machine state.** Clone, install Docker, run `./bin/docex
  compile` — the outputs do not depend on what else is installed.
- **Cost:** the image is heavier than a pip package, and a new tool version means a new
  `docex` release rather than a `pip install -U`. This is accepted — the determinism and
  coherence it buys are the whole point of the executor model. Upgrading a project is a
  one-line pin change (see [`../concepts_and_decisions.md § Version Pinning`](../concepts_and_decisions.md#version-pinning)).
