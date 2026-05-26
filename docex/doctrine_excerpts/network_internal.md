# network: internal (and other non-special names)

Any network whose name is not in the doctrine's reserved set defaults to **internal**: reachable only from other services on the same network.

- **Fixed:** docker network with `internal: true`, no inbound from outside the host. Services reach each other by container name (which equals `${global_service_name}`).
- **Elastic:** an AWS security group within the project VPC that accepts ingress only from itself — i.e., from other services attached to the same SG.

Internal networks are the doctrine's default and the right choice for backing services, worker queues, and any inter-service plumbing that should never be reachable from the public internet.

Doctrine reference: `infrastructure/specifics/networks.md` § `networks: [internal]`.
