# Lexicon #

This guide defines special words and phrases that have unique context for all markdown files in this folder.

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| The Machine | "The OS" | The OS on which all docker compose projects and services run. |
| Project Root |  | The directory of the root folder of the project. This is not the filesystem root. Sometimes this will be indicated as `$pr` e.g. "$pr/dir/file.txt". |
| Project | "docker compose project", "compose project" | Refers to all code and infrastructure within the scope of the project root. Includes docker compose config, dockerfiles, code architecture, and the code itself. |
| Core Service | "service" | Any docker compose service that uses a Dockerfile to execute code that is unique to this project. |
| Release | A versioned, stable snapshot of the codebase. |
| Deployment | The mechanical act of taking a release and making it live on a machine. |