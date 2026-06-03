"""docex — the executor of the doctrine."""

__version__ = "0.10.0"

# The single region the elastic foundation supports (CICL simplification).
# Shared by the compiler, the containerize ECR path, and the boto3 client so
# there is exactly one definition of this value across docex.
ELASTIC_REGION = "us-east-1"

# OTel Collector sidecar image. Pinned by digest, not tag, so base-layer
# churn does not surface to projects pinned to a given docex_version. The
# digest moves when docex cuts a new version. See
# doctrine/infrastructure/specifics/telemetry_infra.md § Sidecar Image.
OTEL_COLLECTOR_IMAGE = (
    "otel/opentelemetry-collector:0.153.0"
    "@sha256:74edb825a429b415262e7eb7a99ed77685c9b2b7238ef69fb42a3625df75458f"
)
