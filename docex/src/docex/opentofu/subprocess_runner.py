"""Subprocess-backed OpenTofu runner.

This is the *only* module in docex permitted to ``import subprocess``
for ``tofu``. Same discipline as ``SubprocessDockerClient`` /
``SubprocessGitClient`` / ``run_playbook``: a single chokepoint so
unit tests can stub OpenTofu without spawning the real binary.

The runner expects AWS credentials to be present in the environment
(the docex container inherits ``~/.aws/credentials`` via the bin/docex
shim's mount); the runner itself does not manage credential storage.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - explicit chokepoint, see module docstring.
from pathlib import Path


def tofu_init(workdir: Path, *, backend: bool = True) -> int:
    """``tofu init`` in ``workdir``. Returns exit code.

    ``backend=False`` runs ``-backend=false``, useful for offline
    ``tofu validate`` against the emitted HCL in tests (no S3 backend
    available, no AWS creds needed).
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "init"]
    if not backend:
        cmd.append("-backend=false")
    cmd.append("-input=false")
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode


def tofu_validate(workdir: Path) -> int:
    """``tofu validate`` in ``workdir``. Returns exit code.

    ``tofu init`` (at minimum ``-backend=false``) must have been run
    against ``workdir`` first — ``validate`` needs the provider
    plugins installed.
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "validate"]
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode


def tofu_plan(workdir: Path, *, out_path: Path | None = None) -> int:
    """``tofu plan`` in ``workdir``. Returns exit code.

    If ``out_path`` is given, writes the binary plan to that file via
    ``-out``.
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "plan", "-input=false"]
    if out_path is not None:
        cmd.append(f"-out={out_path}")
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode


def tofu_apply(
    workdir: Path,
    *,
    plan_file: Path | None = None,
    auto_approve: bool = False,
) -> int:
    """``tofu apply`` in ``workdir``. Returns exit code.

    ``auto_approve=False`` is the footgun-resistant default — the
    operator must confirm interactively. The Phase 4 ``release``
    flow passes ``auto_approve=True`` because it runs in a CI-shaped
    push-button context.

    If ``plan_file`` is given, applies the recorded plan (and
    ``auto_approve`` is irrelevant in that mode — applying a recorded
    plan never re-prompts).
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "apply", "-input=false"]
    if plan_file is not None:
        cmd.append(str(plan_file))
    else:
        if auto_approve:
            cmd.append("-auto-approve")
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode
