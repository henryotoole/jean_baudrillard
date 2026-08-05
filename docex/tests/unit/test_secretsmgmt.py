"""Mod 083 — the value-blind `docex secrets` engine (`secretsmgmt/`).

The whole point of this tooling is that an LLM agent can *drive* secret
handling while being structurally unable to *see* a secret value. These
tests pin the security invariants: `status` never prints a value, `set`
refuses a positional value (tty prompt or `--from-file` only), and `copy`
moves a value env→env with no value channel at all (and refuses a TTE key).
See config_and_secrets.md § Tooling.
"""

from __future__ import annotations

import yaml

from docex.cicl.model import CICLDocument, ProjectManifest
from docex.cicl.transfer import load_transfer_tables
from docex.context import ProjectContext
from docex.secretsmgmt import (
    CONFIG_POLICY,
    SECRET_POLICY,
    copy_key,
    get_key,
    scaffold,
    set_key,
    status,
)

# postgres backing (POSTGRES_PASSWORD minted -> TTE; POSTGRES_USER fixed) plus
# a core service with one bespoke secret. secret_manifest therefore yields
# TELEMETRY_API_KEY (doctrine) + STRIPE_KEY (api); POSTGRES_* are absent.
_INFRA = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    secrets:
      STRIPE_KEY: "Stripe secret API key"
    config:
      PARTNER_URL: "Partner API base URL (per-env)"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        depends_on: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


def _ctx(tmp_path) -> ProjectContext:
    return ProjectContext(
        project_root=tmp_path,
        project=ProjectManifest(name="p", version="0.1.0", docex_version="0.1.0"),
        transfer_tables=load_transfer_tables(project_root=None),
        infra=CICLDocument.model_validate(yaml.safe_load(_INFRA)),
    )


def _secrets_file(tmp_path, env: str):
    return tmp_path / "infra" / "secrets" / f"{env}.env"


def _config_file(tmp_path, env: str):
    return tmp_path / "infra" / "config" / f"{env}.env"


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


def test_scaffold_adds_missing_keys_empty(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    assert scaffold(ctx, SECRET_POLICY, "dev") == 0
    from docex.envfile import read_env_file
    vals = read_env_file(_secrets_file(tmp_path, "dev"))
    assert vals == {"TELEMETRY_API_KEY": "", "STRIPE_KEY": ""}


def test_scaffold_preserves_values_and_removes_stale(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    file = _secrets_file(tmp_path, "dev")
    set_env_key(file, "STRIPE_KEY", "sk_live_123")
    set_env_key(file, "STALE_KEY", "leftover")

    assert scaffold(ctx, SECRET_POLICY, "dev") == 0
    vals = read_env_file(file)
    assert vals["STRIPE_KEY"] == "sk_live_123"  # preserved
    assert "STALE_KEY" not in vals  # removed
    assert vals["TELEMETRY_API_KEY"] == ""  # added empty
    out = capsys.readouterr().out
    assert "STALE_KEY" in out  # removal reported


def test_scaffold_is_idempotent(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    scaffold(ctx, SECRET_POLICY, "dev")
    from docex.envfile import set_env_key
    file = _secrets_file(tmp_path, "dev")
    set_env_key(file, "STRIPE_KEY", "sk_value")
    first = file.read_text()
    assert scaffold(ctx, SECRET_POLICY, "dev") == 0
    assert file.read_text() == first  # no value changes on a second run


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_set_unset_and_never_prints_value(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_secret_value")

    assert status(ctx, SECRET_POLICY, "dev", fmt="text") == 0
    out = capsys.readouterr().out
    assert "STRIPE_KEY" in out and "SET" in out
    assert "TELEMETRY_API_KEY" in out and "UNSET" in out
    # The value must never appear.
    assert "sk_secret_value" not in out
    # Source + description surface.
    assert "[api]" in out
    assert "Stripe secret API key" in out


def test_status_json_omits_value_under_secret_policy(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_secret_value")

    assert status(ctx, SECRET_POLICY, "dev", fmt="json") == 0
    out = capsys.readouterr().out
    import json
    data = json.loads(out)
    stripe = next(d for d in data if d["key"] == "STRIPE_KEY")
    assert stripe["state"] == "SET"
    assert stripe["source"] == "api"
    assert "value" not in stripe  # secret policy: values_visible=False
    assert "sk_secret_value" not in out


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


def test_set_from_file_strips_single_trailing_newline(tmp_path):
    ctx = _ctx(tmp_path)
    valfile = tmp_path / "value.txt"
    valfile.write_text("sk_from_file\n")
    assert set_key(
        ctx, SECRET_POLICY, "dev", "STRIPE_KEY", from_file=str(valfile)
    ) == 0
    from docex.envfile import read_env_file
    assert read_env_file(_secrets_file(tmp_path, "dev"))["STRIPE_KEY"] == "sk_from_file"


def test_set_rejects_positional_value_for_secret(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = set_key(ctx, SECRET_POLICY, "dev", "STRIPE_KEY", value="sk_positional")
    assert rc == 1
    err = capsys.readouterr().err
    assert "may not be passed as an argument" in err
    # Nothing was written.
    from docex.envfile import read_env_file
    assert read_env_file(_secrets_file(tmp_path, "dev")).get("STRIPE_KEY") in (None, "")


def test_set_non_tty_interactive_errors_toward_from_file(tmp_path, capsys, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = set_key(ctx, SECRET_POLICY, "dev", "STRIPE_KEY")
    assert rc == 1
    assert "--from-file" in capsys.readouterr().err


def test_set_tty_prompt_reads_value_no_echo(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk_prompted")
    assert set_key(ctx, SECRET_POLICY, "dev", "STRIPE_KEY") == 0
    from docex.envfile import read_env_file
    assert read_env_file(_secrets_file(tmp_path, "dev"))["STRIPE_KEY"] == "sk_prompted"


def test_set_undeclared_key_errors(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = set_key(ctx, SECRET_POLICY, "dev", "NOT_A_KEY", from_file=str(tmp_path / "x"))
    assert rc == 1
    assert "unknown secret key" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# copy
# ---------------------------------------------------------------------------


def test_copy_same_side_sets_target(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_shared")
    assert copy_key(ctx, SECRET_POLICY, "dev", "test", "STRIPE_KEY") == 0
    assert read_env_file(_secrets_file(tmp_path, "test"))["STRIPE_KEY"] == "sk_shared"
    # dev -> test is same-side: no cross-side warning.
    assert "cross-side" not in capsys.readouterr().err


def test_copy_cross_side_warns_but_proceeds(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_dev")
    assert copy_key(ctx, SECRET_POLICY, "dev", "prod", "STRIPE_KEY") == 0
    assert read_env_file(_secrets_file(tmp_path, "prod"))["STRIPE_KEY"] == "sk_dev"
    assert "cross-side" in capsys.readouterr().err


def test_copy_unset_source_errors(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = copy_key(ctx, SECRET_POLICY, "dev", "test", "STRIPE_KEY")
    assert rc == 1
    assert "unset in dev" in capsys.readouterr().err


def test_copy_refuses_tte_key(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = copy_key(ctx, SECRET_POLICY, "dev", "test", "POSTGRES_PASSWORD")
    assert rc == 1
    assert "TTE key" in capsys.readouterr().err


def test_copy_overwrites_target(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_new")
    set_env_key(_secrets_file(tmp_path, "test"), "STRIPE_KEY", "sk_old")
    assert copy_key(ctx, SECRET_POLICY, "dev", "test", "STRIPE_KEY") == 0
    assert read_env_file(_secrets_file(tmp_path, "test"))["STRIPE_KEY"] == "sk_new"
    assert "overwrote" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# value never leaves the file — no value-printing surface at all.
# ---------------------------------------------------------------------------


def test_set_confirmation_never_echoes_value(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    valfile = tmp_path / "value.txt"
    valfile.write_text("sk_super_secret")
    set_key(ctx, SECRET_POLICY, "dev", "STRIPE_KEY", from_file=str(valfile))
    captured = capsys.readouterr()
    assert "sk_super_secret" not in captured.out
    assert "sk_super_secret" not in captured.err


# ---------------------------------------------------------------------------
# config — the CONFIG_POLICY inverts the secret permissions
# (config_and_secrets.md § Tooling): values visible, positional set OK, get
# prints. copy stays value-blind.
# ---------------------------------------------------------------------------


def test_config_scaffold_writes_config_keys_not_secret_keys(tmp_path):
    ctx = _ctx(tmp_path)
    assert scaffold(ctx, CONFIG_POLICY, "dev") == 0
    from docex.envfile import read_env_file
    vals = read_env_file(_config_file(tmp_path, "dev"))
    # The config manifest — PARTNER_URL only, never the secret keys.
    assert vals == {"PARTNER_URL": ""}
    assert "STRIPE_KEY" not in vals
    assert "TELEMETRY_API_KEY" not in vals


def test_config_scaffold_preserves_values(tmp_path):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    file = _config_file(tmp_path, "dev")
    set_env_key(file, "PARTNER_URL", "https://partner.dev.example.com")
    assert scaffold(ctx, CONFIG_POLICY, "dev") == 0
    assert read_env_file(file)["PARTNER_URL"] == "https://partner.dev.example.com"


def test_config_status_shows_value_text(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_config_file(tmp_path, "dev"), "PARTNER_URL", "https://p.example.com")
    assert status(ctx, CONFIG_POLICY, "dev", fmt="text") == 0
    out = capsys.readouterr().out
    assert "PARTNER_URL" in out and "SET" in out
    # config is non-secret — the value column is shown.
    assert "https://p.example.com" in out


def test_config_status_shows_value_json(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_config_file(tmp_path, "dev"), "PARTNER_URL", "https://p.example.com")
    assert status(ctx, CONFIG_POLICY, "dev", fmt="json") == 0
    import json
    data = json.loads(capsys.readouterr().out)
    partner = next(d for d in data if d["key"] == "PARTNER_URL")
    assert partner["state"] == "SET"
    assert partner["value"] == "https://p.example.com"  # values_visible=True


def test_config_set_accepts_positional_value(tmp_path):
    ctx = _ctx(tmp_path)
    assert set_key(
        ctx, CONFIG_POLICY, "dev", "PARTNER_URL",
        value="https://positional.example.com",
    ) == 0
    from docex.envfile import read_env_file
    assert read_env_file(_config_file(tmp_path, "dev"))["PARTNER_URL"] == (
        "https://positional.example.com"
    )


def test_config_set_supports_from_file(tmp_path):
    ctx = _ctx(tmp_path)
    valfile = tmp_path / "url.txt"
    valfile.write_text("https://fromfile.example.com\n")
    assert set_key(
        ctx, CONFIG_POLICY, "dev", "PARTNER_URL", from_file=str(valfile)
    ) == 0
    from docex.envfile import read_env_file
    assert read_env_file(_config_file(tmp_path, "dev"))["PARTNER_URL"] == (
        "https://fromfile.example.com"
    )


def test_config_get_prints_value(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_config_file(tmp_path, "dev"), "PARTNER_URL", "https://get.example.com")
    assert get_key(ctx, CONFIG_POLICY, "dev", "PARTNER_URL") == 0
    assert capsys.readouterr().out.strip() == "https://get.example.com"


def test_config_get_unset_key_errors(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    scaffold(ctx, CONFIG_POLICY, "dev")  # declares PARTNER_URL empty
    rc = get_key(ctx, CONFIG_POLICY, "dev", "MISSING")
    assert rc == 1
    assert "is not set in dev" in capsys.readouterr().err


def test_get_refused_for_secret_policy(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import set_env_key
    set_env_key(_secrets_file(tmp_path, "dev"), "STRIPE_KEY", "sk_secret_value")
    rc = get_key(ctx, SECRET_POLICY, "dev", "STRIPE_KEY")
    assert rc == 1
    err = capsys.readouterr().err
    assert "not available for secret" in err
    # The value must never be printed, even on the refusal path.
    assert "sk_secret_value" not in err


def test_config_copy_same_side_sets_target(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    set_env_key(_config_file(tmp_path, "dev"), "PARTNER_URL", "https://shared.example.com")
    assert copy_key(ctx, CONFIG_POLICY, "dev", "test", "PARTNER_URL") == 0
    assert read_env_file(_config_file(tmp_path, "test"))["PARTNER_URL"] == (
        "https://shared.example.com"
    )
    assert "cross-side" not in capsys.readouterr().err


def test_config_copy_cross_side_warns_but_proceeds(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    from docex.envfile import read_env_file, set_env_key
    set_env_key(_config_file(tmp_path, "dev"), "PARTNER_URL", "https://dev.example.com")
    assert copy_key(ctx, CONFIG_POLICY, "dev", "prod", "PARTNER_URL") == 0
    assert read_env_file(_config_file(tmp_path, "prod"))["PARTNER_URL"] == (
        "https://dev.example.com"
    )
    assert "cross-side" in capsys.readouterr().err


def test_config_copy_unset_source_errors(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = copy_key(ctx, CONFIG_POLICY, "dev", "test", "PARTNER_URL")
    assert rc == 1
    assert "unset in dev" in capsys.readouterr().err


def test_config_copy_refuses_tte_key(tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = copy_key(ctx, CONFIG_POLICY, "dev", "test", "POSTGRES_PASSWORD")
    assert rc == 1
    assert "TTE key" in capsys.readouterr().err
