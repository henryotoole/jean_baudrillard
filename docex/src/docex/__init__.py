"""docex — the executor of the doctrine."""

__version__ = "1.4.1"

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
#     docker pull traefik:v3.6 && \
#     docker inspect --format '{{index .RepoDigests 0}}' traefik:v3.6
# See doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md.
#
# Mod 047: bumped from v3.3 to v3.6 — traefik 3.3's docker provider
# defaults to Docker API v1.24, which modern Docker daemons (24+) no
# longer accept. The 3.3 traefik comes up but its provider loop emits
# `client version 1.24 is too old. Minimum supported API version is
# 1.40` and never picks up env-tier service labels, so no routing
# happens. v3.6 negotiates the API version correctly.
TRAEFIK_IMAGE = (
    "traefik:v3.6"
    "@sha256:cc1799c50550f730f686df9b368e690f9199542787db8d1dd328a7c3779f6eea"
)

# Ofelia job-scheduler image for the fixed-foundation `scheduler` role.
# Pinned by digest for the same reason as the images above. docex emits
# one ofelia container per scheduler service; it spawns the job as a
# one-off container on each fire. Resolve a new digest with:
#     docker pull mcuadros/ofelia:v0.3.7 && \
#     docker inspect --format '{{index .RepoDigests 0}}' mcuadros/ofelia:v0.3.7
# See doctrine/infrastructure/specifics/scheduler.md § Fixed Foundation.
OFELIA_IMAGE = (
    "mcuadros/ofelia:v0.3.7"
    "@sha256:21082a58c3d0d5d5b8615ac7d1ac5d039074728735879c76baf876c4358cbc3e"
)
