"""``DnsResolver`` protocol. Mod 054.

The development-side preinfra check verifies that each ``dev`` web
hostname resolves in public DNS before ``envinfra up dev`` brings up the
stack (and fires Let's Encrypt HTTP-01 challenges). The runtime
implementation is in ``dnspython_resolver.py``; unit tests inject a fake.
"""

from __future__ import annotations

from typing import Protocol


class DnsResolver(Protocol):
    """Abstraction over public-DNS resolution. The runtime impl is
    dnspython-backed (``dnspython_resolver.py``); unit tests inject a
    fake. Deliberately queries configured nameservers, NOT ``/etc/hosts``
    — the check must see what Let's Encrypt sees."""

    def resolves(self, hostname: str) -> bool:
        """True iff ``hostname`` has at least one A/AAAA record in public
        DNS. False on NXDOMAIN / empty answer. Network/transient errors
        propagate (the caller treats an exception as a check it could not
        complete, distinct from a confirmed non-resolution)."""
        ...
