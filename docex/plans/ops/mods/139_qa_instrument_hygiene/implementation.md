# Mod 139 — implementation steps

Repo root: `/home/ubuntu/.claude/jean_baudrillard` (call it `$jb`). The docex
project is `$jb/docex`. Branch is `advance_008_housekeeping` (do not create or
switch branches). `python` is NOT on PATH — use `$jb/docex/.venv/bin/python`, and
run pytest **from `$jb/docex`**.

Two independent halves; do them in any order. All file paths below are absolute
from `$jb`. **Do not touch core planning docs** (`$jb/docex/plans/core/*`) — the
corporal updates those separately.

---

## HALF A — linkcheck scope + CHANGELOG repair

All edits to one code file (`$jb/skills/cohere/executor/linkcheck.py`), its two
test suites, `$jb/CHANGELOG.md`, `$jb/RELEASING.md`, and `$jb/upgrades/README.md`.

### A2 — file-as-root in `linkcheck.py`

**Edit `markdown_files`.** Replace:

```python
def markdown_files(root):
    """Every `.md` under `root`, generated residue skipped."""
    out = []
```

with:

```python
def markdown_files(root):
    """Every `.md` under `root`, generated residue skipped.

    A `root` may be a single `.md` file, not only a directory — this is how the
    repo-root files (CHANGELOG.md, README.md, RELEASING.md) enter the scan. A file
    root yields just itself; a non-`.md` file root yields nothing.
    """
    if os.path.isfile(root):
        return [os.path.realpath(root)] if root.endswith(".md") else []
    out = []
```

**Edit `main()` root validation.** Replace:

```python
    for r in roots:
        if not os.path.isdir(r):
            print(f"ERROR: root not found: {r}", file=sys.stderr)
            return 2
```

with:

```python
    for r in roots:
        if not (os.path.isdir(r) or (os.path.isfile(r) and r.endswith(".md"))):
            print(f"ERROR: root not found (or not a .md file): {r}", file=sys.stderr)
            return 2
```

### A3 — inline suppression marker

**Add a module constant** next to the other regex/constant definitions (after the
`EXTERNAL_PREFIXES = (...)` line):

```python
LINKCHECK_IGNORE = "<!-- linkcheck-ignore -->"
```

**Edit `scannable_lines`** — add the suppression skip immediately after the frozen
skip. Replace:

```python
        if frozen:
            stats["frozen_lines"] += 1
            continue
        yield i, line
```

with:

```python
        if frozen:
            stats["frozen_lines"] += 1
            continue
        # Per-line suppression: a LIVE line that QUOTES a dead reference as
        # evidence cannot be repaired without destroying the evidence. Skipped,
        # but counted — a verifier may decline, not decline quietly.
        if LINKCHECK_IGNORE in line:
            stats["suppressed"] += 1
            continue
        yield i, line
```

**Add `"suppressed": 0,`** to the `stats` dict in `run_checks`. Replace:

```python
        "files": len(md_files), "check3_files": 0, "frozen_lines": 0,
```

with:

```python
        "files": len(md_files), "check3_files": 0, "frozen_lines": 0,
        "suppressed": 0,
```

**Add a summary print line** in `main()`. Replace:

```python
    print(f"  frozen changelog lines    : {stats['frozen_lines']} skipped")
    return 1 if problems else 0
```

with:

```python
    print(f"  frozen changelog lines    : {stats['frozen_lines']} skipped")
    print(f"  linkcheck-ignore lines    : {stats['suppressed']} suppressed")
    return 1 if problems else 0
```

### A5 — add the three root files to `DEFAULT_ROOTS`

Replace the `# WHY these five:` comment block and the `DEFAULT_ROOTS = [...]` list
with:

```python
# WHY these roots: every live doctrine-adjacent markdown artifact. Five directory
# roots plus the three repo-root markdown files. Frozen records (mod/advance docs,
# upgrade guides) and deliberately-broken fixtures (skill_iter's drift fixtures)
# stay out — their stale links are the record or the fixture, not a finding.
#   doctrine_excerpts/  is REQUIRED: the dead citation that motivated check 1b
#                       lived there, and it is the one aligned artifact with no
#                       other automated consumer.
#   test_projects/      brings PRE_CUT_CHECKLIST.md — which gates both smoke
#                       walks — inside the shipped default reach.
#   CHANGELOG/README/RELEASING  are file roots (see markdown_files). CHANGELOG.md
#                       is scanned, but its RELEASED sections stay frozen-skipped
#                       (scannable_lines) — only the live [Unreleased] section, and
#                       any line NOT carrying a `<!-- linkcheck-ignore -->` marker,
#                       is enforced.
DEFAULT_ROOTS = [
    DOCTRINE_ROOT,
    SKILLS_ROOT,
    os.path.join(JB_ROOT, "docex", "doctrine_excerpts"),
    os.path.join(JB_ROOT, "docex", "plans", "core"),
    os.path.join(JB_ROOT, "docex", "test_projects"),
    os.path.join(JB_ROOT, "CHANGELOG.md"),
    os.path.join(JB_ROOT, "README.md"),
    os.path.join(JB_ROOT, "RELEASING.md"),
]
```

**Update the module docstring Usage block.** Replace:

```
Usage:
    python3 linkcheck.py [ROOT ...]

ROOTs default to DEFAULT_ROOTS below. Exits non-zero if any problem is found.
```

with:

```
Usage:
    python3 linkcheck.py [ROOT ...]

A ROOT may be a directory (walked for `.md` files) or a single `.md` file — the
latter is how the repo-root files (CHANGELOG.md, README.md, RELEASING.md) join
the scan. ROOTs default to DEFAULT_ROOTS below. Exits non-zero if any problem is
found.

A line carrying the marker `<!-- linkcheck-ignore -->` is skipped and counted
(never silently): the one repair for a LIVE line that quotes a dead reference as
evidence, which cannot be fixed without destroying the evidence.
```

### A-tests-1 — CLI-seam tests (file-as-root)

Append to `$jb/docex/tests/unit/test_linkcheck.py` (this is the `main()`/argv/
exit-code seam suite; runs in the docex suite):

```python
def test_single_markdown_file_root_is_scanned_and_enforced(
    linkcheck, monkeypatch, tmp_path, capsys
):
    """A ROOT may be a single .md file — how CHANGELOG/README/RELEASING enter the
    scan. The live [Unreleased] link is enforced; the frozen section's is not."""
    (tmp_path / "doctrine").mkdir()
    (tmp_path / "doctrine" / "alpha.md").write_text("# Alpha\n")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n"
        "live [ok](./doctrine/alpha.md) and [bad](./doctrine/nope.md)\n\n"
        "## [1.0.0] - 2026-01-01\n\n"
        "frozen [also-bad](./doctrine/frozen-nope.md)\n"
    )
    assert _run(linkcheck, monkeypatch, [changelog]) == 1
    out = capsys.readouterr().out
    assert "BROKEN FILE" in out and "nope.md" in out
    assert "frozen-nope.md" not in out  # released section stays frozen-skipped


def test_missing_file_root_is_rejected(linkcheck, monkeypatch, tmp_path, capsys):
    assert _run(linkcheck, monkeypatch, [tmp_path / "does_not_exist.md"]) == 2
    assert "root not found" in capsys.readouterr().err
```

### A-tests-2 — functional test (suppression marker)

Append to `$jb/skills/cohere/executor/tests/test_linkcheck.py` (the `run_checks`
functional suite; runs under the venv, no docex deps):

```python
def test_linkcheck_ignore_marker_suppresses_a_line(tmp_path):
    """A LIVE line that quotes a dead reference as evidence is suppressed per
    line — skipped, but counted in stats['suppressed']."""
    write(tmp_path, {
        "doctrine/a.md":
            "Quoted as evidence: [x](./gone.md) <!-- linkcheck-ignore -->\n",
    })
    problems, declined, stats = check(tmp_path)
    assert problems == [], problems
    assert declined == [], declined
    assert stats["suppressed"] == 1


def test_line_without_marker_still_reports(tmp_path):
    write(tmp_path, {"doctrine/a.md": "[x](./gone.md)\n"})
    problems, declined, stats = check(tmp_path)
    only(problems, declined, "BROKEN FILE")
    assert stats["suppressed"] == 0
```

### A1 — repair the 16 dead CHANGELOG links (TARGETS ONLY, prose untouched)

Edit `$jb/CHANGELOG.md`. **Change only the target inside `](...)`; never the link
text or any prose.** All 16 are in frozen (released) sections, so linkcheck does
not enforce them — these are courtesy repairs for human readers.

**Step 1 — blanket prefix fix.** Replace **all** occurrences of the fragment
`](../doctrine/` with `](./doctrine/` (the file used to sit at `docex/`; `../`
escapes the repo root from its real location). First run
`grep -c '](\.\./doctrine/' CHANGELOG.md` — expect **11**. Apply the replace-all,
then confirm `grep -c '](\.\./doctrine/' CHANGELOG.md` is **0**.

**Step 2 — repoint the one `../doctrine` link whose file is gone.** Step 1 turned
line ~3591's target into `./doctrine/infrastructure/specifics/elastic_bootstrap.md`,
which does not exist (the doc was removed). Repoint it to the live home of the
two-phase-bootstrap content. Replace:

```
](./doctrine/infrastructure/specifics/elastic_bootstrap.md)
```

with:

```
](./doctrine/infrastructure/specifics/projinfra/projinfra.md)
```

(First open `$jb/doctrine/infrastructure/specifics/projinfra/projinfra.md` and
confirm it documents the elastic two-phase bootstrap / NS delegation. If that
content is more squarely in `elastic_route53_zone.md`, repoint to
`./doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md` instead.)

**Step 3 — `plans/` → `docex/plans/` (only resolved from `docex/`).** Two edits:

- Replace `](plans/modifications/048_elastic_walk_polish/)` with
  `](docex/plans/modifications/048_elastic_walk_polish/)`.
- Replace `](plans/modifications/047_smoke_walk_polish/)` with
  `](docex/plans/modifications/047_smoke_walk_polish/)`.

**Step 4 — the relocated triage brief.** Replace
`](./docex/plans/advances/007_small_edges/contract_spec_version_ungated.md)` with
`](./docex/plans/advances/008_housekeeping/references/contract_spec_version_ungated.md)`.

**Step 5 — LEAVE THESE TWO UNCHANGED** (documented decisions — do not edit):

- The link whose text/target is
  `007_small_edges/doctrine_excerpts_stale_entries.md` (near line 638). The file
  was *retired* and subsumed by `doctrine_excerpts_overhaul.md`; the link text
  names the retired file as part of a frozen claim, so repointing to a
  differently-named brief would misrepresent it. Frozen ⇒ unenforced. Leave it.
- The link whose target is `plans/campaigns/shape_overhaul_mod_list.md` (near line
  2663). The campaign file was deleted with no replacement — no live target
  exists. Frozen ⇒ unenforced. Leave it.

**Verify prose is untouched:** `git diff CHANGELOG.md` must show only changes
*inside* `](...)` parentheses — no changed words outside them.

### A4 — state the target-vs-claim rule once in `RELEASING.md`, cite from `upgrades/README.md`

**Edit `$jb/RELEASING.md`.** Insert a new section immediately **before** the
`## How Operators Consume a Release` heading (i.e. after the
`### The first cut bootstraps the scheme` subsection). Insert exactly:

```markdown
## Editing Frozen History: Targets vs. Claims

Released `CHANGELOG.md` sections and shipped `upgrades/` guides are **frozen
history** — the record of what was true at a past release, never revised. One
narrow, mechanical exception governs both: a link **target** may be repointed when
a later release moves or renames the file it addresses; a **claim** — any prose,
including the visible link text and any version it asserts — may not change. The
target is a pointer into living doctrine, and a dangling one preserves nothing
while making the record unusable; the words are the artifact and stand as written.
Where a target's file is gone with no honest replacement, or repointing would
misrepresent the claim (e.g. the link text names the file that moved), the dead
reference is left as record rather than falsified.

Stated here once so both [`upgrades/README.md`](./upgrades/README.md) and
[`CHANGELOG.md`](./CHANGELOG.md) can cite it.

```

**Edit `$jb/upgrades/README.md`.** In the "One Guide Per Release" section, find
the sentence ending the narrow-exception passage:

```
no version claim. A guide's words are the historical artifact; its links are
pointers into living doctrine, and a dangling one preserves nothing while making
the guide unusable.
```

Append one sentence after `the guide unusable.` (same paragraph):

```
 The general rule for frozen history — targets may be repointed, claims may not — is stated once in [`../RELEASING.md`](../RELEASING.md#editing-frozen-history-targets-vs-claims).
```

---

## HALF B — close the compile-test collection hole

Work in `$jb/docex/tests/`.

### B1 — relocate the 60 fast compile tests

1. `cd $jb/docex && git mv tests/integration/test_compile.py tests/unit/test_compile.py`
2. In the moved file `$jb/docex/tests/unit/test_compile.py`, **remove exactly two
   things** (leave everything else — all 60 fast tests and their helpers —
   intact):
   - the helper `def _tofu_validate(tf_dir: Path) -> subprocess.CompletedProcess:`
     and its whole body;
   - the test `test_mod062_ec2_traefik_hcl_is_tofu_valid`, including its three
     decorator lines (`@pytest.mark.integration`,
     `@pytest.mark.skipif(shutil.which("tofu") is None, ...)`,
     `@pytest.mark.parametrize("variant", [...])`).
   - Then remove the now-unused `import subprocess` line (it was used only by
     `_tofu_validate`; `shutil` stays — `_copy_fixture` uses it).
3. Create a NEW integration file `$jb/docex/tests/integration/test_compile_tofu.py`
   holding only the relocated integration test plus the helpers it needs:

```python
"""Integration test: the ec2_traefik project emits HCL that OpenTofu accepts.

Split out of the former tests/integration/test_compile.py (mod 139): that file's
other 60 tests were fast/hermetic and moved to tests/unit/test_compile.py. This is
the one genuine boundary crossing — it shells out to `tofu`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context

_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


def _copy_fixture(src: Path, tmp_path: Path) -> Path:
    """Copy a fixture into a fresh temp dir and return its root."""
    dest = tmp_path / "project"
    shutil.copytree(src, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    secrets = dest / "infra" / "secrets"
    if secrets.exists():
        shutil.rmtree(secrets)
    return dest


def _compile_elastic_with_reverse_proxy(tmp_path: Path, variant: str) -> Path:
    """Copy the elastic fixture, set `reverse_proxy: <variant>` on its
    infra.yml, compile, and return the project root."""
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    text = infra_yml.read_text()
    assert "reverse_proxy:" not in text
    text = text.replace(
        "foundation: elastic\n",
        f"foundation: elastic\nreverse_proxy: {variant}\n",
        1,
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    rc = run_compile(ctx)
    assert rc == 0
    return root


def _tofu_validate(tf_dir: Path) -> subprocess.CompletedProcess:
    """Run `tofu init -backend=false` + `tofu validate` in tf_dir.

    Returns the validate CompletedProcess (init failure is raised eagerly so
    a bad init doesn't masquerade as a validate pass)."""
    init = subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )
    assert init.returncode == 0, f"tofu init failed:\n{init.stdout}\n{init.stderr}"
    return subprocess.run(
        ["tofu", "validate", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("tofu") is None, reason="tofu not installed")
@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod062_ec2_traefik_hcl_is_tofu_valid(tmp_path: Path, variant: str):
    """Every tier of an ec2_traefik project emits HCL that OpenTofu accepts.
    This is the coverage the mod-044 substring tests lacked — it parses the
    emitted HCL rather than string-matching it. Regression for mod 062."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    out = root / "infra" / "output"
    for tier in ("project/production", "stage", "prod"):
        res = _tofu_validate(out / tier)
        assert res.returncode == 0, (
            f"[{variant}] tofu validate failed for {tier}:\n"
            f"{res.stdout}\n{res.stderr}"
        )
```

### B2 — the partition guard

Create `$jb/docex/tests/unit/test_collection_partition.py`:

```python
"""Guard: the two standard pytest invocations must PARTITION the suite.

A fast compile test once sat in tests/integration/ carrying no marker, so it was
collected by `pytest tests` yet invisible to BOTH `pytest tests/unit` (wrong dir)
and `pytest tests -m integration` (unmarked). Twelve such tests went red behind a
green report across two advances (mod 128). Relocating them fixes today's
instance; THIS guard is what stops the hole from silently reopening — it fails
wherever a future test lands in neither bucket (unmarked under tests/integration/)
or in both (integration-marked under tests/unit/).

Collection-only (`--collect-only`): executes no test and contends for no docker
state, so it is safe in the default suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_DOCEX_ROOT = Path(__file__).resolve().parents[2]


def _collected(args: list[str]) -> int:
    """Count collected test node ids for a pytest invocation (no execution).

    Every collected node id line contains '::'; no summary/warning/fixture line
    does, so counting '::' lines is robust across pytest's -q formatting.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args,
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=_DOCEX_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"collection failed for {args}:\n{proc.stdout}\n{proc.stderr}"
    )
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def test_unit_and_integration_buckets_partition_the_suite():
    unit = _collected(["tests/unit"])
    integration = _collected(["tests", "-m", "integration"])
    everything = _collected(["tests", "-m", ""])
    assert unit + integration == everything, (
        f"buckets do not partition the suite: unit({unit}) + "
        f"integration({integration}) = {unit + integration} != all({everything}). "
        f"A test is in neither standard invocation (unmarked under "
        f"tests/integration/?) or in both (integration-marked under tests/unit/?)."
    )
```

---

## RUN — tests (foreground, synchronous, in-turn; do NOT background)

From `$jb/docex`, with `.venv/bin/python`. Use the Bash `timeout` at `600000`.

1. **Unit / default suite** (one call, ~5–6 min):
   `.venv/bin/python -m pytest tests -q`
   Expect **all green**. Passed count = the post-138 baseline **1236 plus the new
   tests** added by this mod (the partition guard + the two file-root CLI tests) —
   report the exact number. Deselected must stay **21**.

2. **Integration suite ALONE** (~8 min):
   `.venv/bin/python -m pytest tests -q -m integration`
   Expect **21 passed** (unchanged). Run it by itself — nothing else concurrent.

3. **Executor functional suite** (linkcheck's `run_checks` seam):
   `cd $jb/skills/cohere/executor && $jb/docex/.venv/bin/python -m pytest tests -p no:cacheprovider`
   Expect all green (includes the two new suppression-marker tests).

4. **linkcheck at default scope** (from `$jb`):
   `$jb/docex/.venv/bin/python skills/cohere/executor/linkcheck.py`
   Expect **exit 0** ("No broken links…"). Confirm the summary's "Scanned … under"
   line now lists `CHANGELOG.md`, `README.md`, `RELEASING.md` among the roots, and
   that "frozen changelog lines … skipped" is non-zero. If it reports any problem
   in a LIVE (non-frozen) line of `RELEASING.md`/`README.md`/CHANGELOG `[Unreleased]`,
   fix that link's target (those are live docs, not frozen) and re-run.

If any total is unexpected (e.g. integration ≠ 21, or the partition guard fails),
stop and report — do not paper over it.

## Report back to the corporal

- final counts from runs 1 and 2 (passed / deselected for each);
- the partition guard's three collected numbers (unit, integration, all) and that
  `unit + integration == all`;
- confirmation runs 3 and 4 are green, and that CHANGELOG/README/RELEASING appear
  in linkcheck's scanned roots;
- `git status` (list of changed/added/renamed files);
- anything you had to deviate from in these steps.
