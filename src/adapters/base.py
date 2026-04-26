from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


# Status normalization values
STATUS_SELLING = "selling"
STATUS_RESERVED = "reserved"
STATUS_SOLD = "sold"
STATUS_UNKNOWN = "unknown"


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
