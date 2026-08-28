---
stratum: resident
---

# Lexicon #

This guide defines special words and phrases that have unique context for all markdown files in this folder. It defines *concepts*, not CICL field names: `uses`, `role`, `env:`, and `networks:` are specified in [cicl.md § Service Fields](./infrastructure/cicl.md#service-fields) rather than here.

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| Doctrine |  | Fundamental and immutable rules for software engineering. |
| Development Machine |  | The discrete server on which development occurs. `dev` and `test` envs run here. Code is written here. Git commands, ansible playbooks, and OpenTofu calls originate on this machine with credentials on this machine. |
| Operator |  | The human engineer working on the development machine with LLMs to write code. |
| Project Root | "$pr" | The directory of the root folder of the project. This is not the filesystem root. Sometimes this will be indicated as `$pr` e.g. "$pr/dir/file.txt". |
| jean root | "$jb" | The directory of the root folder of the repo that contains the doctrine, `docex`, etc. Sometimes this will be indicated as `$jb` e.g. "$jb/doctrine/doctrine.md". |
| Project |  | Refers to all code and infrastructure within the scope of the project root. Includes docker compose config, dockerfiles, code architecture, and the code itself. |
| Service |  | Refers to both "core services" and "backing services". |
| Core Service |  | A named, independently-scaled deployment of a codebase's build artifact — its own role, command, resources, networks, and port. One codebase declares one or more. Addressed as `<codebase>.<service>` (e.g. `api.web`). |
| Backing Service | "backing service" | A service running code external to the project, like postgres running in a docker compose container or AWS S3. |
| Codebase |  | The bundle of source code for a core-service family, and the single build artifact and image compiled from it. One codebase never imports code from another. Declares one or more core services, all of which run that same image. A codebase is the unit of *code*; a core service is the unit of *deployment*. |
| Entrypoint |  | The *code module* a core service's `command` invokes. Binds the composition root's driving adapters to a runtime host. One entrypoint per core service. Not an infrastructure noun — the word is already spent on the Dockerfile `ENTRYPOINT` and on traefik entrypoints. |
| Surface |  | The API which allows interaction with a core service from the "outside". Every surface has a contract defining its function. A core service can have zero, one, or many surfaces. |
| Foundation |  | A project has a `fixed` or `elastic` foundation depending on whether a project manages the lifecycle of the machines which run its infrastructure. |
| Environment | "env" | A copy of all environment-tier infrastructure that serves a distinct purpose: `dev`, `test`, `stage`, and `prod`. |
| Slot | "slot" | An isolated instance of an env's infrastructure stack. Purpose, configurable environmental variables, and structure are all shared by same-type slots. Only currently implemented for the `test` env. |
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
| Modification | "mod" | The process of designing, implementing, and testing a new feature or change to the project. |
| Core Planning Docs | "core docs", "core project docs", "project documentation" | The architectural and module docs found at "$pr/plans/core/*". |
| Objectives |  | Strategic goals for the project. These define what a project *does*. The project is neither complete nor successful until it achieves its objectives. |
| Apex Domain |  | An absolute top-level domain without any subdomains e.g. `example.com` |
| Master Network | `master_network`, `master_vpc` | The main, toplevel network which spans all projects. |
| Stratum | "strata" (pl.) | A classification of doctrine *information* by when it is needed. There are three: the resident, conditional, and executor strata. See [overview](./doctrine.md#strata). |
| Resident Stratum |  | The stratum of doctrine information needed to write any line of code; always resident in context, never gated behind a skill. |
| Conditional Stratum |  | The stratum of doctrine information needed only for a specific activity (e.g. a release); broken into thread skills loaded when the agent undertakes that activity. |
| Executor Stratum |  | The stratum of doctrine encoded as action-taking code (`docex` and its shim); used by doctrine-following agents. |
| Thread Skill |  | A skill which ties a set of conditional stratum documents together into a package based around and triggered by an action. Acts as a router and orienting info to "thread" doctrine files together. |