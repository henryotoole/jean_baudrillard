---
stratum: conditional
---

# Diagram of ECS Service Connect Name Resolution

┌───────────────────────────────────────────────────────────────────────────────────┐                ┌─────────────────────┐
│ ECS Task Instance A                                                               │                │ ECS Task Instance B │
│                                        ┌────────────────────────────────────────┐ │                │                     │
│                                        │ Envoy Sidecar                          │ │                │ ┌───────┐           │
│                                        │                                        │ │                │ │ HTTP  │           │
│ `/etc/hosts`:                          │ <container-name>    Cluster Endpoints  │ │                │ │ API   │           │
│ + <container-name> = 127.255.0.x───────┼►to cluster          ┌────────────────┐ │ │                │ │       │           │
│   e.g. "api-worker"                    │     │               │ IP: health     │ │ │                │ │       │           │
│                                        │     └──────────────►│ IP: health─────┼─┼─┼────────────────┼►│       │           │
│                                        │  (load balancing)   │ ...            │ │ │                │ └───────┘           │
│                                        │                     │                │ │ │                │                     │
│                                        │                     └────────────────┘ │ │                │                     │
│                                        │                                        │ │                │                     │
│                                        └────────────────────────────────────────┘ │                │                     │
│                                                                                   │                │                     │
└───────────────────────────────────────────────────────────────────────────────────┘                └─────────────────────┘
                                                                                                                            
* arrows represent an HTTP request fired against a container name.
* note that the endpoints *within* a cluster — their IPs and health status — are kept up to date by AWS control plane machinery.
* note that the **set of clusters** is not. It is resolved once, when the ECS *deployment* is created, and every task in that deployment is served the same fixed list. A name registered after the deployment never appears in `/etc/hosts` for any of its tasks, and replacing a task does not help unless the replacement lands in a new deployment. See [cicl.md § Resilience covers reachability, not resolvability](../infrastructure/cicl.md#resilience-covers-reachability-not-resolvability).