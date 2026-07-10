"""``SSHClient`` Protocol.

Declares the single SSH operation docex needs: run a command on a
remote host as a given user, authenticating with a private key.
Same discipline as ``GitClient`` / ``DockerClient`` — the method
returns an exit code and never raises on a non-zero remote command.
The pipeline layer interprets the code (including SSH's own ``255``
connection-failure code).

Only :mod:`docex.ssh.subprocess_client` is permitted to ``import
subprocess`` for ssh.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SSHClient(Protocol):
    """Abstraction over the ``ssh`` CLI."""

    def run(
        self,
        host: str,
        key_path: Path,
        command: str,
        *,
        user: str = "deploy",
    ) -> int:
        """Run ``command`` on ``host`` over SSH as ``user`` using the
        private key at ``key_path``. Returns the remote exit code;
        ``255`` is SSH's own connection-failure code (host unreachable /
        auth refused)."""
        ...

    def capture(
        self,
        host: str,
        key_path: Path,
        command: str,
        *,
        user: str = "deploy",
    ) -> tuple[int, str]:
        """Run ``command`` over SSH and return (exit_code, stdout). stderr
        inherits (so auth/host-key errors stay visible). Used to read a small
        remote file (the host TTE store) into docex. 255 = SSH connection
        failure."""
        ...
