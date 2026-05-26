"""Subprocess-backed ``run_playbook``.

This is the *only* module in docex permitted to ``import subprocess``
for ansible. Same discipline as ``SubprocessGitClient`` /
``SubprocessDockerClient``: a single chokepoint so unit tests can stub
ansible without touching the real binary.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
from pathlib import Path
from typing import Any


def run_playbook(
    playbook: Path,
    inventory: Path,
    *,
    extra_vars: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    config: Path | None = None,
    private_key: Path | None = None,
) -> int:
    """Run ``ansible-playbook`` and return its exit code.

    Arguments mirror the ansible CLI flags one-for-one:
      - ``playbook`` is the playbook YAML path (passed positionally).
      - ``inventory`` becomes ``-i <inventory>``.
      - ``extra_vars`` becomes one ``--extra-vars 'k=v'`` per item.
      - ``tags`` becomes ``--tags <comma-sep>`` so callers can run just
        a subset of tasks (used by ``migrate stage/prod``).
      - ``config`` is exported as ``ANSIBLE_CONFIG`` for the child.
      - ``private_key`` becomes ``--private-key <path>`` so ansible
        SSHes to the env's host using the project-local deploy key.

    Stdout / stderr are inherited so the operator sees ansible's task
    output verbatim.
    """
    cmd: list[str] = ["ansible-playbook", "-i", str(inventory)]
    if tags:
        cmd.extend(["--tags", ",".join(tags)])
    if private_key is not None:
        cmd.extend(["--private-key", str(private_key)])
    for key, val in (extra_vars or {}).items():
        cmd.extend(["--extra-vars", f"{key}={val}"])
    cmd.append(str(playbook))

    env = dict(os.environ)
    if config is not None:
        env["ANSIBLE_CONFIG"] = str(config)
    try:
        res = subprocess.run(cmd, env=env, check=False)  # noqa: S603
    except FileNotFoundError:
        # ansible not installed at all.
        return 127
    return res.returncode
