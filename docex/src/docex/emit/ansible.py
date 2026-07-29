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

    # WHY the compiler's carrier flag rather than a `schema_owned_by == s.name`
    # scan (Mod 096): `schema_owned_by` names a CODEBASE (`api`) while
    # `CompiledService.name` is the two-segment compiled identity (`api-web`),
    # so the comparison could only ever be false — the playbook would emit zero
    # migrate tasks and still report success. `schema_owned_by_db` is set on
    # exactly one compiled service per schema-owning codebase, so this yields
    # one migrate task per codebase by construction.
    core_with_schema = sorted(
        (s for s in compiled.services.values()
         if s.is_core and s.schema_owned_by_db),
        key=lambda s: s.name,
    )

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
