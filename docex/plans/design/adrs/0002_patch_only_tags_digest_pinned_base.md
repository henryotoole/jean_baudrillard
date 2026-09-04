---
id: 0002
title: patch_only_tags_digest_pinned_base
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [distribution, determinism]
---

## Context

Determinism is a top-tier requirement: a project pinned to a `docex` version must produce
identical infrastructure outputs forever. Two common conveniences undermine that. Floating
tags (`docex:1`, `docex:1.2`, `docex:latest`) silently re-point to a newer image on every
release, so "the same pin" resolves to different bytes over time. And a base image
referenced by tag (`FROM python:3.12-slim`) is itself a floating pointer — an old `docex`
release rebuilt later picks up a churned base layer.

## Decision

Tag `docex` images **patch-level only** (`docex:1.2.3`); publish no floating tags. Pin the
base image **by digest** (`FROM python:3.12-slim@sha256:...`), not by tag.

## Consequences

- A pin always resolves to one exact image; determinism holds across time and machines.
- Old releases are immune to upstream base-layer churn.
- **Cost:** consumers must bump an explicit patch version to get updates (no `latest`
  convenience), and updating the base image is a deliberate, committed change rather than an
  automatic one. Both are the intended friction.
