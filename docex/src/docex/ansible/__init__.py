"""Thin wrapper around ``ansible-playbook``.

Phase 3 only needs one operation against ansible — run a playbook —
so we skip the Protocol ceremony used for ``DockerClient`` /
``GitClient`` and expose a single callable. The dispatcher hands
this function to commands that need it; tests inject a
``fake_run_playbook`` recorder.

The runtime implementation lives in :mod:`docex.ansible.subprocess_runner`;
this module re-exports it under :func:`run_playbook`.
"""

from __future__ import annotations

from docex.ansible.subprocess_runner import run_playbook

__all__ = ["run_playbook"]
