from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


# Status normalization values
STATUS_SELLING = "selling"
STATUS_RESERVED = "reserved"
STATUS_SOLD = "sold"
STATUS_UNKNOWN = "unknown"


def parse_price_int(value: object) -> int | None:
    """Return an integer price from adapter payload values, if one is present.

    Source payloads are inconsistent: some APIs return integers, some return
    numeric strings, and some include display punctuation. Keep the normalized
    integer here while adapters continue carrying the original display value in
    ``price_raw``.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return int(text)
    except ValueError:
        digits = "".join(c for c in text if c.isdigit())
        return int(digits) if digits else None


@dataclass
class UsedListing:
    source: str
    listing_id: str
    title: str
    price_raw: str | None = None
    price: int | None = None
    url: str | None = None
    location: str | None = None
    status: str | None = None
    crawled_at: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class SourceAdapter(Protocol):
    source_name: str

    def fetch_recent(
        self,
        *,
        pages: int = 1,
        category: str | None = None,
    ) -> list[UsedListing]: ...

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
    ) -> list[UsedListing]: ...
