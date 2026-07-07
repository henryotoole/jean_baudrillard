"""RepoPings — driven port for pruning processed pings.

The reaper only needs to delete; it never reads or writes ping content.
This is deliberately a distinct, minimal repo from `web`'s / `worker`'s
(the doctrine forbids sharing code across hex modules — each module owns
its own interpretation of the `pings` table).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class RepoPings(ABC):
    @abstractmethod
    def delete_processed_before(self, cutoff: datetime) -> int:
        """Delete every ping processed strictly before ``cutoff``.

        Returns the number of rows deleted.
        """
        raise NotImplementedError
