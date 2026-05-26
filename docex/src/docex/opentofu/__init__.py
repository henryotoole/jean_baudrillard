"""Thin wrappers around the ``tofu`` CLI.

Phase 4 needs four OpenTofu operations — init, validate, plan, apply —
so we follow the Phase 3 ansible-runner pattern: one callable per
operation, no Protocol ceremony. The dispatcher and pipeline modules
import these functions directly; tests substitute a recorder.

The runtime implementations live in :mod:`docex.opentofu.subprocess_runner`;
this module re-exports them.
"""

from __future__ import annotations

from docex.opentofu.subprocess_runner import (
    tofu_apply,
    tofu_init,
    tofu_plan,
    tofu_validate,
)

__all__ = ["tofu_apply", "tofu_init", "tofu_plan", "tofu_validate"]
