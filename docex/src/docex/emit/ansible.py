"""Emit playbook + inventory + ansible.cfg for fixed-foundation stage/prod."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from docex.cicl.compile import CompiledEnv


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def emit_ansible(compiled: CompiledEnv, out_dir: Path) -> None:
    """Write playbook.yml, inventory.yml, ansible.cfg into ``out_dir``."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    core_with_schema = sorted(
        [s for s in compiled.services.values() if s.is_core and any(
            b.schema_owned_by == s.name
            for b in compiled.services.values()
            if not b.is_core
        )],
        key=lambda s: s.name,
    )

    playbook_tpl = env.get_template("playbook.yml.j2")
    (out_dir / "playbook.yml").write_text(playbook_tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        core_services_with_schema=core_with_schema,
    ))

    inv_tpl = env.get_template("inventory.yml.j2")
    (out_dir / "inventory.yml").write_text(inv_tpl.render(
        project=compiled.project,
        env=compiled.env,
        subdomain=compiled.subdomain,
    ))

    cfg_tpl = env.get_template("ansible.cfg.j2")
    (out_dir / "ansible.cfg").write_text(cfg_tpl.render())
