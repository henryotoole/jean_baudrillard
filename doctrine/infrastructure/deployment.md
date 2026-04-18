# Deployment

Deployment is the mechanical act of taking a [release](./releases.md) and making it live on a machine. It is distinct from releasing, which is the decision to label a snapshot of the code as stable and versioned.

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

"$version" is used to reference the desired production version below. "$prev_version" refers to the previous version.

## Deployment Process

This section describes the processes for deployment on various different infrastructure stacks.

Currently, the following infrastructure stacks have processes:
| Infrastructure Stack | Description |
| -------------------- | ----------- |
| Single Server | All core code services and backing services (like postgres) run on one server and are managed by docker compose. |

### Single Server Deployment Process

Warning! This process must occur in the production environment on the production server!

1. **Pull the target version** on the machine:
   ```bash
   git fetch origin --tags
   git checkout $version
   ```
2. **Rebuild and restart** the production stack:
   ```bash
   docker compose up --build -d
   ```
   This targets the `prod` Dockerfile stage by default (no override file), exactly as the docker architecture doctrine specifies.
3. **Verify** — check that services are healthy (`docker compose ps`, hit a health endpoint, etc.)

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
