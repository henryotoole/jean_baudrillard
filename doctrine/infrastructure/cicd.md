---
stratum: conditional
---

# CI/CD

This file describes the details of our handling of CI/CD. 

## The Pipeline

This doctrine prescribes a "[trunk based](./version_control.md)" branch strategy for development. New feature work occurs in feature branches. Eventually, when a feature branch is complete, this CI/CD pipeline is used to properly test, merge, and release it. All formal pipeline operations are documented below and are implemented as `docex` commands. 

The pipeline starts off at the end of development. By this point, the developer has been working in a feature branch to make changes to the code and commits as needed. The feature is "complete" and the developer has manually run tests (`./bin/docex test`) to ensure their changes are *at least* working at the tip of the feature branch. The developer has incremented the `project.yml` version and the working tree is clean.

The CI/CD pipeline moves this "finished" feature branch into production:
1. **Check** - Creates an ephemeral worktree merging the feature and main branches and performs gate checks.
	+ If checks, build, or tests fail, the worktree is discarded and the codebase returns to feature branch tip.
2. **Review** (Optional) - PR is approved by manual review. This step requires real git hosting infra.
3. **Merge** - Feature branch changes are merged into main
	+ After this, any change resulting from a failed test requires a new version number.
4. **Containerize** - The build is formally turned into a container image.
5. **Release** to `stage` - The build image is released into `stage`.
6. **Staging Test** - Staging tests are run against the new release version.
	+ If they fail, a new release version must be created and the process started over.
7. **Release** to `prod` - The build image is considered production-ready and is rolled out to `prod`.

The entire CI/CD process *can* be performed solely by running `docex` commands on the development machine. For some teams and projects, that will be sufficient. Others might require a centralized review stage and wish to automate the process with triggers. This level of complexity will require a real git host, like github or gitlab.

### Manual `docex` Chain
The entire CI/CD pipeline can be performed by chaining the following commands (presuming all checks, builds, and tests pass):
`./bin/docex merge`
`./bin/docex containerize`
`./bin/docex release stage`
`./bin/docex stagetest`
`./bin/docex release prod`

## Pipeline Operations

Each level two section below describes one of the steps in the pipeline with:
1. An overview of the step.
2. The process to perform the step.
3. `docex` usage to perform the process.

### Check Step

This step kicks off the CI/CD pipeline. It performs the "gate checks" which are the first line of defense for broken or misconfigured code. These checks are performed against an ephemeral worktree that combines the feature and main branches into the form in which they'd be released *without* actually altering either branch so that reverting back is simple if checks fail. 

#### Process
1. Create the ephemeral worktree by combining the feature branch with the latest main from origin.
2. Perform git / version checks:
	1. Working tree is clean.
	2. Latest main is used.
	3. `project.yml` version was bumped.
	4. `project.yml` version has not yet been released.
	5. No merge conflicts
3. Perform core service checks:
	1. All core services contain `build.sh`, `test.sh`, and `migrate.sh` if it is required.
	2. [Contracts](./infrastructure.md#contracts) exist which match `infra.yml`'s [consumes](./cicl.md#consumes-relationships) relationships. One contract per provider process type, at `${service}.${process}.${format}.yml`.
	3. Every `web`-network process type's contract carries the mandatory [health check](./contracts.md#health-checks) endpoints: its own `GET /health`, and a `/health/<service>/<process>` for each process type it `consumes` that is not itself on `web`. The self-`/health` assertion applies to OpenAPI providers; a `worker`'s probeability is declared by its fields, not by its AsyncAPI contract.
	4. Every core service whose image must answer a probe carries `curl`. The declaration is per process type — any one of a codebase's process types declaring `health_check_path` qualifies the codebase — but the subject is the codebase's single image, so the gate builds and probes once per core service.
	5. Every `consumes` target declares both `port` and `health_check_path`. Those two fields *are* its health declaration; see [contracts.md § Declared by fields](./contracts.md#declared-by-fields-not-by-the-contract).
4. Probe the `observability_backend_url` for reachability (see [telemetry_infra.md § Validation Rules](./specifics/telemetry_infra.md#validation-rules)).
5. Ensure build doesn't fail.
6. Run build test

If any steps fail, the repo is reverted back to its original state.

#### `docex`
`./bin/docex check`

### Review

Review refers to a place where the pipeline pauses until the change can be inspected by another developer and approved for further release.

This step is optional, and is not covered more deeply in this version of the `doctrine`.

### Merge

This step simply merges the feature branch into the main branch (technically we rebase, but "merge" captures the intent more) and tags the relevant commit. The release tag is applied to the merge tip, not to the original version-bump commit. This way, if any fix-up commits after a failed `./bin/docex check` occur, they require no special handling.

#### Process
1. Re-run gate checks just in case the main branch moved.
2. Rebase feature onto current main; fast-forward main to the rebased tip.
3. Tag the new main tip with `v<version>` from `project.yml`.
4. Push main and tags to origin.
5. Delete the feature branch (local + remote)

#### `docex`
`./bin/docex merge`

### Build Step

Every core service gets a `build.sh` script. This is responsible for turning `source` into a `build artifact`. *All* unique commands needed to build that service's code will go here. For a python backend, this script will just copy files over. For a Svelte SPA frontend it might invoke `esbuild`. If a build fails, `build.sh` should return a non-0 exit code.

`build.sh` is the **single canonical build entry point** for every core service. It is invoked in two contexts, but it is the same script in both:

1. **Inside `docker build`** (canonical, authoritative). The Dockerfile's `build` stage `COPY`s `src/` and runs `./build.sh`, depositing artifacts at a known path inside that stage. The `prod` and `test` stages then `COPY --from=build` those artifacts into the final image. This is the path that produces images shipped to `stage` and `prod`.
2. **Inside a one-off container of the codebase's exec service** (iteration convenience). That container runs the `dev` stage, which carries the same build tools, and has `/service/src` and `/service/dist` bind-mounted from the host; running `build.sh` in it refreshes the host's `dist/` so the developer's running code is fresh without a container rebuild.

Because the authoritative build runs *inside* `docker build`, the artifact is always produced on whatever platform the image is being built for — set explicitly by `docker buildx --platform` during [`./bin/docex containerize`](#containerize-step). A developer on an arm64 Mac thus produces correct amd64 production images: the build runs under emulation inside the buildx context, not on the host. There is no path by which a host-architecture artifact can be smuggled into a prod image, because the artifact in a prod image is always produced inside the same `docker build` invocation that produces the image.

The `build artifact` must always be deposited in the service's `dist/` directory — inside the container during `docker build`, or at `$pr/core/${core_service_name}/dist` on the host during dev iteration (the host folder is the bind-mount of that same path inside the exec container). It is recommended that build-tool cache *not* end up in `dist/`, as `dist/` is cleared before every rebuild.

The developer must write and maintain `build.sh`. They must also write the Dockerfile such that its `build` stage invokes `build.sh` — see [Core Service Containers](./infrastructure.md#core-service-containers).

The build step is required for any environment to actually function. The developer rarely invokes it directly; `./bin/docex envinfra up <env>`, `./bin/docex test`, and `./bin/docex containerize` all cause Docker to build (or rebuild) images as needed, which in turn runs `build.sh` inside the `build` stage.

#### Process (formal, during `docker build`)

This is what runs inside the Dockerfile during `./bin/docex containerize`, `./bin/docex envinfra up`, and `./bin/docex test`. It is not invoked directly by `./bin/docex build`.

1. The `build` Dockerfile stage `COPY`s `src/` (and any other build inputs).
2. It runs `./build.sh`, which deposits artifacts to `/service/dist` inside the stage.
3. The `prod` and `test` stages `COPY --from=build` those artifacts into their final image.
4. A non-zero exit from `build.sh` fails the `docker build` and aborts the calling `docex` command.

#### Process (dev iteration)

This is what `./bin/docex build` performs for the `dev` environment, refreshing artifacts without a container rebuild.

1. Remove all contents of `$pr/core/${core_service_name}/dist` on the development machine.
2. Run `build.sh` in a one-off container of each core service's [exec service](./specifics/migrations.md#dev-and-test-mechanism) — `docker compose run --rm <project>-<env>-<core_service>-exec ./build.sh`. The exec service is the container that *is* the codebase; it is profile-gated, so no part of the dev stack needs to be running, and there is no per-process-type container to pick between.
	+ If any return a non-0 exit code, the build has failed.
	+ If any `dist` folder is empty afterward, the build has failed.
3. Updated artifacts appear in the host's `dist` folder via the container's bind-mount.

No image rebuild is triggered here. Dev iteration is the hot loop, so `./bin/docex build` deliberately runs against the codebase's existing image rather than rebuilding it; a stale image is refreshed by `./bin/docex envinfra up dev`.

#### `docex`
`./bin/docex build` to refresh all core services' `dist/` folders in the `dev` environment.
`./bin/docex build <core_service_name>` to refresh a specific core service.

### Build Test Step

We test a build by running integration and unit tests against it. This is done formally in a fresh `test` environment.

In order for tests to all be automatically run for a project, each core service will need a `test.sh` script. This script is simply a small shim which actually runs the tests (e.g. with `pytest` or whatever) and exits with exit code 0 if all tests pass. It gives these tests a standard form so that build testing can be triggered for a whole project the same way for every project.

#### Process
1. Bring up the `test` environment with docker.
	+ Build occurs implicitly as a byproduct.
2. Run [Migrate Step](#migrate-step) against the `test` env.
	+ If any service's `migrate.sh` returns a non-0 exit code, the build test fails.
3. Run each service's `test.sh`.
	+ If any return a non-0 exit code, the build test fails.
4. Tear down the test environment.

#### `docex`
`./bin/docex test` performs the build testing step.

### Containerize Step

This refers to "formal" containerizing - the process by which a service is made into a container which will be uploaded to the registry for release on `stage` and `prod`. "Informal" containerizing during development is simply achieved with `docker-compose up`.

The formal build is performed *inside* `docker build`: the Dockerfile's `build` stage invokes the service's `build.sh`, and the `prod` stage copies the resulting artifact in. There is no separate pre-build step on the host; the artifact is produced by, and lives entirely within, the `docker build` invocation that produces the image. See [Build Step](#build-step) for the full relationship between `build.sh` and the Dockerfile.

Cross-platform builds are handled by `docker buildx`. The target platform is set explicitly so that a developer on any host architecture (arm64 Mac, amd64 Linux) produces an image whose artifact matches the production runtime. The default target is `linux/amd64`; projects whose `host_machine` or Fargate variant differs may override.

#### Process
1. `docker buildx build --platform <target> --target prod` each core service. The `build` stage runs `build.sh` on the target platform; the `prod` stage receives the artifact via `COPY --from=build`. Resulting images are stored locally.
2. Tag each image as `${container_registry}/${project_name}/${service_name}:${version}` — one image per core service, all sharing the project-wide version from `project.yml`. The registry host is part of the tag, so `docker push` routes correctly without a separate target argument.
3. `docker login` against the project's `container_registry`. Containerize runs this on every invocation regardless of foundation — one uniform codepath. Only the credential source differs:
	+ **Fixed:** static creds previously placed in the operator's `~/.docker/config.json` by a one-time setup login per the [registry-credentials convention](./credentials.md#fixed-container-registry).
	+ **Elastic:** a fresh short-lived token generated via `aws ecr get-login-password`. The token expires after 12 hours, so the per-invocation refresh is necessary (and is what justifies the uniformity — the redundant fixed-side login is the cost of having one codepath instead of two).
4. `docker push` each tagged image.

#### `docex`
`./bin/docex containerize`


### Migrate Step

Migration refers to the step where we need to run a database migration. These are always a little tricky because they hit a backing service which might actually be shared across multiple core services. The doctrine aims to standardize this by requiring every core service that "owns" a database provide a `migrate.sh` script.

This `migrate.sh` is a small shim that actually runs an idempotent migration. Nearly all of the time, this will just be a version of `dbmate up`, but choice of migration tool is ultimately up to the developer. This script should return a non-0 exit code on failure. The migrations themselves live in the `$pr/core/${service}/migrations` folder.

Depending on the target environment, `migrate.sh` will be run a little differently.
`dev` and `test` - `migrate.sh` is run inside the core service's `dev` or `test` container after the compose stack is up.
`stage` and `prod` - Either as a step in the Ansible playbook (fixed) or in the release flow (elastic) *after* database resources exist and are reachable but *before* the new application code is rolled out.

#### Process
1. Run the `migrate.sh` script for every core service that has one. `migrate.sh` will:
	1. Determine database connection from the same env vars the service uses at runtime.
	2. Fire the migration against the database.
	3. Return non-0 if a problem occurs.

#### `docex`
`./bin/docex migrate <env>`

### Release Step

This refers to combining a `build image` and environment-specific config into a release. This same process happens both on `stage` and `prod`.

This process is different depending on whether the project has a `fixed` or `elastic` foundation. The details for this are pretty complex and can be found [here](./specifics/release.md).

#### Process - Fixed-Foundation
1. Use ansible to:
	1. SSH into the production machine in the target environment's location.
	2. `docker pull` all core service container images.
	3. Render relevant configurable vars (from tte/secret/config aggregate) and compose config file from `$pr/infra/output/${env}/docker-compose.yml` into the target environment's location.
	4. Run [Migrate Step](#migrate-step) against the target env using one-off containers from the new images. If any migration fails, abort the release before starting the new stack.
	5. Use docker to start up the production stack with the new images.

#### Process - Elastic-Foundation
1. Update the SSM Parameter Store with configurable vars (from tte/secret/config aggregate).
2. Run [Migrate Step](#migrate-step) against the target env via a one-off ECS task using the new image. If any migration fails, abort the release before applying service changes.
3. Use `tofu apply` to propagate compiled HCL. This will kick off image updates, env var injection, and service config changes.

**First-time release of an env.** On the very first release of an elastic environment, the env's ECS services and RDS the migration task targets don't exist yet — they're created by step 3. (The `<project>-<env>` ECS cluster itself already exists — it is project-tier, created empty by projinfra — so the detector keys off the env's *service*, not the cluster.) `./bin/docex release` detects this case (the env's ECS service is absent from its cluster) and swaps the order to `1 → 3 → 2`: secrets, then `tofu apply` to create infrastructure (and roll out the new image), then migrate against the now-live services + RDS. The migration still runs before the env is considered "deployed successfully". Subsequent releases find the cluster present and follow the steady-state order above.

#### `docex`
`./bin/docex release <env>` release to target environment, where env is either `stage` or `prod`

### Staging Tests

Staging tests verify that a deployed release functions correctly on its infrastructure. They catch problems that service tests can not because service tests run isolated within a singular service. 

Stage tests run at a project-wide level against the staging environment *from* a "stage tester" image. The stage tester image is defined by a developer-maintained dockerfile at `$pr/infra/stage/Dockerfile`. This image simply runs on the development machine. It will build with the libraries needed to run the developer-defined stage tests.

The developer also maintains `$pr/infra/stage/stage_test.sh`. It is a shim that calls the developer's stage tests and returns a non-0 exit code if something fails.

#### Process
1. Ensure the staging environment is deployed and reachable at its public URL
2. Build the staging tester image if missing or stale. Tag with `${project_name}-stage-tester`.
3. Spawn an ephemeral container from the tester image:
	+ `--rm` for auto-cleanup.
	+ Bind-mount the project root to `/project` inside the tester container.
	+ Put the tester on the host network (`--network host`) so it can reach the deployed staging URL.
	+ `STAGING_URL` env var pointing at the deployed staging env.
	+ `PROJECT_VERSION` env var set to the current `project.yml` version. Stage tests that assert the deployed version (e.g., a `GET /health` returning `{"version": "..."}`) read this rather than hand-maintaining a hardcoded expected value, which historically drifts on every version bump.
	+ Command: `/project/infra/stage/stage_test.sh`.
4. `stage_test.sh` runs the project's staging tests against the deployed env via HTTPS.
5. The container exits and is auto-removed; its exit code propagates through `docker run` to `./bin/docex stagetest`.

#### `docex`
`./bin/docex stagetest`

### Rollback

The rollback feature is designed for emergency situations where a serious problem has been released into production. It is intended for reflexive use within an hour or two after release. If issues appear later - perhaps a few days after release - then the problem should be fixed via a new release rather than a rollback.

This "narrow window" rollback philosophy dodges many of the numerous problems associated with rollbacks. Rolling back rolls infrastructure definitions back, which could delete newly-added services with persistent memory. If it's only been a few minutes since release, little to no data will have time to accrue in a new database.

Rollbacks are only intended to go back one minor version. They affect code and infrastructure definitions, but not database schemas. We can pull this trick because database migrations are supposed to be [backwards compatible](./specifics/migrations.md#backward-compatibility-requirement).

#### Process

Rollback reuses the standard [release](#release-step) machinery; what differs is which version's compiled output gets applied, and that the [migrate step](#migrate-step) is skipped. The operator's working tree, `project.yml`, and `main` are left untouched.

1. Verify preconditions. If any fail, abort before touching the environment:
	1. Current branch is `main`; working tree has no uncommitted changes outside `infra/output/`. Dirt under `infra/output/` is tolerated because [`docex release`](#release-step) rewrites it implicitly via its compile step — an emergency operator who just released will legitimately have output drift and shouldn't be forced to commit it before rolling back.
	2. `v<target_version>` git tag exists in the repo.
	3. `<target_version>` is no more than one minor version behind `project.yml`'s current version (e.g. if current is `1.5.2`, target must satisfy `>= 1.4.0`).
	4. `<target_version>`'s `infra.yml` declares a `cicl_version` this `docex` compiles. Rollback recompiles the target's `infra.yml` with the *current* compiler (step 3), so a target predating the v1 → v2 boundary cannot be rebuilt; the check reads the tag's `infra.yml` directly and aborts with a fix-forward message. See [cicl.md § CICL Version](./cicl.md#cicl-version).
	5. Container images at `<target_version>` exist in the registry for every core service.
2. Create an ephemeral worktree at the `v<target_version>` tag.
3. Recompile `infra/output/<env>/` from the worktree's `infra.yml` using the current `docex`. The recompiled output lives only in the worktree.
4. Apply the recompiled output to `<env>` using the standard [release process](#release-step) for the project's foundation, with migrations skipped:
	+ Fixed: invoke the emitted ansible playbook against the host with `--skip-tags migrate`. Ansible pulls the older image, renders the older compose, and `docker compose up -d` converges the stack.
	+ Elastic: push configurable vars to SSM, then `tofu apply` directly against the recompiled HCL. No migration `RegisterTaskDefinition` / `RunTask` step.
5. Discard the ephemeral worktree.

After rollback, the operator's next step is a normal fix-forward release: bump `project.yml` past the broken version on `main`, ship a corrected build through the standard pipeline. The recompile and release at the new version naturally re-converges the env to a healthy state.

#### `docex`
`./bin/docex rollback <env> <target_version>` rolls `<env>` (`stage` or `prod`) back to the specified version.