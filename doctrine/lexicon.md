---
stratum: resident
---

# Lexicon #

This guide defines special words and phrases that have unique context for all markdown files in this folder.

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| Doctrine |  | Fundamental and immutable rules for software engineering. |
| Development Machine |  | The discrete server on which development occurs. `dev` and `test` envs run here. Code is written here. Git commands, ansible playbooks, and OpenTofu calls originate on this machine with credentials on this machine. |
| Operator |  | The human engineer working on the development machine with LLM's to write code. |
| Project Root | "$pr" | The directory of the root folder of the project. This is not the filesystem root. Sometimes this will be indicated as `$pr` e.g. "$pr/dir/file.txt". |
| jean root | "$jb" | The directory of the root folder of the repo that contains the doctrine, `docex`, etc. Sometimes this will be indicated as `$jb` e.g. "$jb/doctrine/doctrine.md". |
| Project | "codebase" | Refers to all code and infrastructure within the scope of the project root. Includes docker compose config, dockerfiles, code architecture, and the code itself. |
| Service |  | Refers to both "core services" and "backing services". |
| Core Service | "application service", "application container" | Any service that executes code which is unique to this project. |
| Backing Service | "backing service" | A service running code external to the project, like postgres running in a docker compose container or AWS S3. |
| Foundation |  | A project has a `fixed` or `elastic` foundation depending on whether a project manages the lifecycle of the machines which run its infrastructure. |
| Environment | "env" | A copy of all environment-tier infrastructure that serves a distinct purpose: `dev`, `test`, `stage`, and `prod`. |
| Infrastructure Tier |  | All infrastructure falls into one of three tiers on the basis of project control and environmental replication. See [here](./infrastructure/infrastructure.md#infrastructure-tiers). |
| Prerequisite Infrastructure | "preinfra" | Infrastructure outside of project scope. |
| Project Infrastructure | "projinfra" | Infrastructure shared by all environments and driven at the project level. |
| Environment Infrastructure | "envinfra", "env infra" | Infrastructure duplicated across all environments and driven at the environment level. |
| Infrastructure Side | "production side", "development side" | Refers to project infrastructure which services `prod` / `stage` envs (for production side) and `dev` / `test` envs (for development side). What a side *is* depends on foundation; it can be a `fixed` development machine, a `fixed` production machine, or an `elastic` AWS platform. |
| Shape |  | The fixed topology of a deployed stack: which resources exist, where they live, what depends on what. |
| Stack |  | Loosely describes the machinery that is needed for one environment to run. |
| Configurable Vars |  | The unique-per-deployment key/value pairs which are aggregated and injected into containers as environmental variables. Three sources: TTE vars, secrets, and config. |
| CICL |  | The language / format in which [`infra.yml`](./infrastructure/cicl.md) is defined. |
| docex |  | Software package which acts as the executor for parts of the doctrine which are so deterministic they can be written into code. |
| build |  | The process by which source code is compiled into a build artifact. |
| release |  | The process by which a containerized built artifact is combined with environment-specific config to run in the `stage` or `prod` environments. |
| Modification | "mod" | The process of designing, implementing, and testing a new feature or change to the codebase. |
| Core Planning Docs | "core docs", "core project docs", "project documentation" | The architectural and module docs found at "$pr/plans/core/*". |
| Objectives |  | Strategic goals for the project. These define what a project *does*. The project is neither complete nor successful until it achieves its objectives. |
| Apex Domain |  | An absolute top-level domain without any subdomains e.g. `example.com` |
| Master Network | `master_network`, `master_vpc` | The main, toplevel network which spans all projects. |
| Stratum | "strata" (pl.) | A classification of doctrine *information* by when it is needed. There are three: the resident, conditional, and executor strata. See [overview](./doctrine.md#strata). |
| Resident Stratum |  | The stratum of doctrine information needed to write any line of code; always resident in context, never gated behind a skill. |
| Conditional Stratum |  | The stratum of doctrine information needed only for a specific activity (e.g. a release); broken into thread skills loaded when the agent undertakes that activity. |
| Executor Stratum |  | The stratum of doctrine encoded as action-taking code (`docex` and its shim); used by doctrine-following agents. |
| Thread Skill |  | A skill which ties a set of conditional stratum documents together into a package based around and triggered by an action. Acts as a router and orienting info to "thread" doctrine files together. |