from dataclasses import dataclass

CODE_LENGTH = 7


@dataclass(frozen=True)
class ShortLink:
    """A resolved mapping from a generated short code to a target URL."""

    code: str
    target_url: str

    def __post_init__(self) -> None:
        if len(self.code) != CODE_LENGTH:
            raise ValueError(f"short code must be exactly {CODE_LENGTH} characters")
        if not self.code.isalnum():
            raise ValueError("short code must be alphanumeric")
        if not (self.target_url.startswith("http://") or self.target_url.startswith("https://")):
            raise ValueError("target_url must be an http(s) URL")
