"""Guard: the docex image must run Python unbuffered.

Mod 146 (F1). PYTHONUNBUFFERED=1 is what makes docex's narration
interleave with subprocess output in true chronological order when a run
is redirected to a file. If this line is ever dropped from the Dockerfile,
logs silently scramble again — so assert its presence loudly here.
"""

from __future__ import annotations

from pathlib import Path


def test_dockerfile_sets_pythonunbuffered():
    # tests/unit/ -> tests/ -> project root
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text()
    assert "ENV PYTHONUNBUFFERED=1" in text, (
        "Dockerfile must set ENV PYTHONUNBUFFERED=1 so docex output is "
        "unbuffered (mod 146). Without it, redirected logs scramble."
    )
