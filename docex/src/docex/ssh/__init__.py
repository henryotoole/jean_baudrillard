"""``SSHClient`` package.

Mirrors the ``GitClient`` / ``DockerClient`` shape: a thin abstraction
over the one SSH operation docex needs (run a command on a remote host
via a deploy key), with a single subprocess-backed implementation.
Unit tests substitute a scriptable fake.

The Protocol lives in :mod:`docex.ssh.client`; the runtime
implementation is :class:`docex.ssh.subprocess_client.SubprocessSSHClient`.
"""

from __future__ import annotations

from docex.ssh.client import SSHClient
from docex.ssh.subprocess_client import SubprocessSSHClient

__all__ = ["SSHClient", "SubprocessSSHClient"]
