# Deployment

Deployment is the mechanical act of taking a [release](./releases.md) and making it live on a machine. It is distinct from releasing, which is the decision to label a snapshot of the code as stable and versioned.

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

"$version" is used to reference the desired production version below. "$prev_version" refers to the previous version.

## Deployment Process

The process used to deploy a release changes depending on the [infrastructure stack tier](./overview.md) being used

### Tier 1 or "Single Server" Infra Stacks

The basic idea is that we simply pull the released repository onto the production machine (or environment) and rebuild docker.

The general steps to deploy a **tagged, released** version are as follows:
1. SSH into the production server / environment.
2. **Pull the target version** on the machine:
   ```bash
   git fetch origin --tags
   git checkout $version
   ```
3. **Rebuild and restart** the production stack:
   ```bash
   docker compose up --build -d
   ```
   This targets the `prod` Dockerfile stage by default (no override file), exactly as the docker architecture doctrine specifies.
4. **Verify** — check that services are healthy (`docker compose ps`, hit a health endpoint, etc.)

#### Rollback

If something goes wrong, rollback is the same workflow pointed at the previous tag:

```bash
git checkout $prev_version
docker compose up --build -d
```

#### Justfile

```just
# Note: Must run from production envorinment.
deploy version:
  git fetch origin --tags
  git checkout v{{version}}
  docker compose up --build -d
```

### Tier 2 or "Vertical Scaling" Infra Stacks

**NOT YET DEVELOPED**

This cannot simply follow the Tier 1 method because it makes no provisions for other services that aren't managed by docker compose in production.

### Tier 3 or "Horizontal Scaling" Infra Stacks

**NOT YET DEVELOPED**

This cannot simply follow the Tier 1 method because it makes no provisions for an ECS-like scaling system where there is not one single production machine to shell into.