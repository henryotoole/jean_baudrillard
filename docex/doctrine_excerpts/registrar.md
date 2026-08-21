# registrar

A domain registrar — NameSilo, GoDaddy, or similar — is **prerequisite infrastructure** under both foundations: the project neither provisions nor manages it. The doctrine treats the registrar as a black box that owns the project's `apex_domain`.

- **Fixed:** the registrar's own DNS routes each environment's subdomain — `dev.<project_name>.<apex_domain>`, `test.…`, `stage.…`, `prod.…`, plus the bare `<project_name>.<apex_domain>` — to the host machine's IP. `docex` does not automate this; the operator wires it once at setup.
- **Elastic:** the registrar delegates DNS authority for the project's zone to AWS Route53 via NS records, so the project's own compiled HCL drives DNS without touching the registrar console after initial delegation.

Doctrine reference: `infrastructure/shape.md § Fixed-Foundation`.
