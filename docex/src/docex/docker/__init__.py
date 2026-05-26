"""Docker integration package.

Every docker / docker-compose invocation in docex goes through the
``DockerClient`` protocol defined here. Production code wires up the
``SubprocessDockerClient`` implementation; tests substitute a fake.

This is the only module in docex permitted to ``import subprocess``.
The orchestration layer (``docex.orchestrate.*``) must always speak
through the protocol so that unit tests can mock cheaply.
"""

from __future__ import annotations

from docex.docker.client import DockerClient
from docex.docker.subprocess_client import SubprocessDockerClient

__all__ = ["DockerClient", "SubprocessDockerClient"]
