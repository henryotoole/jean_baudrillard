# network: internal (and other non-special names)

Any network whose name is not in the doctrine's reserved set defaults to **internal**: reachable only from other services on the same network.

- **Fixed:** a plain user-defined docker bridge with no published host ports, so nothing outside the host can reach it. Services reach each other by container name (which equals `${global_service_name}`). Docker's `internal: true` flag is deliberately **not** used — it adds no ingress protection over this shape and would strip the bridge's masquerade rule, killing egress.
- **Elastic:** an AWS security group **within the shared master VPC** that accepts ingress only from itself — i.e., from other services attached to the same SG.

Internal networks are the doctrine's default and the right choice for backing services, worker queues, and any inter-service plumbing that should never be reachable from the public internet.

**Ingress-only, not an airgap.** A non-`web` network restricts who can reach *in*; it does not restrict reaching *out*. Containers on one have full internet egress on both foundations — via the host's NAT on fixed, via allow-all SG egress and the master VPC's NAT gateway on elastic. Constraining egress per network is deferred doctrine.

Doctrine reference: `infrastructure/specifics/networks.md § networks: [internal]`.
