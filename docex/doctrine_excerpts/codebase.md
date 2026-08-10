# codebase

One source tree and the single build artifact — one `build_image` — compiled from it. The codebase is the unit of *code*; the `core_service` is the unit of *deployment*.

A codebase declares one or more core services under `codebases.<name>.core_services` in `infra.yml`. Every one of them runs that same image, started a different way.

**Codebases never share code.** Each is a distinct source tree and one codebase never imports from another. All that ties them together is a shared purpose, shared backing services, and the single project-wide version.

What stays codebase-scoped rather than per-core-service: the image ref and its registry repository, `schema_owned_by` (so `migrate.sh` runs once per codebase), the `core/<name>/` source folder with `build.sh` / `test.sh` / `health.sh` / `migrate.sh` (`migrate.sh` only where the codebase owns a schema), and the `secrets:` / `config:` / codebase-level `env:` blocks.

A codebase lives at `$pr/core/<name>/` and ships a Dockerfile declaring the four canonical stages (`build`, `dev`, `prod`, `test`).

Doctrine reference: `infrastructure/infrastructure.md` § Repository Structure; `infrastructure/cicl.md` § Core Services; `lexicon.md`.
