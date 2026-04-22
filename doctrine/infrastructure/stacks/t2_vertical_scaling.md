#  Vertical Scaling Infrastructure Stack

This is the document for vertical scaling infrastructure, or Tier 2 infra.

## Overview

Tier 2 opens the door to cloud-type services but does not break the idea of a single, "central" instance that fundamentally can only scale vertically. Some or all of the backing services are outsourced to the cloud - S3 is used instead of minio; an RDS server might be used instead of postgres. Services outside of the central instance must be either configured manually or with terraform.

HTTP routing is still done with traefik, but the cloud provider's backing services won't be tied into the traefik networks.

The catch of Tier 2 is that it can only scale vertically. The non-outsourced docker stack runs on an EC2 instance. This instance can be scaled larger, but can not be split out into multiple instances.

NOTE: The rest of this document is not yet written!

*More notes to come.*