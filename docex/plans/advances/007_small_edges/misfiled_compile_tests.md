# Sixty fast compile tests live in `tests/integration/`, and the conventional pair of invocations has a hole between them

**Found:** advance 006, mod 128, while re-deriving baselines.

## What happened

At `d185054`, `pytest tests` reported **1104 passed, 12 FAILED**. At the same
commit, `pytest tests/unit` reported **1052 passed, green** — and 1052 is the
number the advance 006 plan carries, the number three mod briefs carried, and the
number mods 125, 126, and 127 each reported a green suite against.

All twelve failures were in `tests/integration/test_compile.py`:

| Count | Cause | Went red in |
| --- | --- | --- |
| 10 | `_SECRET_INFRA` and `_NAMING_INFRA` — two inline `infra.yml` documents — declare a `web`-network core service with no `health_check_path`, which mod 125's **rule 33** now requires. | advance 006, mod 125 |
| 1 | `test_project_tier_task_execution_policy_empty_core_services` pins `cicl_version: "2"`. | advance **005** |
| 1 | `test_describe_dag_and_llm` asserts `"depends_on" in out`; the field was retired. | advance **005** |

Two of the twelve had been red since advance 005 — the advance whose report
records "unit 1009, integration 20/0". They went red inside it, and nothing ran
the invocation that would have shown it.

Mod 128 fixed all twelve as CICL conformance (the inline documents were simply
invalid under the current generation of the format, and were corrected to be
valid). **That fix is not what this brief is about.**

## The mechanism

`tests/integration/test_compile.py` holds **61 tests, of which exactly one carries
`@pytest.mark.integration`.** The other 60 are fast, pure, in-process compile
tests that need no docker, no AWS, and no network. They run in the default suite.

`pyproject.toml` sets `addopts = "-m 'not integration'"`, so the two conventional
invocations are:

- `pytest tests/unit` — collects `tests/unit/` only. **Cannot see the 60.**
- `pytest tests -m integration` — collects the 18 marked tests. **Cannot see the 60.**

The 60 are visible only from `pytest tests`, which is neither of the two commands
anybody was running. The directory name says "integration", the marker says
otherwise, and the hole is invisible from both sides — which is why it stayed open
across two advances. Nobody was careless; the instrument had a blind spot exactly
the width of one file.

## Why it is worth a brief rather than a shrug

The twelve tests are fixed, so there is nothing red today. What survives is the
structure that opened the hole, and it will open again the moment a rule changes
under one of those 60 tests.

This is the third instance in advance 006 of one defect: **a number inherited
rather than re-derived.** The other two are
[`test_fixture_base_image_rot.md`](./test_fixture_base_image_rot.md) and the
advance plan's own correction that the seed projects are invisible to pytest
(`advance_plan.md`, Phase 3). All three are advance 005's catalogued failure
arriving in the *instrument* rather than in the code.

## Two candidate fixes — deliberately not chosen here

1. **Relocate the 60 to `tests/unit/`.** They belong there by every property that
   matters: fast, hermetic, no real boundary crossed. The file would split into
   `tests/unit/test_compile.py` (60) and whatever the one genuinely-integration
   test needs. Makes the directory name true.
2. **Mark them honestly and leave them where they are.** Add
   `pytestmark = pytest.mark.integration` — but this is the *wrong* honesty: it
   would move 60 fast tests into the expensive suite that gets run rarely, which
   trades a visible hole for a slow one. The variant worth considering is a third
   marker (`compile`) and a `pyproject.toml` that names all the buckets, so no
   test can belong to none of them.

A third option, which is not a fix but a guard and is cheap alongside either:
assert in CI that `collected(tests/unit) + collected(-m integration) ==
collected(tests)`. That makes a future hole fail rather than hide, which is the
property both fixes above are actually trying to buy.

## Two operational facts to record while they are cheap

**`pytest tests -m integration` must be run alone.** Measured in mod 128: run
concurrently with other pytest processes, it produced **five** failures —
`test_migrate_real`, `test_migrate_cold_stack`, `test_up_down_real`,
`test_test_real`, `test_build_real` — presenting as docker DNS failures resolving
`sample-dev-appdb` and an unset `POSTGRES_PASSWORD`. Run alone at the same
commit: **18 passed**. Every one of those five is a convincing false positive
that a reader would diagnose as a real defect in migrate, up/down, or build. The
integration tests bring up real compose stacks with fixed project names and
contend for docker's network state; they are not parallel-safe against
themselves.

**The default suite is `pytest tests`.** Adopted as a standing instruction for
the remainder of advance 006 by operator ruling at mod 128's design review, along
with re-deriving suite counts at close-out rather than quoting a subagent's
figures.
