"""Entrypoint for the `web` core service of the `api` codebase.

Takes the graph `root.build_app()` constructed and hands it to a runtime
host. The host (uvicorn) belongs here and not in an adapter
(internal_dependency_rules.md § Entrypoints, rule 2).
"""

from __future__ import annotations

import logging
import os

import uvicorn

from root import build_app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# WHY: the default must match infra.yml's `port: 8080` for this process
# type — nothing injects PORT, so the two are coupled by convention.
port = int(os.environ.get("PORT", "8080"))

uvicorn.run(build_app(), host="0.0.0.0", port=port, log_level="info")
