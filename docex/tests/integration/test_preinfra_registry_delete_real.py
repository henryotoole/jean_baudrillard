"""Integration test: the manifest-delete probe against real registries.

The positive control for mod 133, and the mod's load-bearing artifact. Two
real ``registry:2`` containers are brought up on ephemeral loopback ports,
**identical except for ``REGISTRY_STORAGE_DELETE_ENABLED``**, and the real
``UrllibRegistryClient`` is run against both:

- flag on  → PRESENT (known-good input)
- flag off → **ABSENT** (known-bad input)

so the finding branch is exercised against a registry that really is
misconfigured and the pass branch against one that really is not. The unit
tests pin the *mapping*; this pins that the mapping is fed the observations
real software actually produces.

**Assertion 2 is the version pin.** The probe reads ``404
MANIFEST_UNKNOWN`` as "the capability is present", which is an *inference*:
it infers that the ``deleteEnabled`` gate was passed because a later stage
(the manifest lookup) was reached. The image is ``registry:2`` because that
is what the doctrine pins. Measured during design: ``registry:3`` does not
honour the flag at all — manifest DELETE returns ``202`` with the flag
unset — so on distribution 3.0 there is no misconfiguration to detect and
nothing discriminates. If a future doctrine bump changes the image to one
that stops discriminating, ``test_flag_off_is_read_as_capability_absent``
goes red and forces the inference in ``plans/modifications/
133_preinfra_registry_delete_probe/overview.md`` Part 1 to be re-derived
rather than silently lost. Do not "fix" that test by relaxing it.

**No image is pushed.** The probe deletes a 64-zero digest under a
repository that does not exist, so it is side-effect-free by construction
— which matters because in production it runs against preinfra shared by
every project on the machine. ``test_flag_on_is_read_as_capability_present``
asserts the registry's catalog is still empty afterwards.

**Deviation from the implementation steps, recorded deliberately.** Step 8
specifies registries *without* htpasswd, with arm 3 covering auth via a
wrong credential. Those two cannot both hold: a registry with no auth
configured ignores the ``Authorization`` header entirely, so a wrong
credential produces the *same* answer as a right one and arm 3 would assert
nothing. Both registries therefore run **with** htpasswd, which is also
closer to the real deployment (``container_registry.md`` prescribes
htpasswd) and makes arm 1 additionally prove that the real
credential-reading path authenticates successfully. The flag remains the
only difference between the two containers.

Gated by ``@pytest.mark.integration``; auto-skipped when no docker daemon
is reachable (see ``conftest.py``).
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from docex.pipeline.preinfra import (
    _DELETE_PROBE_DIGEST,
    _DELETE_PROBE_REPOSITORY,
    _DOCEX_INGRESS_NETWORK,
    run_preinfra,
)
from docex.registry.urllib_client import UrllibRegistryClient


# Doctrine-pinned registry image. See the module docstring: this constant is
# half of the version pin — changing it is what the flag-off assertion is
# guarding against.
_IMAGE = "registry:2"

_PROBE_USER = "probe"
_PROBE_PASSWORD = "probepass"

# bcrypt of `_PROBE_PASSWORD`, hardcoded. WHY hardcoded: `registry:2` accepts
# only bcrypt htpasswd entries, and there is no bcrypt available to generate
# one at test time — no `htpasswd` binary on the host or in the image, and
# Python's `crypt` (which can emit `$2b$`) is deprecated and gone in 3.13.
# This is a throwaway fixture credential for an ephemeral loopback container,
# not a secret: nothing it guards outlives the test.
_HTPASSWD_LINE = (
    f"{_PROBE_USER}:$2b$12$LJslnnVsARtR0nsiTmKuOO0NgoSCKeEbyzw9w9HCBv/DaIgnkbD8a"
)

_READY_TIMEOUT_SECONDS = 30.0


def _http_status(url: str, *, timeout: float = 2.0) -> int | None:
    """Status of a GET, or ``None`` if no response was obtained."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def _wait_until_serving(host: str) -> None:
    """Poll ``GET /v2/`` until the registry answers.

    A 401 counts as serving — with htpasswd on, that IS the API responding.
    Polling rather than sleeping a fixed interval: container start time is
    not a constant, and a fixed sleep is either slow or flaky.
    """
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _http_status(f"http://{host}/v2/") in (200, 401):
            return
        time.sleep(0.2)
    raise AssertionError(f"registry at {host} never started serving /v2/")


def _published_host(container: str) -> str:
    """The ``localhost:<port>`` the container's 5000 is published on.

    Read back from docker rather than chosen in advance: asking docker for a
    free port (``-p 127.0.0.1:0:5000``) and then reading the assignment has
    no race, where picking a port ourselves does.
    """
    out = subprocess.check_output(
        ["docker", "port", container, "5000/tcp"], text=True
    )
    port = out.splitlines()[0].strip().rsplit(":", 1)[1]
    return f"localhost:{port}"


def _write_docker_config(path: Path, entries: dict[str, tuple[str, str]]) -> Path:
    """Write a Docker config with an ``auths`` entry per host.

    Exercises the real credential-reading path in ``UrllibRegistryClient``
    (the whole reason it takes a ``docker_config_path`` override) instead of
    stubbing it.
    """
    auths = {
        host: {
            "auth": base64.b64encode(f"{user}:{pw}".encode()).decode(),
        }
        for host, (user, pw) in entries.items()
    }
    path.write_text(json.dumps({"auths": auths}))
    return path


@pytest.fixture
def registry_pair(tmp_path: Path):
    """Two real ``registry:2`` containers, differing only in the flag.

    Yields ``{"on": host, "off": host}``. Torn down in a ``finally`` so a
    failing assertion cannot leak containers onto the machine.
    """
    htpasswd = tmp_path / "htpasswd"
    htpasswd.write_text(_HTPASSWD_LINE + "\n")
    # World-readable: the registry process inside the container is not the
    # host uid that owns this file.
    htpasswd.chmod(0o644)

    suffix = uuid.uuid4().hex[:8]
    names = {"on": f"docex-m133-on-{suffix}", "off": f"docex-m133-off-{suffix}"}
    # Identical but for this. Keep it that way: the controlled comparison is
    # the entire point of the two-container design.
    flag_env = {"on": ["-e", "REGISTRY_STORAGE_DELETE_ENABLED=true"], "off": []}

    try:
        for arm, name in names.items():
            subprocess.run(
                [
                    "docker", "run", "-d", "--name", name,
                    "-p", "127.0.0.1:0:5000",
                    *flag_env[arm],
                    "-e", "REGISTRY_AUTH=htpasswd",
                    "-e", "REGISTRY_AUTH_HTPASSWD_REALM=docex-mod133",
                    "-e", "REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd",
                    "-v", f"{htpasswd}:/auth/htpasswd:ro",
                    _IMAGE,
                ],
                stdout=subprocess.DEVNULL, check=True,
            )
        hosts = {arm: _published_host(name) for arm, name in names.items()}
        for host in hosts.values():
            _wait_until_serving(host)
        yield hosts
    finally:
        for name in names.values():
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )


def _probe(host: str, config: Path):
    """Run the real client's probe against ``host``."""
    client = UrllibRegistryClient(docker_config_path=config, timeout=10.0)
    return client.delete_manifest(
        host, _DELETE_PROBE_REPOSITORY, _DELETE_PROBE_DIGEST
    )


def _run_dev_preinfra(ctx, fake_docker, fake_dns, host: str, config: Path) -> int:
    """A full development-side ``run_preinfra`` whose registry is ``host``.

    Docker and DNS are faked because they are not what this test is about;
    the registry and the client that talks to it are real.
    """
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    ctx.infra.container_registry = host
    return run_preinfra(
        ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=UrllibRegistryClient(docker_config_path=config, timeout=10.0),
    )


@pytest.mark.integration
def test_flag_on_is_read_as_capability_present(
    registry_pair, tmp_path, sample_ctx, fake_docker, fake_dns, capsys,
):
    """Known-good input: delete enabled → PRESENT, rc 0, nothing declined."""
    host = registry_pair["on"]
    config = _write_docker_config(
        tmp_path / "config_on.json", {host: (_PROBE_USER, _PROBE_PASSWORD)}
    )

    result = _probe(host, config)
    assert result.failure is None, result.detail
    assert result.status == 404
    assert result.error_code == "MANIFEST_UNKNOWN"

    rc = _run_dev_preinfra(sample_ctx, fake_docker, fake_dns, host, config)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "all checks passed" in out
    assert "Declined" not in out

    # The side-effect-free contract, verified against the real registry
    # rather than asserted: nothing was created by probing it.
    catalog_url = f"http://{host}/v2/_catalog"
    request = urllib.request.Request(catalog_url)
    token = base64.b64encode(
        f"{_PROBE_USER}:{_PROBE_PASSWORD}".encode()
    ).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=5.0) as resp:
        catalog = json.loads(resp.read())
    assert catalog.get("repositories") in (None, []), catalog


@pytest.mark.integration
def test_flag_off_is_read_as_capability_absent(
    registry_pair, tmp_path, sample_ctx, fake_docker, fake_dns, capsys,
):
    """Known-bad input: delete disabled → ABSENT, rc **1**.

    THIS IS THE VERSION PIN (see the module docstring). It is also the only
    place in the suite where the finding branch runs against a registry that
    genuinely is misconfigured — the smoke walk cannot reach it, because this
    machine's registry has the flag set.
    """
    host = registry_pair["off"]
    config = _write_docker_config(
        tmp_path / "config_off.json", {host: (_PROBE_USER, _PROBE_PASSWORD)}
    )

    result = _probe(host, config)
    assert result.failure is None, result.detail
    assert result.status == 405
    assert result.error_code == "UNSUPPORTED"

    rc = _run_dev_preinfra(sample_ctx, fake_docker, fake_dns, host, config)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "REGISTRY_STORAGE_DELETE_ENABLED" in out
    assert "teardown.sh" in out
    assert host in out


@pytest.mark.integration
def test_wrong_credential_is_declined_not_a_verdict(
    registry_pair, tmp_path, sample_ctx, fake_docker, fake_dns, capsys,
):
    """A rejected credential yields ``401``, which is no verdict either way.

    The registry's auth middleware runs ahead of the delete handler, so a
    401 arrives regardless of the flag — this is the trap that let the
    original defect survive several releases. It must decline at rc 0 and
    claim nothing about the capability.
    """
    host = registry_pair["on"]
    config = _write_docker_config(
        tmp_path / "config_bad.json", {host: (_PROBE_USER, "not-the-password")}
    )

    result = _probe(host, config)
    # An HTTPError is a response: 401 must arrive as a status, never as a
    # transport failure. Getting this wrong is what would turn the ABSENT
    # 405 into a declination and delete the only branch that can fail.
    assert result.failure is None, result.detail
    assert result.status == 401

    rc = _run_dev_preinfra(sample_ctx, fake_docker, fake_dns, host, config)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "Declined" in out
    assert "lacks delete scope" in out
    assert "REGISTRY_STORAGE_DELETE_ENABLED" not in out
    # The credential must not leak into operator-facing output — not the
    # base64 blob, not the password.
    assert "not-the-password" not in out
    assert base64.b64encode(
        f"{_PROBE_USER}:not-the-password".encode()
    ).decode() not in out
