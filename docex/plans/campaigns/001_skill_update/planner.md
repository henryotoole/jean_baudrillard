# Some Ideas

1. `stage` infra should not have delete protection, since it's likely to be taken down almost immediately. For that matter, we should add `envinfra down stage` to the release process so the duplicate resources don't just sit around using resources.

# Definite Fixes

## Major Skill Refactor

This is a major change to the doctrine, but not to docex. The idea is to take the doctrine text (which is rather a lot of lines and tokens at this point) and break it down into three strata (see lexicon). The first is sysprompt, the second is broken out into skills, and the third is a classifier for docex.

In broad strokes, what we need to do is this:
1. (DONE) Document the new strata and how skills will be formed.
2. (DONE) Do a classification pass at all doctrine, breaking it down by section into strata and levels of specificity. This is actively ongoing in a context session on rnd-eins.
3. (DONE) Actually write all the skills (probably LLM does this and I edit it).
4. (DONE) Formalize an update process in practices so that other operators (and myself) can "update" the doctrine by pulling the highest version released on main and running setup.sh to merge over new skills etc. This'll be a process baked into claude, perhaps with a skill itself. We should probably also make a "update a project to newer version of doctrine skill" by the by.
5. (DONE) Write the cohere meta-skill which performs a static audit against the doctrine and the skills that link into it. This skill will cover link checks, skill-reference coverage, resident-discipline (keeping details out of resident-level markdown), and within-doctrine contradictions.

### Refactors and Edits

1. `infrastructure.md` should be edited to move details out and into more specific, non-resident files.
2. `skills.md` (drafted, currently) will need some edits that describe how skills are managed, and I'll have to get claude to confirm.

## DNS and Certs for development-side.

`dev` does not get DNS by default during inception process. on fixed it can't, but on `elastic` it can because Route53 is used. I think that there are two different branches to resolve this depending on whether the [dns] resource is preinfra or projinfra; that is, whether the project is `fixed` or `elastic`:
1. Elastic - Route53 or some other API-driven DNS is used and `projinfra up development` can include dev DNS records.
2. Fixed - `preinfra development` checks whether DNS has been routed and fails if it hasn't. 

When we bring `envinfra` up, traefik attempts certs for all hosts. However, if `dev` and `test` hosts can't be reached because DNS is not set up, then LE's 5-failed-authorizations-per-hour limit is tripped. To avoid this, we need to make sure `dev` dns is handled before envinfra goes up (see above) and remove the mapping to `test` entirely from both DNS and cert fetching.

## Tagging Not Discussed In Mainline

What tags are given resources by the compiler is not listed in the mainline doctrine, and needs to be. Tagging behavior documentation is buried in transfer_tables.md.

## Three Different TODO Lists

This file, engineer/gaps, and engineer/TODO all purport to do the same thing. I need to consolidate them and remove anything that's already handled.

## AWS Account Talk is wrong now

Line 59 of shape: | aws_account | prerequisite | An AWS account | The AWS account in which all elastic resources are provisioned. The doctrine assumes one project per account; multi-tenant accounts are out of scope. |

## No Scheduler Role

There's no transfer-table-defined scheduler role, and we really need one.

## .gitignore standards

Start adding things like *.pyc to gitignore in inception.md.

## Playwright

I really need to write playwright into the doctrine and ship a skill that uses it for testing. Can we do automated tests with playwright? These are questions that need asking.

Two goals:
1. Make playwright available for agents with a skill, for agent-driven investigation and smoke-testing.
2. Make playwright available for basic smoke tests (E2E tests).

## HAProxy Cannot Handle multi-label TLD's

Need to fix this.

## Health Checks And Curl

Double check that `docex check` actually checks whether or not curl is installed on images which need it by their Dockerfiles.