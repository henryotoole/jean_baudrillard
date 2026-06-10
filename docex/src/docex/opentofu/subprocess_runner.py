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

import json
import subprocess  # noqa: S404 - explicit chokepoint, see module docstring.
from pathlib import Path
from typing import Any


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
    targets: list[str] | None = None,
) -> int:
    """``tofu apply`` in ``workdir``. Returns exit code.

    ``auto_approve=False`` is the footgun-resistant default — the
    operator must confirm interactively. The Phase 4 ``release``
    flow passes ``auto_approve=True`` because it runs in a CI-shaped
    push-button context.

    If ``plan_file`` is given, applies the recorded plan (and
    ``auto_approve`` is irrelevant in that mode — applying a recorded
    plan never re-prompts).

    ``targets`` restricts the apply to the given resource addresses
    (each rendered as ``-target=<addr>``). Used by ``docex bootstrap``
    to apply just the Route53 zone in phase 1, before ACM DNS
    validation is reachable.
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "apply", "-input=false"]
    if plan_file is not None:
        cmd.append(str(plan_file))
    else:
        if auto_approve:
            cmd.append("-auto-approve")
        for addr in (targets or []):
            cmd.append(f"-target={addr}")
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode


def tofu_destroy(
    workdir: Path,
    *,
    auto_approve: bool = True,
    targets: list[str] | None = None,
) -> int:
    """``tofu destroy`` in ``workdir``. Returns exit code.

    Mirrors :func:`tofu_apply` for the teardown direction. ``docex
    envinfra down`` (elastic stage/prod env-tier) and ``docex projinfra
    down production`` (elastic project-tier) both run in a push-button
    context, so ``auto_approve`` defaults to ``True`` here (the inverse
    of ``tofu_apply``'s footgun-resistant default — a destroy is always
    deliberately invoked by the operator, never as a side effect).

    ``targets`` restricts the destroy to the given resource addresses
    (each rendered as ``-target=<addr>``).
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "destroy", "-input=false"]
    if auto_approve:
        cmd.append("-auto-approve")
    for addr in (targets or []):
        cmd.append(f"-target={addr}")
    try:
        res = subprocess.run(cmd, check=False)  # noqa: S603
    except FileNotFoundError:
        return 127
    return res.returncode


def tofu_state_list(workdir: Path) -> list[str]:
    """``tofu state list`` in ``workdir``. Returns resource addresses.

    Empty list both on "no state yet" and on subprocess failure — the
    caller treats either as "phase 1 needed" anyway. Used by
    ``docex bootstrap`` to determine which phase of the project-tier
    apply to run (zone-only vs. full).
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "state", "list"]
    try:
        res = subprocess.run(  # noqa: S603
            cmd, check=False, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return []
    if res.returncode != 0:
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def tofu_output(workdir: Path, name: str) -> Any:
    """``tofu output -json <name>`` in ``workdir``. Returns parsed JSON.

    Used by ``docex bootstrap`` to read the project zone's NS records
    after phase 1, so it can print them for NS delegation. Returns
    ``None`` if the output doesn't exist (e.g. the zone hasn't been
    applied yet) or the subprocess fails — the caller is expected to
    treat ``None`` as "not yet available".
    """
    cmd: list[str] = ["tofu", f"-chdir={workdir}", "output", "-json", name]
    try:
        res = subprocess.run(  # noqa: S603
            cmd, check=False, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
    if res.returncode != 0:
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return None
