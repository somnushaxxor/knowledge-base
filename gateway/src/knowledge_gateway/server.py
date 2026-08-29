"""FastMCP transport adapter for the Knowledge Gateway service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from .auth import SINGLE_USER_ACTOR_ID, SingleUserTokenVerifier
from .backup_scheduler import BackupScheduler
from .config import Settings
from .errors import ConfigurationError, GatewayError
from .models import Actor
from .service import KnowledgeGateway


def build_auth(settings: Settings) -> Any | None:
    if settings.auth_mode == "disabled":
        return None
    return SingleUserTokenVerifier(str(settings.access_token))


def actor_from_request(settings: Settings) -> Actor:
    token = get_access_token()
    if token is None:
        if settings.auth_mode != "disabled":
            raise ToolError("authenticated access token is required")
        return Actor(actor_id=str(settings.local_actor))
    return Actor(actor_id=SINGLE_USER_ACTOR_ID)


async def _call(function: Callable[..., dict[str, object]], *args: Any, **kwargs: Any):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except GatewayError as exc:
        details = getattr(exc, "issues", None)
        suffix = f": {details}" if details else ""
        raise ToolError(f"{exc}{suffix}") from exc


def create_mcp(
    settings: Settings | None = None,
    service: KnowledgeGateway | None = None,
) -> FastMCP:
    settings = settings or Settings.from_env()
    settings.validate()
    service = service or KnowledgeGateway(settings)
    service.ensure_ready()
    BackupScheduler(service).start()
    mcp = FastMCP(
        name="Knowledge Gateway",
        instructions=(
            "Canonical OKF knowledge-base gateway. Before the first write in a "
            "session, call kb_overview and follow its usage and taxonomy. "
            "Search before mutation. Updates require expected_revision. Never "
            "reuse an idempotency key for a different request. Never write the "
            "live bundle or Git backup directly. Never invent document types. "
            "Report success only after a write receipt."
        ),
        auth=build_auth(settings),
    )

    @mcp.tool
    async def kb_overview() -> dict[str, object]:
        """Read how this knowledge base works: taxonomy (types, purpose, folders,
        sections), write/read usage, health, validation issues, and latest
        durable revision.

        Call this before the first write in a session and follow `usage` plus
        `taxonomy`. Do not copy a parallel write protocol from a skill.
        """
        return await _call(service.overview, actor_from_request(settings))

    @mcp.tool
    async def kb_search(
        query: str,
        limit: int = 10,
        document_type: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, object]:
        """Search active OKF metadata and content with optional exact filters.

        Results include updated_at (last accepted gateway mutation). Optional
        since/until are inclusive ISO-8601 bounds on updated_at. An empty query
        lists matching documents newest-first.
        """
        return await _call(
            service.search,
            actor_from_request(settings),
            query,
            limit=limit,
            document_type=document_type,
            status=status,
            tags=tags,
            since=since,
            until=until,
        )

    @mcp.tool
    async def kb_get(path: str) -> dict[str, object]:
        """Read one complete document with parsed metadata and current revision."""
        return await _call(service.get, actor_from_request(settings), path)

    @mcp.tool
    async def kb_upsert(
        path: str,
        content: str,
        idempotency_key: str,
        reason: str,
        expected_revision: str | None = None,
        create_only: bool = False,
    ) -> dict[str, object]:
        """Create or replace one complete OKF document with optimistic concurrency.

        The gateway validates the document before writing. Invalid documents
        are rejected and not persisted.
        """
        return await _call(
            service.upsert,
            actor_from_request(settings),
            path=path,
            content=content,
            idempotency_key=idempotency_key,
            reason=reason,
            expected_revision=expected_revision,
            create_only=create_only,
        )

    @mcp.tool
    async def kb_put_file(
        path: str,
        content_base64: str,
        idempotency_key: str,
        reason: str,
        expected_revision: str | None = None,
        create_only: bool = False,
    ) -> dict[str, object]:
        """Store a non-text artifact under files/ with optimistic concurrency.

        Path must be bundle-relative and start with files/. Text extensions are
        rejected; knowledge text belongs in OKF Markdown. Send raw bytes as
        standard base64. Maximum decoded size is 10 MiB.
        """
        return await _call(
            service.put_file,
            actor_from_request(settings),
            path=path,
            content_base64=content_base64,
            idempotency_key=idempotency_key,
            reason=reason,
            expected_revision=expected_revision,
            create_only=create_only,
        )

    @mcp.tool
    async def kb_get_file(
        path: str,
        include_content: bool = True,
    ) -> dict[str, object]:
        """Read one files/ artifact: metadata and optional base64 bytes."""
        return await _call(
            service.get_file,
            actor_from_request(settings),
            path,
            include_content=include_content,
        )

    @mcp.tool
    async def kb_list_files() -> dict[str, object]:
        """List non-text artifacts stored under files/."""
        return await _call(service.list_files, actor_from_request(settings))

    @mcp.tool
    async def kb_archive(
        path: str,
        expected_revision: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, object]:
        """Move a current document under archive/ without deleting content."""
        return await _call(
            service.archive,
            actor_from_request(settings),
            path=path,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            reason=reason,
        )

    @mcp.tool
    async def kb_history(
        path: str,
        limit: int = 20,
    ) -> dict[str, object]:
        """Inspect attributable mutation receipts and the local Git history."""
        return await _call(
            service.history,
            actor_from_request(settings),
            path,
            limit,
        )

    return mcp


try:
    _settings = Settings.from_env()
    mcp = create_mcp(_settings)
except ConfigurationError as exc:
    raise SystemExit(f"Knowledge Gateway configuration error: {exc}") from exc


def main() -> None:
    """Run the gateway over MCP Streamable HTTP."""
    try:
        mcp.run(
            transport="http",
            host=_settings.host,
            port=_settings.port,
            path=_settings.mcp_path,
            log_level=_settings.log_level,
        )
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
