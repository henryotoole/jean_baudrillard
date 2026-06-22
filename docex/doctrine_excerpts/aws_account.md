# aws_account

The AWS account in which all elastic-foundation resources are provisioned. **Prerequisite infrastructure**: `docex` does not create or manage AWS accounts. The doctrine assumes **one project per AWS account** — multi-tenant accounts are out of scope.

This isolation is deliberate. A single project per account means the project's IAM policies, billing tags, security boundaries, and audit trails are uncomplicated. When two projects need to share resources, they should do so via explicit cross-account roles, not by squeezing into the same account.

Doctrine reference: `infrastructure/shape.md` § Elastic-Foundation.
