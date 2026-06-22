---
stratum: conditional
---

# Elastic ECR

This file describes the ECR (Elastic Container Registry) repositories created on the production side of every elastic-foundation project. They hold the build images that `./bin/docex containerize` pushes and `./bin/docex release` pulls.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Resources

One ECR repository per core service, in the project's elastic region (currently `us-east-1`):

| Resource | HCL | Name (rendered) |
| -------- | --- | --------------- |
| Repository for service `<svc>` | `aws_ecr_repository.<svc>` | `<project>/<svc>` |

For a project named `myproject` with core services `api` and `worker`, the resources are `aws_ecr_repository.api` and `aws_ecr_repository.worker`, with rendered names `myproject/api` and `myproject/worker`.

The repo name is a **two-segment path** joined by a literal `/`. ECR treats forward slashes in repo names as namespace separators, so this is a valid repository name (not a sub-resource) and yields image references that match the canonical form declared in [cicl.md § Container Registry and Service Images](../../cicl.md#container-registry-and-service-images): `${container_registry}/${project_name}/${service_name}:${version}`.

The slash is **not** rendered by the naming-policy machinery in [transfer_tables.md § Naming Policies](../transfer_tables.md#naming-policies) — that machinery has a single global separator per policy and cannot express "slash between segments, underscore preserved within segments." ECR repo naming is therefore a structural emitter hardcoded in docex code: each segment (`${project_name}`, `${service_name}`) is passed verbatim with its own underscores preserved; the slash between them is emitted directly.

## Configuration

Per-repository defaults emitted by `docex`:

| Setting | Value | Why |
| ------- | ----- | --- |
| `image_tag_mutability` | `MUTABLE` | Doctrine commits to one image per version (`v0.1.2`), but allows republishing the same tag during pre-release iteration — useful when a `./bin/docex containerize` partial failure leaves a bad image and the operator rebuilds. Immutable tags would block recovery without an artificial version bump. |
| `image_scanning_configuration.scan_on_push` | `true` | Free; surfaces CVEs in the AWS console. No CI enforcement attached by default. |
| `encryption_configuration.encryption_type` | `AES256` | Default; explicit for clarity in diffs. |
| `force_delete` | `false` | Repositories with images can't be destroyed casually — `./bin/docex projinfra down production` will fail loudly rather than silently nuking image history. |

Tags follow the **projinfra** block of the doctrine-wide standard in [cicl.md § Naming and Tagging](../../cicl.md#naming-and-tagging) with `shape_name=container_registry`. The repo is per-service, but the projinfra block has no `service` tag — the service name rides in `descriptor` (`descriptor=${service_name}`) and the derived `Name` (`${project}_container_registry_${service}`).

The doctrine does **not** emit lifecycle policies by default — no auto-deletion of old image versions. Image storage is cheap; preserving history makes rollback to old versions trivial. Projects that need cleanup can add a policy via project-local extension.

## Image Naming

For an elastic project, each core service's image reference at run time is:

```
<account>.dkr.ecr.us-east-1.amazonaws.com/<project>/<svc>:<version>
```

The account ID is resolved by `docex` at compile time (or at `containerize` / `release` time when running the actual commands) via `aws sts get-caller-identity`. The version comes from `project.yml`. See [cicl.md § Container Registry](../../cicl.md#container-registry-and-service-images).

When a project's `infra.yml` overrides `container_registry:` to an external registry, ECR is still created (it's cheap, and the doctrine doesn't want to introduce conditional projinfra), but unused. The override applies at the *image-reference* layer in env-tier compiled output — the env-tier task definitions reference the external registry instead of the auto-provisioned ECR.

This is a minor wart: an unused ECR is paid-for storage (typically $0 if nothing's pushed, but still creates a footprint in the AWS console). The doctrine accepts it in exchange for keeping projinfra unconditionally consistent across elastic projects.

## Authentication

Push (`./bin/docex containerize`) and pull (`./bin/docex release` via the ECS task-execution role) both use AWS-side authentication:

- **Push:** `aws ecr get-login-password` against the operator's AWS credentials, then `docker login` against the rendered ECR registry URL. The `containerize` command handles this transparently — no operator action.
- **Pull:** ECS tasks pull using the task-execution role (see [`elastic_iam.md`](./elastic_iam.md)), which carries `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, and `ecr:GetDownloadUrlForLayer` scoped to the project's repositories.

No long-lived registry creds are stored on any host. ECR auth tokens are short-lived (12 hours) and refreshed by `containerize` per invocation.

## Outputs Consumed Downstream

The project's `main.tf` declares one output per core service:

| Output | Used by |
| ------ | ------- |
| `ecr_repository_<svc>_url` | Env-tier task definitions in each env's `main.tf` — referenced as the image source for the service |

The compiler also emits an `ecr_repository_<svc>_arn` output for the task-execution role's resource-scoped permissions (see [`elastic_iam.md`](./elastic_iam.md)).

## Lifecycle

The repositories come up with `./bin/docex projinfra up production`. They persist across deploys; `release` pushes new image tags but never modifies the repository resource itself. `./bin/docex projinfra down production` will fail if any repository contains images (`force_delete: false`); the operator must explicitly empty repositories before tearing down project-tier infra.

When a core service is added to `infra.yml`, the next `./bin/docex projinfra up production` creates the new repository. When a core service is removed, the repository remains in state (and in AWS) until the operator either manually empties it and re-runs projinfra, or removes the resource from the rendered HCL via project-local extension. The doctrine doesn't auto-delete repositories with image history; the failure mode of accidental deletion is worse than the operator overhead of explicit cleanup.

## Out of Scope

- **Cross-region replication.** Single-region only.
- **Image-version lifecycle policies.** No auto-cleanup; the doctrine prefers preserving rollback history over storage minimization.
- **Repository policies for cross-account pulls.** If a project needs to be pulled from outside its account, the operator attaches a repository policy out-of-band.
