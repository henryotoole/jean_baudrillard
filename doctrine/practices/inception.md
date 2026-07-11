---
stratum: conditional
---

# Inception

This module describes the opening acts of creating a project from nothing. The inception process covers all the setup steps from "all we have is a rough idea in the form of a [masterplan](./docs.md#the-masterplan) document" to "the project is ready for regular [mod](./modifications.md) cycles and production releases".

## Initial State

Before a project's inception, only the following "inputs" exist:
1. A `masterplan.md` document, detailing the project's:
	1. Name
	2. Objectives
	3. Project-specific terms and concepts
	4. Infrastructure, sometimes down to the hexagonal-module level.
		+ Includes domain and foundation.
	5. Flows
2. A "projects" directory on a development machine where the github repo will be cloned.
3. The project owner's github credentials, available on the development machine.

## Inception Process

This flow is handled by an LLM.

__PART I__: Setup
1. Read the `masterplan.md`. If the operator has not indicated where this is, ask them.
2. Determine the project's machine-readable name from its plain text name. It should be in snake_case, and will be immutable after the project is set up. We'll refer to this as `${project_name}`.
3. Create a git repository for the project with the available credentials.
	+ Most of the time, the git host will be 'github' and the `gh` command can be used to achieve this.
	+ The repo should **always** be private - if it can not be made private, do not proceed.
4. Clone the new repository into the "projects" directory. The folder created by the clone operation will be the "project root" or `$pr`. All further work will happen out of this directory.
5. Change directory into the project folder e.g. `cd ${project_name}`
6. Create a branch called "inception_and_first_draft" and switch to it.
7. Set up some basic structure for the project:
	1. Create or update `.gitignore` file with the [default](#gitignore-defaults) below.
	2. Add the critical `project.yml` file from the [default](#projectyml-default) below.
	3. Add a `README.md` with a brief couple of sentences that describe the project.
	4. Add `CHANGELOG.md` from the [default](#changelogmd-default)
	5. Create the project folder structure as specified in [infra](../infrastructure/infrastructure.md#codebase-structure) down to:
		1. `core` folder, no subfolders.
		2. `infra` folder, all direct child subfolders.
			+ `secrets`, `config`, `tte`, and `deploy_creds` should each be given [infra `.gitignore`](#infra-gitignore-files) files.
		3. `plans` folder, all direct child subfolders but no files.
	6. Write `masterplan.md` verbatim into its place at `$pr/plans/core/masterplan.md`.
8. Install `docex` (see [install instructions](../infrastructure/docex.md#project-installation)).
	1. Test that it works with `./bin/docex --version`.
9. Make a commit with the message "Inception Part I: setup complete".

__PART II__: Design
The project has now been set up. Basic structure exists and the `masterplan.md` is in the defined place. Everything from this point on goes wherever the `doctrine` prescribes.

Pause here to ask the operator whether they wish to design the architecture:
A) Entirely by themselves
B) By working with the LLM
C) By handing full architecture authority to the LLM.

The design phase should "fill out" the [core planning docs](./docs.md#core-planning-documents). Each core service should be given a folder in `$pr/plans/core`, and filled out with architecture and design docs. Core services with internal hexagonal architecture should have module docs for each planned hexagonal module. Core services which [own the schema](../infrastructure/cicl.md#the-cicl-format) for a relational database should get a `db_schema.md` file documenting relational schema choices.

All these core planning docs are driven by `masterplan.md`. They "unpack" those high-level plans into more concrete architecture and design docs. 

__PART III__: Infrastructure Smoke Test
1. Make a commit with the message "Inception Part II: design complete"
2. Route DNS to `dev`, either with registrar DNS or Route53 depending on what is appropriate.
3. Verify development preinfra exists with `./bin/docex preinfra development`
	+ If it doesn't exist or is broken, load the `preinfra-setup` skill and create / fix needed resources.
4. Write `infra.yml` to reflect the needs of the core planning docs.
5. Create the core service folders in `$pr/core` and the infrastructural concerns within each:
	1. A Dockerfile that defines the environment.
		+ These don't need to be perfect. At this stage, we only know what the core services are and probably what language they'll be in. These must exist to smoke test the infrastructure; details will be worked out later in the mod cycles.
	2. `dist`, `src`, and `tests` folders.
		+ These will be empty.
	3. Infrastructure scripts: `build.sh`, `test.sh`.
		+ These can be empty, they must merely exist.
	4. If this core service owns the schema for a relational database, also create `migrate.sh` and the `migrations` folder.
		+ These can be empty, they must merely exist.
6. Compile `infra.yml`.
7. Use `./bin/docex secrets scaffold` and `./bin/docex config scaffold` to create configurable var `<env>.env` files.
	1. Set needed values in `$pr/infra/config/<env>.env` for `dev` and `test`.
	2. Work with the operator and use `./bin/docex secrets` commands to set needed secret values for `dev` and `test`. 
8. Bring project infrastructure online with `./bin/docex projinfra up development`
9. Bring the `dev` environment up to smoke test that the infrastructure works.
	1. Check that the environment comes up without error.
10. Take the `dev` environment back down.
11. Make a commit with the message "Inception Part III: infrastructure smoke tested"

__PART IV__: First Draft
The project has been set up and has a `dev` and `test` env that work. The next step is the "first draft" of the project where the initial design state is implemented. This will be done in one or more [modification](./modifications.md) cycles.

The process is roughly:
1. Perform one or more mod cycles to build the first draft of the project.
2. Make a commit "Inception Part IV: first draft complete"

The first of these cycles is very important. It must do the following very well:
1. Write the contents of `build.sh` and `test.sh` for the first time for each core service.
2. Adjust each core service's Dockerfile for the specifics of the service it will be running.
3. Core services which [own the schema](../infrastructure/cicl.md#the-cicl-format) for a relational database will need to write the initial migration file(s) which set up the database and the `migrate.sh` script which runs it.
4. Write the first drafts of [contracts](../infrastructure/contracts.md) for "provider" core services.

The files in the above list will likely be edited again in future mods. However, this first one is terribly important because it establishes the conventions that future mods will follow. Care should be taken to get them right.

__PART V__: First Production Release
Much time may separate __PART IV__ and __PART V__. The operator may wish to keep the project in development for a while and iterate with mod cycles. Eventually, however, the first real production release will need to occur. The following steps must be performed before the `docex` machinery can perform its first release.
1. The relevant [deploy credentials](../infrastructure/credentials.md#deploy-credentials) must be provided.
	1. Check if the credentials exist, and if they do not, tell the operator to get them.
2. Set all needed configurable vars for `stage` and `prod`:
	1. Set needed values in `$pr/infra/config/<env>.env` for `stage` and `prod`.
	2. Work with the operator and use `./bin/docex secrets` commands to set needed secret values for `stage` and `prod`. 
3. The `$pr/infra/stage` resources will need to be created. These are described in detail [here](../infrastructure/tests.md#staging-tests).
4. Verify production preinfra exists with `./bin/docex preinfra production`
	+ If it doesn't exist or is broken, load the `preinfra-setup` skill and create / fix needed resources.
5. Setup production project infrastructure with `./bin/docex projinfra up production`. There may need to be an operator NS-delegation step at the parent registrar if it has not been done before for the project domain.
6. The LLM should carefully proceed along the CI/CD pipeline. See [CI/CD Pipeline](../infrastructure/cicd.md#the-pipeline) and run each step in order.

After doing a production release for the first time, any barriers will be overcome and future releases will proceed smoothly.

### `.gitignore` Defaults
```
# Build artifacts (dev-iteration only; prod artifacts live inside images)
core/*/dist/

# OpenTofu local state and plan files (state is remote per
# projinfra/elastic_state_backend; .terraform/, plans, and state are local.
# .terraform.lock.hcl is NOT ignored — the provider lock is committed, which
# the doctrine's determinism promise wants.)
infra/output/**/.terraform/
infra/output/**/*.tfplan
infra/output/**/*.tfstate*

# docex ephemeral git worktrees
.docex/

# The infra value/credential dirs (secrets, config, tte, deploy_creds) are
# gitignored per-directory by their own infra .gitignore files — see the
# "Infra .gitignore Files" section below. Nothing about them is needed here.

# Python bytecode + tool caches
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/

# Editor / IDE
.idea/
.vscode/

# Logs
*.log

# OS noise
.DS_Store
Thumbs.db
```

The block above covers Python (docex's own language and a common project choice)
plus universal editor/OS noise. Projects add language-specific artifact patterns
for their stack as needed — e.g. `node_modules/` (Node), `target/` (Rust/Cargo),
`bin/` (Go).

### Infra `.gitignore` Files
One file to apply to `infra/secrets`, `infra/config`, `infra/tte`, and `infra/deploy_creds`.
```
*
!.gitignore
!README.md
!*.pub
```

### `project.yml` Default
```yml
name: ${project_name}
version: "0.0.1"
```
The `docex_version` field is appended to this file by `docex_install.sh` in PART I step 8 — do not write it by hand.

### `CHANGELOG.md` Default

```md
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project incepted.

```