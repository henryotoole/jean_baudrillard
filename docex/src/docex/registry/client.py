"""``RegistryClient`` protocol and its result type. Mod 133.

The development-side preinfra check verifies that the container registry
will accept a manifest DELETE — the capability every `fixed` project's
`teardown.sh` depends on. The runtime implementation is in
`urllib_client.py`; unit tests inject a fake.

WHY the result carries the registry's own error code and not just the HTTP
status: a reverse proxy in front of the registry can produce a bare 405
(method rejected) or a bare 404 (wrong route), and reading either as a
verdict invents a misconfiguration that does not exist. Only the registry's
own `errors[].code` distinguishes its answer from something else's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ManifestDeleteResult:
    """Outcome of one ``DELETE /v2/<repo>/manifests/<ref>``.

    Exactly one of ``status`` and ``failure`` is set. ``status`` means a
    response was received; ``failure`` means no response could be obtained
    and names why, so the caller can decline with a specific resolution
    rather than a generic one.
    """

    status: int | None = None
    error_code: str | None = None
    failure: str | None = None   # "no_credential" | "bad_credential_store" | "transport"
    detail: str = ""


class RegistryClient(Protocol):
    """Abstraction over the Registry V2 HTTP API. Never raises: a request
    that cannot be made or completed comes back as a ``failure`` result, so
    the caller decides whether that is a finding or a declination."""

    def delete_manifest(
        self, host: str, repository: str, reference: str,
    ) -> ManifestDeleteResult:
        ...
