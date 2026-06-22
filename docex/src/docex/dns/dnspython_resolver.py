"""dnspython-backed ``DnsResolver`` implementation. Mod 054.

This is the only module in docex permitted to ``import dns`` — every
other module reaches DNS through the ``DnsResolver`` protocol, mirroring
the docker/aws/ssh client seams.
"""

from __future__ import annotations

import dns.resolver


class DnspythonResolver:
    """Default ``DnsResolver`` — queries the system's configured
    nameservers via dnspython. Ignores ``/etc/hosts`` by construction."""

    def resolves(self, hostname: str) -> bool:
        # NXDOMAIN/NoAnswer on one rdtype is not a verdict — keep trying
        # the other before concluding "does not resolve". NoNameservers /
        # Timeout and friends are NOT caught here: they mean "couldn't
        # check", which the caller must distinguish from "confirmed
        # missing", so they propagate.
        for rdtype in ("A", "AAAA"):
            try:
                answer = dns.resolver.resolve(hostname, rdtype)
                if len(answer) > 0:
                    return True
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                continue
        return False
