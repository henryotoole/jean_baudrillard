"""docex — the executor of the doctrine."""

__version__ = "1.0.0"

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

# Traefik image for the per-project reverse proxy. Pinned by digest for
# the same reason as OTEL_COLLECTOR_IMAGE — projects pinned to a given
# docex_version see an immutable base. Resolve a new digest with:
#     docker pull traefik:v3.3 && \
#     docker inspect --format '{{index .RepoDigests 0}}' traefik:v3.3
# See doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md.
TRAEFIK_IMAGE = (
    "traefik:v3.3"
    "@sha256:2cd5cc75530c8d07ae0587c743d23eb30cae2436d07017a5ff78498b1a43d09f"
)
