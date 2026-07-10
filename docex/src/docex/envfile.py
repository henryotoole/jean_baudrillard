"""Flat KEY=value env-file read/write — the standard form used by every
configurable-value store (secrets/tte/config) and the aggregate. See
config_and_secrets.md § Standard Form. Raw-literal values: split on the first
'=', no quote/escape/interpolation/trim processing."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_env_text(text: str, *, source: str = "<text>") -> dict[str, str]:
    """Parse standard-form env-file text into an ordered dict. Full-line `#`
    comments and blank lines skipped. Split on first '='. A malformed key
    raises ValueError (fail loud). ``source`` names the origin in errors —
    used when parsing a string captured over SSH (no file path to cite)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{source}: malformed line (no '='): {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.match(key):
            raise ValueError(
                f"{source}: invalid key {key!r} (must match [A-Z][A-Z0-9_]*)"
            )
        out[key] = value  # raw literal — no strip, no unquote
    return out


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a standard-form env file into an ordered dict. Missing file → {}.
    Full-line `#` comments and blank lines skipped. Split on first '='.
    A line whose key is malformed raises ValueError (fail loud, not silent)."""
    if not path.is_file():
        return {}
    return parse_env_text(path.read_text(), source=str(path))


def write_env_file(
    path: Path, values: Mapping[str, str], *, header: list[str] | None = None
) -> None:
    """Write a standard-form env file, keys sorted for determinism. `header`
    lines are written as `#` comments at the top. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {h}" for h in (header or [])]
    if header:
        lines.append("")
    for k in sorted(values):
        lines.append(f"{k}={values[k]}")
    path.write_text("\n".join(lines) + "\n")
