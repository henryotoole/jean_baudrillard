---
stratum: conditional
---

# Credentials

This file provides a general overview of how deploy credentials are handled under doctrine infrastructure.

## Deploy Credentials

These are similar to secrets, but differ as they aren't embedded in the resulting project infrastructure to keep it running. They are only used as a part of the CI/CD pipeline in order to cause infrastructure to match whatever the project declares in `infra.yml`.

The role of these credentials is the same on all foundations, but the specifics are different from `fixed` to `elastic`.

### Fixed

Credentials are stored in the `$pr/infra/deploy_creds` folder in the form of private keys. There's one key for each deployable environment: `stage` and `prod`. Naming convention is:
+ private key - `$pr/infra/deploy_creds/<env>`
+ public key - `$pr/infra/deploy_creds/<env>.pub`

Public keys aren't strictly required, but will in practice often exist in this folder.

How these keys are used is described more deeply in the [release](./specifics/release.md) specifics.

#### Fixed Container Registry
Both the push side (development machine) and pull side (production machine) of a `fixed`-foundation project need credentials to access the container registry.

These are placed in `~/.docker/config.json` on both machines. 

### Elastic

Currently for elastic foundations we only use AWS. This doctrine expects to find AWS credentials at the standard place: `~/.aws/credentials`.

#### Elastic Container Registry
The same AWS credentials handle push and pull from ECR.

## Git Host Credentials
Access to the git host (e.g. github) from the development machine is done with whatever credentials the developer has provided for the machine. These will most frequently be stored as a private key in the `~/.ssh` directory or simply be available through an ssh-agent.

Some development machines instead broker git access through a configured **git credential helper** (`credential.helper`) — for example one that mints short-lived tokens on demand rather than holding a static key. Because `docex` runs git inside its container, a helper that depends on host-local state (a helper binary, a socket) cannot run there. For these machines `docex` brokers git credentials **on the host** — through git's own credential machinery (`git credential fill`), so it stays agnostic to which helper is configured — and makes that resolution available to the in-container git **per network operation**, so each fetch/push obtains a *fresh* short-lived credential rather than a single one captured up front. This keeps long-running commands (e.g. `merge`, whose defensive `check` may run for minutes before its `push`) from failing on a credential that expired between capture and use. This behavior is opt-in (the environment signals it) and leaves the static key/agent path above unchanged when not enabled. The mechanism lives in the [`docex` shim](./docex.md#project-installation); see [`docex`'s masterplan](../../docex/plans/core/masterplan.md#the-shim) for specifics.