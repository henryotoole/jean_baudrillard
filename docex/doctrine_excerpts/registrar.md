# registrar

A domain registrar — NameSilo, GoDaddy, or similar — is **prerequisite infrastructure** under both foundations: the project does not provision or manage it. The doctrine treats the registrar as a black box that owns the project's apex domain.

- **Fixed:** the registrar's DNS configuration directly routes each environment's subdomain (`dev.<domain>`, `test.<domain>`, `stage.<domain>`, `www.<domain>`) to the appropriate host machine's IP. The doctrine does not automate this — operators wire it once at setup time.
- **Elastic:** the registrar delegates DNS authority to AWS Route53 via NS records, so the project's own HCL can drive DNS without ever touching the registrar console after initial setup.

Doctrine reference: `infrastructure/shape2.md` § Fixed-Foundation / Elastic-Foundation.
