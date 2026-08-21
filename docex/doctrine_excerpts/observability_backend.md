# observability_backend

The backend application stack — HyperDX by default — that collects, indexes, and displays the project's telemetry (logs, traces, metrics). **Prerequisite infrastructure**: self-hosted or cloud-managed, shared across projects, and never provisioned by a project's compiled output.

A project points at it with the top-level `observability_backend_url:` field in `infra.yml`. That URL must be HTTPS and well-formed (the compiler rejects `http://` and unparseable values; `docex check` probes reachability). It propagates into each core service's paired OTel collector sidecar (see `why telemetry_sidecar`) as `OBSERVABILITY_BACKEND_URL`; the sidecars export OTLP to it in `stage` and `prod`. In `dev`/`test` the sidecar's exporter is `debug` and nothing is forwarded to the backend.

Doctrine reference: `infrastructure/cicl.md § Observability Backend`; `infrastructure/telemetry.md § Observability Backend`.
