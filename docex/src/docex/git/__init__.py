"""``GitClient`` package.

Phase 3 introduces a ``GitClient`` Protocol mirroring the Phase 2
``DockerClient`` shape: a thin abstraction over every git operation
``check`` and ``merge`` need, with a single subprocess-backed
implementation. Unit tests use a recording fake; integration tests
use the real one.

The Protocol lives in :mod:`docex.git.client`; the runtime
implementation is :class:`docex.git.subprocess_client.SubprocessGitClient`.
"""

from __future__ import annotations

from docex.git.client import GitClient
from docex.git.subprocess_client import SubprocessGitClient

__all__ = ["GitClient", "SubprocessGitClient"]
