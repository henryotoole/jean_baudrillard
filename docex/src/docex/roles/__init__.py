"""`docex roles` / `docex role <name>` — the role/parts reference.

Magic refs (`${backing_services.<svc>.<part>}`) pull from the *parts* each
role's engine exposes via its transfer-table `provides:` block. Those parts
live in the transfer tables, not the doctrine prose — so these commands
surface them on demand:

- ``list_roles``    — every known role with its description.
- ``describe_role`` — one role: its engines, the provided parts (the
                      magic-ref targets) per foundation, required env vars,
                      and role-specific fields.

Both render either human-readable text or, with ``fmt="llm"``, JSON for
tooling and agents writing ``infra.yml``.
"""

from __future__ import annotations

import json
import re

from rich.console import Console

from docex.cicl.transfer import EngineEntry, TransferTables
from docex.errors import TransferTableError


# A part is a "secret" if any of its per-foundation templates carries a
# $[VAR] runtime ref — those are delivered via .env / SSM, never inlined.
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


def _is_secret_part(per_foundation: dict[str, str]) -> bool:
    return any(_RUNTIME_REF_RE.search(t or "") for t in per_foundation.values())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def list_roles(tables: TransferTables, *, fmt: str = "text") -> int:
    """List every known role with its description. Returns exit code."""
    names = tables.roles()

    if fmt == "llm":
        payload = {
            "roles": [
                {
                    "name": r,
                    "description": tables.description(r),
                    "engines": sorted(tables.role(r)),
                }
                for r in names
            ]
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    console = Console()
    if not names:
        console.print("No roles defined.")
        return 0
    width = max(len(r) for r in names)
    console.print(f"[bold]Available roles ({len(names)}):[/bold]\n")
    for r in names:
        desc = tables.description(r) or "(no description)"
        console.print(f"  [cyan]{r.ljust(width)}[/cyan]  {desc}")
    console.print(
        "\nRun [bold]docex role <name>[/bold] for engines and provided parts."
    )
    return 0


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def _engine_payload(entry: EngineEntry) -> dict:
    parts: dict[str, dict] = {}
    for part, per_found in (entry.provides or {}).items():
        if not isinstance(per_found, dict):
            continue
        parts[part] = {
            "foundations": sorted(per_found.keys()),
            "secret": _is_secret_part(per_found),
            "templates": dict(per_found),
        }
    return {
        "name": entry.engine,
        "foundation": entry.foundation,
        "default_port": entry.default_port,
        "parts": parts,
        "env": dict(entry.env or {}),
        "fields": sorted((entry.fields or {}).keys()),
    }


def describe_role(tables: TransferTables, role: str, *, fmt: str = "text") -> int:
    """Describe one role's engines, parts, env vars, and fields.

    Returns exit code: 1 (with a list of known roles) if ``role`` is unknown.
    """
    try:
        engines = tables.role(role)
    except TransferTableError:
        Console(stderr=True).print(
            f"[red]error:[/red] unknown role {role!r}. "
            f"Known roles: {', '.join(tables.roles())}"
        )
        return 1

    if fmt == "llm":
        payload = {
            "role": role,
            "description": tables.description(role),
            "engines": [_engine_payload(engines[e]) for e in sorted(engines)],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    console = Console()
    desc = tables.description(role)
    console.print(f"[bold]{role}[/bold]" + (f" — {desc}" if desc else "") + "\n")

    for ename in sorted(engines):
        entry = engines[ename]
        meta = f"foundation: {entry.foundation}"
        if entry.default_port is not None:
            meta += f", default_port: {entry.default_port}"
        console.print(f"  [bold]engine:[/bold] {ename}  ({meta})")

        provides = entry.provides or {}
        if provides:
            console.print("    provided parts (magic-ref targets):")
            pwidth = max(len(p) for p in provides)
            for part in sorted(provides):
                per_found = provides[part]
                if not isinstance(per_found, dict):
                    continue
                founds = ", ".join(sorted(per_found.keys()))
                secret = "  [yellow](secret)[/yellow]" if _is_secret_part(per_found) else ""
                console.print(f"      [cyan]{part.ljust(pwidth)}[/cyan]  {founds}{secret}")
        else:
            console.print("    provided parts: (none)")

        env = entry.env or {}
        if env:
            console.print("    required env (infra/secrets/<env>.env):")
            ewidth = max(len(k) for k in env)
            for k in sorted(env):
                console.print(f"      {k.ljust(ewidth)}  {env[k]}")

        fields = entry.fields or {}
        if fields:
            console.print(f"    role-specific fields: {', '.join(sorted(fields))}")
        console.print("")

    return 0


__all__ = ["list_roles", "describe_role"]
