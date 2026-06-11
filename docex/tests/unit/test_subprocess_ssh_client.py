"""Unit tests for ``SubprocessSSHClient`` command assembly.

Pure command-building; no real ssh is spawned. Integration coverage of
the actual probe lives with the fixed-production preinfra walk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from docex.ssh.subprocess_client import SubprocessSSHClient


def test_ssh_run_builds_expected_args(monkeypatch):
    client = SubprocessSSHClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(
        "docex.ssh.subprocess_client.subprocess.run", fake_run
    )

    rc = client.run("host.example.com", Path("/keys/prod"), "true", user="deploy")
    assert rc == 0
    args = fake_run.call_args[0][0]
    assert args[0] == "ssh"
    assert "-i" in args and args[args.index("-i") + 1] == "/keys/prod"
    assert "deploy@host.example.com" in args
    assert args[-1] == "true"


def test_ssh_run_quiets_known_hosts_warning(monkeypatch):
    """F3 (mod 053): the probe routes known_hosts to /dev/null so the
    read-only ~/.ssh mount doesn't trigger the 'Failed to add the host to
    the list of known_hosts' warning, while still using accept-new."""
    client = SubprocessSSHClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(
        "docex.ssh.subprocess_client.subprocess.run", fake_run
    )

    client.run("h", Path("/k"), "true")
    args = fake_run.call_args[0][0]
    # The -o options are emitted as ["-o", "<opt>"] pairs.
    opts = [args[i + 1] for i, a in enumerate(args) if a == "-o"]
    assert "UserKnownHostsFile=/dev/null" in opts
    assert "StrictHostKeyChecking=accept-new" in opts
    assert "BatchMode=yes" in opts


def test_ssh_run_returns_127_when_ssh_missing(monkeypatch):
    client = SubprocessSSHClient()

    def boom(*_a, **_kw):
        raise FileNotFoundError("ssh not on PATH")

    monkeypatch.setattr("docex.ssh.subprocess_client.subprocess.run", boom)
    assert client.run("h", Path("/k"), "true") == 127
