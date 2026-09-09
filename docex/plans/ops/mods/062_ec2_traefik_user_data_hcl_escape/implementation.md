# Mod 062 — Implementation steps

Fix the invalid HCL emitted for `reverse_proxy: ec2_traefik_{eip,pip}` and add
the two regression tests that would have caught it. See `overview.md` for the
root cause. This document is self-contained; you do not need prior context.

Background you need:
- The bug: the EC2-traefik `user_data` shell script is injected into an HCL
  heredoc in `src/docex/emit/templates/project.tf.j2`
  (`user_data = <<-USER_DATA\n{{ traefik_user_data }}\n  USER_DATA`). HCL
  heredocs interpolate `${…}` and `%{…}`; the script's bash `${VAR}`
  expansions collide, producing `Error: Extra characters after interpolation
  expression` at `tofu validate`.
- The rendered script is pure bash — no `${…}` in it is an intended HCL
  reference — so escaping every `${`→`$${` and `%{`→`%%{` is correct and
  complete. OpenTofu un-escapes them back when evaluating the heredoc.

## Step 1 — Apply the fix

File: `src/docex/emit/hcl.py`, in `emit_hcl_project(...)`.

Find the block that renders the user_data (inside `if rp in ("ec2_traefik_eip",
"ec2_traefik_pip"):`), which currently ends:

```python
        ud_tpl = env.get_template("ec2_traefik_user_data.sh.j2")
        traefik_user_data = ud_tpl.render(
            project=project,
            project_subdomain=project_subdomain,
            apex_domain=apex_domain,
            reverse_proxy=rp,
            traefik_acme_email=acme_email,
        )
```

Insert immediately after that `.render(...)` assignment (still inside the
`if`):

```python
        # WHY: the user_data is injected into an HCL heredoc in
        # project.tf.j2, and HCL heredocs interpolate ${...}/%{...}. The
        # rendered script is pure bash — every ${VAR} is a shell expansion,
        # none are HCL refs — so escape both interpolation triggers. OpenTofu
        # un-escapes $${ -> ${ and %%{ -> %{ when evaluating the heredoc, so
        # the instance receives the intended script. Bare $(...) / $VAR are
        # untouched (only ${ and %{ trigger HCL interpolation). NOTE: do NOT
        # use the $->$$ doubling from _hcl_value here — that is for quoted
        # strings whose only $ usage is ${...}; this script has bare $(...)
        # that must survive un-doubled.
        traefik_user_data = traefik_user_data.replace(
            "${", "$${"
        ).replace("%{", "%%{")
```

Do not change `project.tf.j2` or the `.sh.j2` template.

## Step 2 — Unit regression test (default suite)

File: `tests/integration/test_compile.py`. These tests are NOT marked
`integration` and run in the default suite. Add near the other `test_mod044_*`
tests. Reuse the existing helper `_compile_elastic_with_reverse_proxy`.

The tokens `${PROJECT}`, `${TRAEFIK_VERSION}`, `${VOLUME_ID}`,
`${DEVICE_NAME}` originate only in the user_data — the HCL's own
interpolations reference `data.`/`aws_`/`path.` identifiers, never those
names — so asserting on the bare vs. escaped forms across the whole file is
safe and needs no heredoc extraction.

```python
def test_mod062_traefik_user_data_hcl_escaped_eip(tmp_path: Path):
    """The EC2-traefik user_data is HCL-escaped before entering the heredoc:
    every bash ${VAR} appears as $${VAR} so OpenTofu doesn't parse it as an
    interpolation. Regression for mod 062 (invalid HCL on the ec2_traefik
    path)."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Escaped forms present.
    assert "$${PROJECT}" in tf
    assert "$${VOLUME_ID//-/}" in tf
    assert "$${TRAEFIK_VERSION}" in tf
    # No bare (unescaped) bash expansions survive — these token names come
    # only from user_data, never from the HCL's own interpolations.
    for bare in ("${PROJECT}", "${VOLUME_ID}", "${TRAEFIK_VERSION}",
                 "${DEVICE_NAME}", "${REGION}"):
        assert bare not in tf, f"unescaped {bare} would break HCL parsing"
    # Bash command substitution stays un-doubled (only ${/%{ are escaped).
    assert "$(curl -sf http://169.254.169.254" in tf


def test_mod062_traefik_user_data_hcl_escaped_pip(tmp_path: Path):
    """Same escaping guarantee on the pip variant, whose user_data carries
    the additional boot-time DNS-update block."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_pip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert "$${PROJECT}" in tf
    for bare in ("${PROJECT}", "${VOLUME_ID}", "${TRAEFIK_VERSION}"):
        assert bare not in tf
```

## Step 3 — `tofu validate` regression test (integration-marked)

This is the test that structurally would have caught the bug: it parses the
emitted HCL with real OpenTofu rather than string-matching. Mark it
`integration` (real external-tool boundary), and skip cleanly when `tofu` is
not installed.

Add to `tests/integration/test_compile.py`. Add `import shutil` and
`import subprocess` at the top if not already present (`shutil` is; add
`subprocess`).

```python
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

Notes for the executor:
- The integration conftest (`tests/integration/conftest.py`) auto-skips
  `integration`-marked items when the docker daemon is unreachable. That is
  acceptable here — on the dev/smoke machine docker is present. The
  `skipif(tofu missing)` guard covers the tofu dependency independently.
- Do not add a project-tier `stage`/`prod` split confusion: the three tiers to
  validate are `project/production`, `stage`, and `prod` (there is no
  `project/development` HCL on elastic — that side is compose).

## Step 4 — Run the tests

```bash
cd ~/.claude/jean_baudrillard/docex

# Default (fast) suite — must stay green, includes the new unit tests.
PYTHONPATH=src python3 -m pytest tests/unit tests/integration/test_compile.py -q

# The new tofu-validate integration tests explicitly.
PYTHONPATH=src python3 -m pytest tests/integration/test_compile.py -q \
    -m integration -k mod062
```

Expected:
- Default suite: all pass (the previous count was 625; the two new unit tests
  bring it to 627).
- `-m integration -k mod062`: 2 passed (eip + pip) if `tofu` is on PATH;
  otherwise skipped.

## Step 5 — Alignment check (do not skip)

Per `docex_process.md` § Additional Artifacts, confirm the five layers agree:
- `doctrine/.../ec2_traefik.md` — unchanged (behavior is unchanged); no edit.
- `docex/plans/core/*.md` — no design-doc change required (the fix is an emit
  mechanics detail; `compiler.md` output layout is unchanged — still one
  `main.tf` per tier). No edit.
- `tables/` — untouched.
- `src/docex/emit/hcl.py` — the fix (Step 1).
- `tests/` — the three tests (Steps 2–3).

Do NOT update core planning docs or the changelog in this step — the design
context handles docs/changelog after reviewing your work (mod process steps
7–8).

## Definition of done

1. `hcl.py` escape applied (Step 1).
2. Two unit tests + one parametrized integration test added (Steps 2–3).
3. Default suite green; `-k mod062 -m integration` green (or skipped w/o tofu).
4. No changes outside `src/docex/emit/hcl.py` and
   `tests/integration/test_compile.py`.
