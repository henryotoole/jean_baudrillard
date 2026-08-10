---
stratum: conditional
---

# Contracts

This file describes contracts and what the `doctrine` requires of them.

Contracts define the [surfaces](./cicl.md#surfaces) of a core service. Every surface must have a contract. When two core services interact across such a surface, they form a provider / consumer pair. Whether a core service is a provider, a consumer, or both depends on the `uses` relationships declared by `infra.yml`'s [uses](./cicl.md#uses-relationships) field.

The contract for a given surface shall be stored at:

`$pr/infra/contracts/${codebase}.${service}.${surface}.${format}.${ext}`

e.g.

```
infra/contracts/
├── api.web.rest.openapi.yml
└── api.worker.events.asyncapi.yml
```

## Standards

Contracts take standard formats defined by the `doctrine` on the basis of the `api_styles` chosen for the contract's surface. The full table is below:

The doctrine currently provides the following standard contract formats:
| Contract Format | Filepath Name | Ext | Specification |
| --------------- | ------------- | --- | ------------------------ |
| OpenAPI | `openapi` | `yml` | OpenAPI 3.2 or later. |
| AsyncAPI | `asyncapi` | `yml` | AsyncAPI 3.0 or later. |
| GraphQL | `graphql` | `graphql` | *Planned, not yet implemented into doctrine.* |
| Proto | `proto` | `proto` | *Planned, not yet implemented into doctrine.* |

GraphQL and Proto are not yet implemented and will currently trip a compile error if used.

The format follows from the `api_styles` the surface declares (see [cicl.md](./cicl.md#surfaces)). 

Note that while the contract format is dependent upon API style, it still describes the *core service*. An asyncapi.yml contract describes `api.worker`, *not* a queue backing service.