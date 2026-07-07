---
stratum: conditional
---

# Contracts

This file describes contracts and what the `doctrine` requires of them.

Contracts define the boundaries of core services. Core services can be providers, consumers, or both depending on usage relationships defined by `infra.yml`'s [depends-on](./cicl.md#depends-on-relationships) field. Every core service that is a provider will have a contract at `$pr/infra/contracts/${service_name}.${contract_format}.yml`.

## Standards

Contracts take standard formats defined by the `doctrine` on the basis of consumer-provider communication mechanism. The full table is below:

The doctrine currently provides the following standard contract formats:
| Contract Format | Filepath Name | Communication Mechanisms |
| --------------- | ------------- | ------------------------ |
| OpenAPI | openapi | HTTP request-based communication. |
| AsyncAPI | asyncapi | Queue-based communication. |

Note that while the contract format is dependent upon communication mechanism, it still describes the *core service*. An asyncapi.yml contract describes `worker`, *not* the queue backing service that actually feeds it info.

## Mandatory Endpoints

In order for the `doctrine`'s infrastructure system to work, certain core services have mandatory endpoints which must exist in their contracts. If they don't exist, the codebase won't pass [CI checks](./cicd.md#check-step).

### Health Checks

In order to pass staging tests, all hosted core services (e.g. `backend`, `web`, `worker`) must provide health checks, reachable from the open web. Not all core services are actually reachable, so those that are must expose the health checks of those that aren't.

The pattern used is pretty simple - all core services on the `web` network must expose:
`/health` - A route which returns the health of the service as {version: "x.x.x"}.

Furthermore, each of those `web`-network core services must provide health checks for all core services downstream in their [dependency chain](./cicl.md#depends-on-relationships):
`/health/<other_service>` - Returns {version: "x.x.x"} for "other_service"

By enforcing these endpoints in the contract, we allow the developer to implement them however they see fit but ensure that health checks will be available to CI/CD operations.