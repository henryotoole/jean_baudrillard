# aws_account

The AWS account in which a project's elastic-foundation resources are provisioned. **Prerequisite infrastructure**: `docex` does not create or manage AWS accounts.

The doctrine assumes **many projects may share one AWS account**. Projects are not isolated by account; they are isolated *within* an account by naming, tags, security groups, and IAM scoping. Multiple elastic projects sit side by side in the same account and share one prerequisite **master VPC** (see `why master_network`) — its Internet Gateway, NAT gateway, and subnets are shared across every elastic project in the account. Each project still gets its own reverse proxy, ECR repository, Route53 zone, and per-env security groups, so blast-radius protection comes from those per-project resources rather than from an account boundary.

Doctrine reference: `infrastructure/shape.md § Elastic-Foundation`.
