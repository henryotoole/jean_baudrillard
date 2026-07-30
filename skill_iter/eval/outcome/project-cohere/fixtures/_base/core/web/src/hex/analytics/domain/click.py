from dataclasses import dataclass


@dataclass(frozen=True)
class Click:
    """A single recorded hit against a short code."""

    code: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("click code must be non-empty")
