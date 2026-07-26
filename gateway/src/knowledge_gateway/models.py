"""Small domain value objects used independently of FastMCP."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Actor:
    """Authenticated caller identity and its gateway permissions."""

    actor_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    delegating_principal: str | None = None

    def can_read(self) -> bool:
        return bool(self.scopes & {"kb:read", "kb:write", "kb:admin"})

    def can_write(self) -> bool:
        return bool(self.scopes & {"kb:write", "kb:admin"})

    def is_admin(self) -> bool:
        return "kb:admin" in self.scopes


@dataclass(frozen=True)
class TaxonomyType:
    name: str
    folder: str
    sections: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDocument:
    metadata: dict[str, object]
    body: str
    raw: str

