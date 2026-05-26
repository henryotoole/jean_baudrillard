# Lexicon #

This guide defines special words and phrases that have unique context for all markdown files in this folder.

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| Doctrine |  | Fundamental and immutable rules for software engineering. |
| Development Machine |  | The discrete server on which development occurs. `dev` and `test` envs run here. Code is written here. Git commands, ansible playbooks, and OpenTofu calls originate on this machine with credentials on this machine. |
| Operator |  | The human engineer working on the development machine with LLM's to write code. |
| Project Root |  | The directory of the root folder of the project. This is not the filesystem root. Sometimes this will be indicated as `$pr` e.g. "$pr/dir/file.txt". |
| Project | "codebase" | Refers to all code and infrastructure within the scope of the project root. Includes docker compose config, dockerfiles, code architecture, and the code itself. |
| Service |  | Refers to both "core services" and "backing services". |
| Core Service | "application service", "application container" | Any service that executes code which is unique to this project. |
| Backing Service | "backing service" | A service running code external to the project, like postgres running in a docker compose container or AWS S3. |
| Foundation |  | A project has a `fixed` or `elastic` foundation dependeing on whether a project manages the lifecycle of the machines which run its infrastructure. |
| Environment | "env" | A copy of all environment-tier infrastructure that serves a distinct purpose: `dev`, `test`, `stage`, and `prod`. |
| Infrastructure Tier |  | All infrastructure falls into one of three tiers on the basis of project control and environmental replication. See [here](./infrastructure/infrastructure.md#infrastructure-tiers).
| Shape |  | The fixed topology of a deployed stack: which resources exist, where they live, what depends on what. |
| Stack |  | Loosely describes the machinery that is needed for one environment to run. |
| CICL |  | The language / format in which [`infra.yml`](./infrastructure/cicl.md) is defined. |
| docex |  | Software package which acts as the executor for parts of the doctrine which are so deterministic they can be written into code. |
| build |  | The process by which source code is compiled into a build artifact. |
| release |  | The process by which a containerized built artifact is combined with environment-specific config to run in the `stage` or `prod` environments. |
| Modification | "mod" | The process of designing, implementing, and testing a new feature or change to the codebase. |
| Core Planning Docs | "core docs", "core project docs", "project documentation" | The architectural and module docs found at "$pr/plans/core/*". |
| Objectives |  | Strategic goals for the project. These define what a project *does*. The project is neither complete nor successful until it achieves its objectives. |