"""docex — the executor of the doctrine."""

__version__ = "0.9.0"

# The single region the elastic foundation supports (CICL simplification).
# Shared by the compiler, the containerize ECR path, and the boto3 client so
# there is exactly one definition of this value across docex.
ELASTIC_REGION = "us-east-1"
