# doc-coherer — agent test

The mandated interface file for this agent's test folder. A test-orchestrator reads
this to run the tests; everything else in this folder is free-form interior it
references (seed repositories, fixtures, helper scripts, grading rubrics).

## Subject

- **Agent:** `doc-coherer` (`agents/private/doc-coherer.md`)
- **What it does:** edits a project's design and code-level docs so they are
  internally consistent and accurately describe the code as written. The graded
  artifact is the *change it effects*.

## Setup

<!-- TODO: how the orchestrator assembles the test world — e.g. copy the seed code
body into a scratch working tree outside this repo and record a baseline commit so
the agent's edits can be captured. Reference the interior fixtures/scripts here. -->

## Cases

<!-- TODO: one entry per test case. For each, state:
     - Arrange — the starting doc/code state to put in place.
     - Act     — how to invoke doc-coherer (the subject files + overhead files to
                 pass it).
     - Assert  — what a correct result looks like, as verifiable expectations. -->

## Grade

<!-- TODO: how the effected change is judged against each case's expectations. -->

## Teardown

<!-- TODO: cleanup (e.g. remove the scratch working tree). -->
