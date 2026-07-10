"""Subprocess-backed implementation of ``SSHClient``.

Mirrors :mod:`docex.git.subprocess_client`. This is the *only*
module in docex permitted to ``import subprocess`` for ssh.

Stdout / stderr inherit from the parent process so the operator sees
ssh's own output (e.g. host-key acceptance, auth refusals) verbatim.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
from pathlib import Path


class SubprocessSSHClient:
    """Production ``SSHClient`` implementation."""

    def __init__(self, *, ssh_bin: str = "ssh") -> None:
        self._ssh = ssh_bin

    def run(
        self,
        host: str,
        key_path: Path,
        command: str,
        *,
        user: str = "deploy",
    ) -> int:
        # ``BatchMode=yes`` forbids interactive prompts (so a missing key
        # fails fast instead of hanging on a password prompt);
        # ``accept-new`` records an unseen host key without prompting but
        # still refuses a *changed* one; ``ConnectTimeout`` bounds the
        # probe. ssh surfaces the remote command's exit code, or 255 on
        # its own connection failure.
        #
        # F3 (mod 053): the docex shim mounts ~/.ssh read-only, so with a
        # real known_hosts file ssh prints "Failed to add the host to the
        # list of known_hosts" on every probe — harmless but alarming
        # noise. Point known_hosts at /dev/null so accept-new has a
        # throwaway, writable sink; this is a short-lived probe/deploy
        # connection, not a session where host-key persistence matters.
        args = [
            self._ssh,
            "-i", str(key_path),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            f"{user}@{host}",
            command,
        ]
        try:
            res = subprocess.run(args, check=False)  # noqa: S603
        except FileNotFoundError:
            # ssh not installed; fatal exit-code shape (mirrors git client).
            return 127
        return res.returncode

    def capture(
        self,
        host: str,
        key_path: Path,
        command: str,
        *,
        user: str = "deploy",
    ) -> tuple[int, str]:
        # Same connection flags as ``run`` (see that method for the -o
        # rationale). Unlike ``run``, stdout is captured so docex can read
        # a small remote file (the host TTE store); stderr still inherits so
        # auth / host-key failures stay visible to the operator.
        args = [
            self._ssh,
            "-i", str(key_path),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            f"{user}@{host}",
            command,
        ]
        try:
            res = subprocess.run(  # noqa: S603
                args, check=False, stdout=subprocess.PIPE, text=True,
            )
        except FileNotFoundError:
            return (127, "")
        return (res.returncode, res.stdout or "")
