"""Orchestrate package — the Phase 2 command implementations.

Each module exposes ``run_<command>(ctx, docker, **args) -> int`` and
is invoked by the dispatcher in ``docex.__main__``. The dispatcher
hands every command a ``DockerClient``; tests pass a recording fake.
"""
