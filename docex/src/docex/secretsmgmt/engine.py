"""Value-blind configurable-value tooling — the engine behind
``docex secrets`` (and, in Mod 084, ``docex config``).

Category-parametrized by a ``CategoryPolicy`` so the same four ops
(scaffold / status / set / copy) serve both secrets and config with the
permission asymmetry from config_and_secrets.md § Tooling:

- secrets are value-blind: ``status`` prints SET/UNSET only, ``set`` refuses
  a positional value (tty prompt or ``--from-file`` only), and there is no
  ``get``.
- config (Mod 084) inverts those: ``status``/``get`` show values and ``set``
  accepts a positional value.

Nothing here ever prints a secret value; the value only leaves the file at
materialization (aggregation, Mods 080-082).
"""

from __future__ import annotations

import getpass
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from docex.cicl.categories import (
    ManifestEntry,
    config_manifest,
    minted_policies,
    secret_manifest,
)
from docex.context import ProjectContext
from docex.emit.secrets import render_manifest_env
from docex.envfile import read_env_file, set_env_key


@dataclass(frozen=True)
class CategoryPolicy:
    name: str            # "secret" | "config"
    subdir: str          # "secrets" | "config"
    values_visible: bool  # status shows values (config) vs SET/UNSET (secret)
    set_positional_ok: bool  # `set` accepts a positional value (config only)


SECRET_POLICY = CategoryPolicy(
    "secret", "secrets", values_visible=False, set_positional_ok=False
)

# Config inverts the secret permissions: values are visible (status/get show
# them) and a positional `set` value is accepted. See config_and_secrets.md
# § Tooling.
CONFIG_POLICY = CategoryPolicy(
    "config", "config", values_visible=True, set_positional_ok=True
)


def _side(env: str) -> str:
    """The infrastructure side an env belongs to (config_and_secrets.md)."""
    return "development" if env in ("dev", "test") else "production"


def _file(ctx: ProjectContext, policy: CategoryPolicy, env: str) -> Path:
    return ctx.project_root / "infra" / policy.subdir / f"{env}.env"


def _manifest(ctx: ProjectContext, policy: CategoryPolicy) -> list[ManifestEntry]:
    """The required entries for this category — secret or config."""
    if policy.name == "secret":
        return secret_manifest(ctx.infra, ctx.transfer_tables)
    if policy.name == "config":
        return config_manifest(ctx.infra, ctx.transfer_tables)
    raise NotImplementedError(f"no manifest for category {policy.name!r}")


def scaffold(ctx: ProjectContext, policy: CategoryPolicy, env: str) -> int:
    """Reconcile ``infra/<subdir>/<env>.env`` against the required key set:
    add missing keys (empty), drop stale keys, preserve existing values.
    Idempotent — a second run makes no value changes."""
    manifest = _manifest(ctx, policy)
    required = {e.key for e in manifest}
    file = _file(ctx, policy, env)
    existing = read_env_file(file)

    new_values = {e.key: existing.get(e.key, "") for e in manifest}
    added = [e.key for e in manifest if e.key not in existing]
    removed = sorted(k for k in existing if k not in required)
    preserved = [e.key for e in manifest if e.key in existing]

    # policy.subdir is also the CLI command name ("secrets" / "config"); use it
    # (not policy.name, the singular noun) for command hints.
    prefix = [
        f"# Managed by `docex {policy.subdir} scaffold {env}`.",
        f"# Reconcile keys with scaffold; set values with `docex {policy.subdir}"
        f" set {env} <KEY>`.",
        "",
    ]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        render_manifest_env(
            manifest, ctx.infra,
            prefix_lines=prefix, values=new_values,
        )
    )

    print(
        f"scaffold {env}: {len(added)} added, {len(removed)} removed, "
        f"{len(preserved)} preserved"
    )
    if removed:
        print(f"  removed: {', '.join(removed)}")
    return 0


def status(
    ctx: ProjectContext, policy: CategoryPolicy, env: str, *, fmt: str = "text"
) -> int:
    """Redacted read: per key SET/UNSET, source, description. Never prints a
    secret value (no length/hash either) unless ``policy.values_visible``."""
    manifest = _manifest(ctx, policy)
    existing = read_env_file(_file(ctx, policy, env))

    rows = []
    for e in manifest:
        val = existing.get(e.key, "")
        rows.append((e.key, "SET" if val != "" else "UNSET", e.source, e.desc, val))

    if fmt == "json":
        out = []
        for key, state, source, desc, val in rows:
            item = {"key": key, "state": state, "source": source, "desc": desc}
            if policy.values_visible:
                item["value"] = val
            out.append(item)
        print(json.dumps(out, indent=2))
        return 0

    width = max((len(r[0]) for r in rows), default=0)
    for key, state, source, desc, val in rows:
        line = f"{key:<{width}}  {state:<5}  [{source}]  {desc}"
        # Only config exposes the value; secrets stay value-blind here.
        if policy.values_visible and val != "":
            line += f"  = {val}"
        print(line)
    return 0


def set_key(
    ctx: ProjectContext,
    policy: CategoryPolicy,
    env: str,
    key: str,
    *,
    value: str | None = None,
    from_file: str | None = None,
) -> int:
    """Write one key's value. For secrets the value channel is a no-echo tty
    prompt or ``--from-file`` only — a positional value is rejected so the
    value never transits the agent's context."""
    keys = {e.key for e in _manifest(ctx, policy)}
    if key not in keys:
        print(
            f"error: unknown {policy.name} key {key}; run "
            f"`docex {policy.subdir} scaffold {env}` or declare it in infra.yml",
            file=sys.stderr,
        )
        return 1

    if from_file is not None:
        raw = Path(from_file).read_text()
        # Strip a single trailing newline only; the rest is a raw literal.
        resolved = raw[:-1] if raw.endswith("\n") else raw
    elif value is not None:
        if not policy.set_positional_ok:
            print(
                f"error: {policy.name} values may not be passed as an "
                f"argument; use an interactive prompt or --from-file",
                file=sys.stderr,
            )
            return 1
        resolved = value
    else:
        if not sys.stdin.isatty():
            print(
                f"error: no interactive terminal to prompt for {key}; provide "
                f"the value with --from-file (non-interactive invocation)",
                file=sys.stderr,
            )
            return 1
        resolved = getpass.getpass(f"Value for {key}: ")

    set_env_key(_file(ctx, policy, env), key, resolved)
    # Redacted confirmation — never echo the value (even for config, keep it
    # off the terminal here; `status`/`get` are the read paths).
    print(f"set {key} in {env} ({policy.subdir})")
    return 0


def get_key(
    ctx: ProjectContext, policy: CategoryPolicy, env: str, key: str
) -> int:
    """Print one key's value. Config only — refuses when not
    ``policy.values_visible`` (secrets have no ``get``; a value never goes to
    stdout)."""
    if not policy.values_visible:
        print(
            f"error: `get` is not available for {policy.name} "
            f"(values never printed)",
            file=sys.stderr,
        )
        return 1
    val = read_env_file(_file(ctx, policy, env)).get(key)
    if val is None:
        print(f"error: {key} is not set in {env}", file=sys.stderr)
        return 1
    print(val)  # config is non-secret — printing is fine
    return 0


def copy_key(
    ctx: ProjectContext,
    policy: CategoryPolicy,
    src_env: str,
    tgt_env: str,
    key: str,
) -> int:
    """Value-blind env→env copy. Refuses a TTE (minted) key, errors on an
    unset source, warns on a cross-side copy, and overwrites the target."""
    if key in minted_policies(ctx.infra, ctx.transfer_tables):
        print(
            f"error: cannot copy a TTE key {key} (minted per env, write-once)",
            file=sys.stderr,
        )
        return 1

    src_val = read_env_file(_file(ctx, policy, src_env)).get(key)
    if not src_val:  # None (absent) or "" (declared, unset)
        print(f"error: {key} is unset in {src_env}", file=sys.stderr)
        return 1

    if _side(src_env) != _side(tgt_env):
        print(
            f"warning: cross-side copy — seeding {tgt_env} "
            f"({_side(tgt_env)}) from {src_env} ({_side(src_env)})",
            file=sys.stderr,
        )

    tgt_file = _file(ctx, policy, tgt_env)
    had = key in read_env_file(tgt_file)
    set_env_key(tgt_file, key, src_val)
    print(f"{'overwrote' if had else 'set'} {key} in {tgt_env} ({policy.subdir})")
    return 0
