# dns

DNS routes incoming HTTP/S requests to the right environment by hostname. The doctrine derives all four environment subdomains from a single `domain:` field in `infra.yml`:

| Env | Subdomain |
| --- | --------- |
| dev | dev.<domain> |
| test | test.<domain> |
| stage | stage.<domain> |
| prod | www.<domain> |

Apex (`<domain>` itself) is never served — operators handling apex-to-`www` redirection do so at the registrar.

- **Fixed:** DNS is prerequisite infrastructure handled in the registrar's console. `docex` does not configure it.
- **Elastic:** DNS is project infrastructure (AWS Route53), provisioned by `docex compile` output. The registrar delegates NS to Route53 once at setup.

Doctrine reference: `infrastructure/cicl.md` § Domain.
