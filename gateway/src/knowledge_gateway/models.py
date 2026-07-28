"""Small domain value objects used independently of FastMCP."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    """Authenticated caller identity recorded in mutation receipts."""

    actor_id: str


@dataclass(frozen=True)
class TaxonomyType:
    name: str
    folder: str
    sections: tuple[str, ...]
    filename: str | None = None
    tags_required: bool = True


@dataclass(frozen=True)
class ParsedDocument:
    metadata: dict[str, object]
    body: str
    raw: str
