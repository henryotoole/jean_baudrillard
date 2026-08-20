# Test Running Improvements

I finally worked with a project large enough to have tests that take much time to run. This has led to some pain points which can be corrected partly by changes to `docex` and partly by changes to the wording surrounding it.

## Problem - Overlapping Test Runs

Tests occur in the `test` env on a fixed set of infra resources. While `docex test` *is* wrapped with a `finally` that tears the env back down when it completes (even if it errors), sometimes the test-running agent loses the process running the tests and that process becomes orphaned. When `docex test` is run again, this attempts to use the same infrastructure leading to all sorts of weird errors.

### Solution - Lock

A single-run lock. Have env-mutating commands (test, migrate, …) take a per-(project, env) lock — a flock, or a refuse-if-the-test-project-already-has-containers check — so a second concurrent run refuses rather than silently contending over shared volumes.

## Problem - Tests Take A Long Damn Time

Notably, flow tests are very important but can take *ages* to actually run since they stand up and use real infrastructure.

### Solution - Finer-Grained Test Selection during Mod Cycle

It should be a standard option during a mod cycle or an advance to choose whether to run the full test suite or just affected tests. An advance should always close out with full test runs, and CI/CD will of course always deploy full tests.

## Problem - Tests Can Time out

### Solution