# Some Ideas

1. `stage` infra should not have delete protection, since it's likely to be taken down almost immediately. For that matter, we should add `envinfra down stage` to the release process so the duplicate resources don't just sit around using resources.

# Definite Fixes

## Major Skill Refactor

[DONE]

This is a major change to the doctrine, but not to docex. The idea is to take the doctrine text (which is rather a lot of lines and tokens at this point) and break it down into three strata (see lexicon). The first is sysprompt, the second is broken out into skills, and the third is a classifier for docex.

In broad strokes, what we need to do is this:
1. (DONE) Document the new strata and how skills will be formed.
2. (DONE) Do a classification pass at all doctrine, breaking it down by section into strata and levels of specificity. This is actively ongoing in a context session on rnd-eins.
3. (DONE) Actually write all the skills (probably LLM does this and I edit it).
4. (DONE) Formalize an update process in practices so that other operators (and myself) can "update" the doctrine by pulling the highest version released on main and running setup.sh to merge over new skills etc. This'll be a process baked into claude, perhaps with a skill itself. We should probably also make a "update a project to newer version of doctrine skill" by the by.
5. (DONE) Write the cohere meta-skill which performs a static audit against the doctrine and the skills that link into it. This skill will cover link checks, skill-reference coverage, resident-discipline (keeping details out of resident-level markdown), and within-doctrine contradictions.

### Refactors and Edits

1. (DONE) `infrastructure.md` should be edited to move details out and into more specific, non-resident files.
2. (DONE) `skills.md` (drafted, currently) will need some edits that describe how skills are managed, and I'll have to get claude to confirm.

## DNS and Certs for development-side.

[YOU]

`dev` does not get DNS by default during inception process. on fixed it can't, but on `elastic` it can because Route53 is used. I think that there are two different branches to resolve this depending on whether the [dns] resource is preinfra or projinfra; that is, whether the project is `fixed` or `elastic`:
1. Elastic - Route53 or some other API-driven DNS is used and `projinfra up development` can include dev DNS records.
2. Fixed - `preinfra development` checks whether DNS has been routed and fails if it hasn't. 

When we bring `envinfra` up, traefik attempts certs for all hosts. However, if `dev` and `test` hosts can't be reached because DNS is not set up, then LE's 5-failed-authorizations-per-hour limit is tripped. To avoid this, we need to make sure `dev` dns is handled before envinfra goes up (see above) and remove the mapping to `test` entirely from both DNS and cert fetching.

## Tagging Not Discussed In Mainline

[ME]

What tags are given resources by the compiler is not listed in the mainline doctrine, and needs to be. Tagging behavior documentation is buried in transfer_tables.md.

## No Scheduler Role

[YOU]

There's no transfer-table-defined scheduler role, and we really need one.

## .gitignore standards

[YOU]

Start adding things like *.pyc to gitignore in inception.md.

## Playwright

[YOU]

I really need to write playwright into the doctrine and ship a skill that uses it for testing. Can we do automated tests with playwright? These are questions that need asking.

Two goals:
1. Make playwright available for agents with a skill, for agent-driven investigation and smoke-testing.
2. Make playwright available for basic smoke tests (E2E tests).

## HAProxy Cannot Handle multi-label TLD's

[YOU]

Need to fix this.

## Health Checks And Curl

[YOU]

Double check that `docex check` actually checks whether or not curl is installed on images which need it by their Dockerfiles.


## Implement Tagging Changes

[YOU]

See [this section](../../../../doctrine/infrastructure/cicl.md#naming-and-tagging). This is our first real attempt at setting resource tagging standards cross-infrastructure. The current state of tagging is NOT like this - you'll need to investigate how we tag things know to know clearly what to update.

This will be a change to both doctrine and docex code.

The following is a summary of disruptive changes:
```
 Value changes / removals (the disruptive ones)

  Preinfra — master network (VPC, subnets, IGW, NAT, EIP, route tables):
  - managed_by: docex-preinfra → doctrine-operator ⚠️ load-bearing — pipeline/preinfra.py and emit/templates/project.tf.j2 data sources
  filter on the old value; update both filters.
  - Name: old hand-written values (docex-master-vpc, etc.) → ${shape_name}_${descriptor} form.
  - tier=public|private (subnets): keep as-is, but it's now a resource-local load-bearing tag (under the non-exclusive clause), no longer
  part of the standard block. The subnet data-source lookups still depend on it.

  Preinfra — observability backend (HyperDX EC2 + EBS):
  - prerequisite-infrastructure-telemetry → replaced by the standard preinfra block (shape_name=observability_backend). ⚠️ load-bearing —
  the duplicate-instance guard in telemetry_preinfra.md checks the old tag; repoint it at the new tags.

  Projinfra — Route53 zone (and any project-tier resource using the old 5-tag "per-resource elastic" pattern):
  - Drop env, service, role (those were inappropriate at the project tier).

  Net-new tags to add (alignment, lower risk)

  - All tiers: infra_tier, shape_name, descriptor — new everywhere.
  - Name: new on projinfra and envinfra (envinfra had none; projinfra was mostly untagged).
  - Previously untagged projinfra (ALB, ACM certs, ECR repos, IAM exec role, S3 state bucket + DynamoDB lock table): gain the full
  projinfra block. Note the state backend is tagged via the pre-tofu bootstrap API path, not HCL.
  - CloudWatch log group: had only managed_by=doctrine → gains the full envinfra block.

  Unchanged (so you don't chase them)

  - Envinfra project, env, service, role, managed_by — values unchanged.
  - Projinfra managed_by=doctrine, project — unchanged.
  - purpose=ec2_traefik_acme on the EC2-traefik ACME EBS — unchanged (stays a resource-local load-bearing tag).
```