"""describe — render a compiled stack as DAG or LLM-JSON.

``run_describe(ctx, env=..., fmt=...)`` is the entry point used by the
CLI dispatcher.
"""

from __future__ import annotations

from pathlib import Path

from docex.context import ProjectContext
from docex.errors import InfraFileError


def run_describe(ctx: ProjectContext, *, env: str, fmt: str) -> int:
    if ctx.infra is None:
        raise InfraFileError(
            f"{ctx.project_root}/infra/infra.yml: file missing — describe "
            "requires an infra.yml"
        )
    from docex.cicl.compile import compile_env

    compiled = compile_env(
        ctx.infra,
        ctx.transfer_tables,
        env=env,
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )

    if fmt == "dag":
        from docex.describe.dag import render_dag
        print(render_dag(compiled))
    elif fmt == "llm":
        from docex.describe.llm import render_llm
        print(render_llm(compiled))
    else:  # argparse already restricts this
        raise ValueError(f"unknown format {fmt!r}")
    return 0
