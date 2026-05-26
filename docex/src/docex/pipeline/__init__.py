"""Phase 3 ``pipeline`` commands.

Mirrors :mod:`docex.orchestrate` (Phase 2's local-stack commands). The
pipeline package houses commands that act on the *release* timeline
rather than a local dev/test stack: ``check``, ``merge``,
``containerize``, ``release``, ``stagetest``.

Each command exposes a single ``run_<cmd>(ctx, ...)`` entry point.
"""
