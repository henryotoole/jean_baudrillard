"""RepoPings — driven port for pruning processed pings.

`retention` only needs to delete; it never reads or writes ping content.
This is deliberately a distinct, minimal repo from `pings`' / `processor`'s
(the doctrine forbids sharing code across hex modules — each module owns
its own interpretation of the `pings` table).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class RepoPings(Protocol):
    def delete_processed_before(self, cutoff: datetime) -> int:
        """Delete every ping processed strictly before ``cutoff``.

        Returns the number of rows deleted.
        """
        ...
