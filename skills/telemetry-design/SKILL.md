---
name: telemetry-design
description: Doctrine for designing a project's observability — what logs, traces, and metrics to emit and how the OTel collector sidecars carry them to the observability backend. Use this whenever you are adding or changing telemetry, deciding what signals to emit, configuring the OTel sidecar, debugging where signals end up, or touching the observability backend — even if the words "telemetry" or "observability" are never used.
metadata:
  type: thread
---

# telemetry-design

The doctrine for telemetry/observability is two files plus the threads connecting this activity to its neighbors. Read the general file on load; descend into the specific one only when the task reaches the mechanism.

## General Information

What telemetry is and what to emit. **Read this now.**

[`telemetry.md`](../../doctrine/infrastructure/telemetry.md) — the observability model: the three signals (logs / traces / metrics), how they flow, the OTel standard, backend choice, retention windows, and the doctrine-injected `OTEL_*` env vars. This orients the whole activity.

## Specific Information

How docex moves the signals. **Read on demand**, when the task reaches the mechanism.

[`telemetry_infra.md`](../../doctrine/infrastructure/specifics/telemetry_infra.md) — how the collector sidecar is emitted per foundation (compose service vs. ECS task-definition container), its config YAML, endpoint/secret delivery, validation rules, and failure modes. Go here when configuring the sidecar, changing collector behavior, or debugging where a signal landed.

## Thread

What connects, and where this activity ends.

- *Emitting* telemetry from application code is a Resident coding practice, already in context — see [`logging.md`](../../doctrine/practices/logging.md). This skill is about designing a project's observability and wiring the carrying infrastructure, not the line-level logging API.
- Standing up the observability *backend itself* (HyperDX) is prerequisite infrastructure: that is the `preinfra-setup` activity ([`telemetry_preinfra.md`](../../doctrine/infrastructure/preinfra/telemetry_preinfra.md)), not this one.
- On elastic, the sidecar's IAM and secret wiring surface under `projinfra-setup` (task-execution role) and `cicd-pipeline` (secret push). Follow those skills if the task crosses into them rather than duplicating their detail here.
