# telemetry_sidecar

An OpenTelemetry Collector that runs **paired one-to-one with each emitting core service** — one sidecar per core service, and per replica. It accepts OTLP telemetry from its partner core service and exports it onward to the `observability_backend` (see `why observability_backend`). Application code never talks to the backend directly; it emits through its SDK to the local sidecar.

- **Fixed:** a distinct compose container paired by network namespace (`network_mode: service:<container>`), so it always reaches its partner on loopback. Its `dev`/`test` exporter is `debug`, dumping every signal to the sidecar's own stdout — the dev "watch the telemetry" path.
- **Elastic:** a second container inside the same ECS task definition, one per running task/replica.

The sidecar is environment-tier infrastructure the compiler emits automatically; the project declares nothing for it beyond `observability_backend_url`.

Doctrine reference: `infrastructure/specifics/telemetry_infra.md § Sidecar Image`; `infrastructure/telemetry.md § Collector Sidecar`.
