# Test Running Improvements

I finally worked with a project large enough to have tests that take much time to run. This has led to some pain points which can be corrected partly by changes to `docex` and partly by changes to the wording surrounding it.

## Problem - Overlapping Test Runs

Tests occur in the `test` env on a fixed set of infra resources. While `docex test` *is* wrapped with a `finally` that tears the env back down when it completes (even if it errors), sometimes the test-running agent loses the process running the tests and that process becomes orphaned. When `docex test` is run again, this attempts to use the same infrastructure leading to all sorts of weird errors.

### Solution - Lock

A single-run lock. Have env-mutating commands (test, migrate, …) take a per-(project, env) lock — a flock, or a refuse-if-the-test-project-already-has-containers check — so a second concurrent run refuses rather than silently contending over shared volumes.

## Problem - Tests Take A Long Damn Time, Slowing Mod Cycles

Notably, flow tests are very important but can take *ages* to actually run since they stand up and use real infrastructure.

### Solution - Finer-Grained Test Selection during Mod Cycle

It should be a standard option during a mod cycle or an advance to choose whether to run the full test suite or just affected tests. An advance should always close out with full test runs, and CI/CD will of course always deploy full tests.

## Problem - Long Test Times Double for CI/CD

The CI/CD process runs `docex check` in the trunk branch and then `docex merge` to merge the trunk into main. `merge` runs *another* `docex check` by design to ensure that the absolute final released commit gets tested.

### Solution - Intelligent Second-Check Running

The easiest solution is to only run the second check if the code has *actually changed* since the first check. While it's easy enough to tell whether the codebase has changed, the two commands being run independently may present a problem (`docex merge` may not be able to tell when the last `docex check` has been run). Perhaps `docex check` should leave some sort of fingerprint (a checksum of the committed repo)? Or, alternately, we could make some `docex cicd` command that just runs the whole chain, running both `check` commands and therefore knowing if merging branches caused a change between them.

See [this](./redundant_merge_recheck.md).

## Problem - Tests Can Time out

See [this](./docex_test_command_monolith_limitations.md) for the problem and a limited solution. The real solution will take some design work.

## Problem - No Standard Way to Run Subset

Right now, the only doctrine-blessed way to run tests is to run *all the tests*. This means that correcting a single failing test in development requires re-running them all. This either is very slow, or forces the developer to come up with some bespoke command they can use to run just a few tests. In practice, the developer-agent does this every time but with mixed success (wasting tokens and time as it works out the right docker invocation). 

### Solution - Define Standard Way

I'm thinking of using either the `dev` or `test` env. Whichever we use, it's best if it stays "hot" after the test (perhaps leaning us towards using `dev` for this). Some research ought to be done into what's best. Questions:
1. What env to use?
2. Whether the standard invocation should be synchronous or asynchronous (see [monolith limitations](./docex_test_command_monolith_limitations.md)).
3. Whether we build this into the `docex test` command or just hand the developer-agent instructions on how to inject their own `pytest` invocations (or whatever is correct for the language / test framework).