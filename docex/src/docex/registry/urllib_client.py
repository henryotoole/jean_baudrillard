"""urllib-backed ``RegistryClient`` implementation. Mod 133.

This is the only module in docex permitted to ``import urllib.request``
for registry HTTP — every other module reaches the Registry V2 API through
the ``RegistryClient`` protocol, mirroring the docker/aws/ssh/dns client
seams (see ``dns/dnspython_resolver.py``).

The credential comes from the operator's Docker config (the file
``docker login`` writes). WHY read it directly rather than shelling out to
``docker``: the probe must be able to say "there is no credential for this
host" as a *specific* declination, and a `docker` invocation collapses that
into a generic failure. The flip side is that a credential held by a
``credsStore``/``credHelpers`` helper is not readable here; that is reported
as its own declination rather than guessed at.

SECURITY: no credential — neither the base64 blob nor the decoded
user/password — is ever placed in a result field, printed, or logged.
``detail`` is operator-facing text and stays credential-free.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from docex.registry.client import ManifestDeleteResult

# Bound the body read: a verdict needs at most an `errors[]` array, and an
# unbounded read on a hostile/wedged endpoint is a hang in disguise.
_MAX_BODY_BYTES = 64 * 1024

# WHY http for these hosts: this mirrors Docker's own insecure-registry
# default (localhost is trusted without TLS by dockerd), not a test
# affordance. A registry reached over loopback has no cert to present.
_INSECURE_HOSTS = frozenset({"localhost", "127.0.0.1"})


class UrllibRegistryClient:
    """Default ``RegistryClient`` — one authenticated request via urllib.

    ``docker_config_path`` overrides the credential source (default
    ``~/.docker/config.json``); the integration test points it at a temp
    config so the real credential-reading path is exercised rather than
    stubbed. ``timeout`` is explicit and bounded so a wedged registry
    cannot hang ``envinfra up dev`` forever.
    """

    def __init__(
        self,
        *,
        docker_config_path: Path | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._config_path = (
            docker_config_path
            if docker_config_path is not None
            else Path.home() / ".docker" / "config.json"
        )
        self._timeout = timeout

    def delete_manifest(
        self, host: str, repository: str, reference: str,
    ) -> ManifestDeleteResult:
        auth, cred_failure = self._read_auth(host)
        if cred_failure is not None:
            return cred_failure

        url = f"{_scheme_for(host)}://{host}/v2/{repository}/manifests/{reference}"
        request = urllib.request.Request(url, method="DELETE")
        request.add_header("Authorization", f"Basic {auth}")
        request.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                body = resp.read(_MAX_BODY_BYTES)
                return ManifestDeleteResult(
                    status=resp.status,
                    error_code=_error_code(body),
                    detail=f"{resp.status} from {host}",
                )
        except urllib.error.HTTPError as exc:
            # WHY this clause comes first and does NOT produce a `failure`:
            # an HTTPError IS a response. The ABSENT finding is a 405, so
            # mapping 4xx to `failure` would silently delete the only branch
            # of this check that can fail.
            body = b""
            try:
                body = exc.read(_MAX_BODY_BYTES)
            except Exception:  # noqa: BLE001 — a body we can't read is just no code
                pass
            return ManifestDeleteResult(
                status=exc.code,
                error_code=_error_code(body),
                detail=f"{exc.code} from {host}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # DNS failure, connection refused, TLS failure, timeout — no
            # response at all, so no verdict is available from this request.
            return ManifestDeleteResult(
                failure="transport",
                detail=f"could not reach {host}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — the protocol forbids raising
            return ManifestDeleteResult(
                failure="transport",
                detail=f"could not probe {host}: {exc!r}",
            )

    def _read_auth(
        self, host: str,
    ) -> tuple[str | None, ManifestDeleteResult | None]:
        """Return ``(auth_blob, None)`` or ``(None, declination_result)``.

        Every unreadable-credential mode becomes a ``failure`` result, never
        an exception, so the caller can decline with the right resolution.
        """
        path = self._config_path
        if not path.is_file():
            return None, ManifestDeleteResult(
                failure="no_credential",
                detail=f"no Docker config at {path}",
            )
        try:
            config = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001 — unreadable == no credential
            return None, ManifestDeleteResult(
                failure="no_credential",
                detail=f"could not parse Docker config {path} ({exc})",
            )
        auths = config.get("auths") if isinstance(config, dict) else None
        entry = auths.get(host) if isinstance(auths, dict) else None
        if not isinstance(entry, dict):
            return None, ManifestDeleteResult(
                failure="no_credential",
                detail=f"no auths entry for {host!r} in {path}",
            )
        auth = entry.get("auth")
        if not auth:
            # Not a bug: the credential lives in an external helper and
            # docex will not shell out to one.
            return None, ManifestDeleteResult(
                failure="bad_credential_store",
                detail=(
                    f"the auths entry for {host!r} in {path} carries no "
                    f"inline credential (a credsStore/credHelpers helper "
                    f"holds it)"
                ),
            )
        try:
            decoded = base64.b64decode(auth, validate=True).decode("utf-8")
        except Exception:  # noqa: BLE001 — detail must not echo the blob
            return None, ManifestDeleteResult(
                failure="no_credential",
                detail=(
                    f"the auths entry for {host!r} in {path} is not valid "
                    f"base64"
                ),
            )
        if ":" not in decoded:
            return None, ManifestDeleteResult(
                failure="no_credential",
                detail=(
                    f"the auths entry for {host!r} in {path} does not decode "
                    f"to user:password"
                ),
            )
        return auth, None


def _scheme_for(host: str) -> str:
    """``http`` for a loopback host (bare or ``host:port``), else ``https``."""
    hostname = host.rsplit(":", 1)[0] if ":" in host else host
    return "http" if hostname in _INSECURE_HOSTS else "https"


def _error_code(body: bytes) -> str | None:
    """The registry's own ``errors[0].code``, or ``None``.

    ``None`` covers an absent body, a non-JSON body, and JSON without an
    error code — all of which the caller must treat as "no registry code",
    never as a verdict.
    """
    if not body:
        return None
    try:
        doc = json.loads(body)
    except Exception:  # noqa: BLE001 — a non-JSON body carries no code
        return None
    if not isinstance(doc, dict):
        return None
    errors = doc.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    code = first.get("code")
    return code if isinstance(code, str) else None
