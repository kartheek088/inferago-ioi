from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.http_client import SafeHttp


class ConnectorUnavailable(Exception):
    """Raised when a connector cannot run (e.g. missing credentials). Message = setup instructions."""


@dataclass
class CollectedItem:
    external_id: str
    url: str | None
    title: str | None
    content: str
    author: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    org_name: str | None = None
    org_website: str | None = None
    evidence_type: str = "post"
    # For documents: [(page_reference, text)]
    pages: list[tuple[str | None, str]] | None = None
    document_name: str | None = None
    # Public, poster-published contact routes: (contact_type, value, source_url, verified, method)
    contact_routes: list[tuple[str, str, str, bool, str]] = field(default_factory=list)
    needs_manual_review: bool = False
    deadline: datetime | None = None
    budget_text: str | None = None


@dataclass
class CollectContext:
    http: SafeHttp
    config: dict[str, Any]
    cursor: dict[str, Any]
    query_terms: list[str]
    max_items: int
    log: Callable[[str], None]


class Connector(Protocol):
    key: str

    def collect(self, ctx: CollectContext) -> Iterator[CollectedItem]: ...


def from_unix(ts: int | float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), UTC).replace(tzinfo=None)
