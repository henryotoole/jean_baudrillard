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
* note that the clusters and endpoint status are kept up to date by AWS control plane machinery.