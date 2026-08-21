"""Guard: the two standard pytest invocations must PARTITION the suite.

A fast compile test once sat in tests/integration/ carrying no marker, so it was
collected by `pytest tests` yet invisible to BOTH `pytest tests/unit` (wrong dir)
and `pytest tests -m integration` (unmarked). Twelve such tests went red behind a
green report across two advances (mod 128). Relocating them fixes today's
instance; THIS guard is what stops the hole from silently reopening — it fails
wherever a future test lands in neither bucket (unmarked under tests/integration/)
or in both (integration-marked under tests/unit/).

Collection-only (`--collect-only`): executes no test and contends for no docker
state, so it is safe in the default suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_DOCEX_ROOT = Path(__file__).resolve().parents[2]


def _collected(args: list[str]) -> int:
    """Count collected test node ids for a pytest invocation (no execution).

    Every collected node id line contains '::'; no summary/warning/fixture line
    does, so counting '::' lines is robust across pytest's -q formatting.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args,
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=_DOCEX_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"collection failed for {args}:\n{proc.stdout}\n{proc.stderr}"
    )
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def test_unit_and_integration_buckets_partition_the_suite():
    unit = _collected(["tests/unit"])
    integration = _collected(["tests", "-m", "integration"])
    everything = _collected(["tests", "-m", ""])
    assert unit + integration == everything, (
        f"buckets do not partition the suite: unit({unit}) + "
        f"integration({integration}) = {unit + integration} != all({everything}). "
        f"A test is in neither standard invocation (unmarked under "
        f"tests/integration/?) or in both (integration-marked under tests/unit/?)."
    )
