# Lexicon #

This guide defines special words and phrases that have unique context for all markdown files in this folder.

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| Doctrine |  | Fundamental and immutable rules for software engineering. |
| The Machine | "The OS" | The OS on which all docker compose projects and services run. |
| Project Root |  | The directory of the root folder of the project. This is not the filesystem root. Sometimes this will be indicated as `$pr` e.g. "$pr/dir/file.txt". |
| Project | "docker compose project", "compose project" | Refers to all code and infrastructure within the scope of the project root. Includes docker compose config, dockerfiles, code architecture, and the code itself. |
| Service |  | A distinct piece of infrastructure. Docker compose containers are services. AWS S3 is a service. |
| Core Service | "application service", "application container" | Any service that executes code which is unique to this project. |
| Backing Service | "backing service" | A service running code external to the project, like postgres running in a docker compose container or AWS S3. |
| Release | | A versioned, stable snapshot of the codebase. |
| Deployment | | The mechanical act of taking a release and making it live on a machine. |
| Modification | "mod" | The process of designing, implementing, and testing a new feature or change to the codebase. |
| Core Planning Docs | "core docs", "core project docs", "project documentation" | The architectural and module docs found at "$pr/plans/core/*". |
| Objectives |  | Strategic goals for the project. These define what a project *does*. The project is neither complete nor successful until it achieves its objectives. |