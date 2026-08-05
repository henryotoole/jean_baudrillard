"""Emit playbook + inventory + ansible.cfg for fixed-foundation stage/prod."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from docex.cicl.compile import CompiledEnv, group_by_codebase


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def emit_ansible(compiled: CompiledEnv, out_dir: Path) -> None:
    """Write playbook.yml, inventory.yml, ansible.cfg into ``out_dir``."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    # WHY the playbook migrates in the EXEC service (Mod 099): fixed
    # stage/prod migration is already a one-off `compose run --rm` container,
    # but it used to target an *app* service — so production migration read
    # that core service's `env:` overlay. That is the exact trap the exec
    # service exists to close, and leaving it open here would have left
    # justification #2 ("`migrate.sh` may depend only on codebase-scoped
    # env") true in dev/test and false in prod. Routing through the exec
    # service is why it is emitted in all four fixed envs and not just
    # dev/test.
    #
    # WHY grouped by codebase rather than filtered by service: migration is
    # per codebase. `schema_owned_by_db` is now true of every core service of
    # a schema-owning codebase (the Mod 096 "carrier" is gone), so a filter
    # over compiled services would emit one duplicate migrate task per process
    # type. Grouping first makes "one per codebase" structural.
    migrations = [
        {
            "codebase": codebase,
            "exec_service": f"{procs[0].codebase_global_name}-exec",
        }
        for codebase, procs in group_by_codebase(compiled).items()
        if any(p.schema_owned_by_db for p in procs)
    ]

    playbook_tpl = env.get_template("playbook.yml.j2")
    (out_dir / "playbook.yml").write_text(playbook_tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        # Explicit, project-scoped Compose project name — matches docex's
        # native env_compose_project (`<dns_label>-<env>`, mod 053). Without
        # it the playbook's compose invocations derive the unscoped `<env>`
        # from the deploy-dir basename and collide across projects (mod 090).
        compose_project_name=f"{compiled.project_dns_label}-{compiled.env}",
        migrations=migrations,
    ))

    inv_tpl = env.get_template("inventory.yml.j2")
    (out_dir / "inventory.yml").write_text(inv_tpl.render(
        project=compiled.project,
        env=compiled.env,
        subdomain=compiled.subdomain,
    ))

    cfg_tpl = env.get_template("ansible.cfg.j2")
    (out_dir / "ansible.cfg").write_text(cfg_tpl.render())
