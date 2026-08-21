# dns

DNS routes an incoming HTTP/S request to the right project, environment, and core service purely by hostname. The doctrine's domain anatomy is:

`<codebase>-<service>.<env>.<project_name>.<apex_domain>` — e.g. `api-web.dev.myproject.example.com`

A single `apex_domain:` field in `infra.yml` sets the project's bare apex (e.g. `example.com`); every environment and service subdomain derives from it. A few "bare" subdomains carry routing rules of their own:

| Subdomain | Routes to |
| --- | --- |
| `<env>.<project_name>.<apex_domain>` | that env's `domain_default_service` |
| `<project_name>.<apex_domain>` | prod's bare-env default (URL ergonomics) |
| `<apex_domain>` | nothing by default |

These are routing choices, not redirects.

- **Fixed:** DNS is prerequisite infrastructure configured in the registrar's console; `docex` does not manage it. The operator points each env subdomain at the host machine once at setup (see `why registrar`).
- **Elastic:** DNS is project infrastructure (AWS Route53). `docex` provisions one hosted zone per project for its `apex_domain` and emits the environment A-records; the operator NS-delegates to that zone once from the parent domain.

Doctrine reference: `infrastructure/cicl.md § Domain`.
