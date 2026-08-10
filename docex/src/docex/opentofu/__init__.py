"""Thin wrappers around the ``tofu`` CLI.

Five operations — init, validate, plan, apply, destroy — following the
ansible-runner pattern: one callable per operation, no Protocol ceremony.
``tofu_destroy`` arrived after the other four (elastic project-tier teardown
and elastic ``envinfra down`` for stage/prod). ``__all__`` below is the
authority on the set. The dispatcher and pipeline modules import these
functions directly; tests substitute a recorder.

The runtime implementations live in :mod:`docex.opentofu.subprocess_runner`;
this module re-exports them.
"""

from __future__ import annotations

from docex.opentofu.subprocess_runner import (
    tofu_apply,
    tofu_destroy,
    tofu_init,
    tofu_plan,
    tofu_validate,
)

__all__ = ["tofu_apply", "tofu_destroy", "tofu_init", "tofu_plan", "tofu_validate"]
