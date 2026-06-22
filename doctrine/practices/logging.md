---
stratum: resident
---

# Logging

This file covers logging practices for within a core service container.

## By Language

### Python

Logging should be configured at the code entrypoint with:
```py
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
```

Loggers are fetched for use with code via:
```py
logger = logging.getLogger(__name__)
```

## With Respect to Telemetry

Application **telemetry** — the structured logs, traces, and metrics you want to query — is emitted through the **OTel SDK**, which auto-discovers the doctrine-injected `OTEL_*` env vars and exports OTLP to the paired collector sidecar (→ the observability backend). Wire your telemetry through the SDK; do **not** also mirror it to stdout/stderr.

**Why no stdout mirror:** on elastic, container stdout/stderr is captured by `awslogs` → CloudWatch (see [telemetry_infra.md § Container stdout/stderr](../infrastructure/specifics/telemetry_infra.md#container-stdoutstderr-class-2-diagnostics)). Mirroring SDK telemetry to stdout would duplicate every Class-1 record into CloudWatch *on top of* the backend — two sinks, double ingest, a muddied diagnostics log.

**Seeing telemetry in dev:** in `dev`/`test` the sidecar's exporter is `debug`, which dumps every signal to the *sidecar's* stdout — read it with `docker logs -f <svc>-otelcol`. That is the dev "watch the telemetry" path; no application-side echo is needed.

**Reserve stdout/stderr for Class-2 diagnostics:** crash output, panics, pre-SDK-init messages, and shell scripts (`migrate.sh`). These can't go through the SDK and are exactly what `docker logs` (fixed) / CloudWatch (elastic) exist to capture. The `basicConfig` stub above is fine for that diagnostic logging — just don't route application *telemetry* through a stdout handler in addition to the SDK.