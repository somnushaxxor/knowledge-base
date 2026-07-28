"""FastMCP transport adapter for the Knowledge Gateway service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from .auth import SINGLE_USER_ACTOR_ID, SingleUserTokenVerifier
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
    mcp = FastMCP(
        name="Knowledge Gateway",
        instructions=(
            "Canonical OKF knowledge-base gateway. Search before mutation, use "
            "expected_revision for updates, and never reuse an idempotency key "
            "for a different request."
        ),
        auth=build_auth(settings),
    )

    @mcp.tool
    async def kb_overview(scope: str) -> dict[str, object]:
        """Read bundle identity, taxonomy, health, and latest durable revision."""
        return await _call(service.overview, actor_from_request(settings), scope)

    @mcp.tool
    async def kb_search(
        scope: str,
        query: str,
        limit: int = 10,
        document_type: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        """Search active OKF metadata and content with optional exact filters."""
        return await _call(
            service.search,
            actor_from_request(settings),
            scope,
            query,
            limit=limit,
            document_type=document_type,
            status=status,
            tags=tags,
        )

    @mcp.tool
    async def kb_get(scope: str, path: str) -> dict[str, object]:
        """Read one complete document with parsed metadata and current revision."""
        return await _call(service.get, actor_from_request(settings), scope, path)

    @mcp.tool
    async def kb_upsert(
        scope: str,
        path: str,
        content: str,
        idempotency_key: str,
        reason: str,
        expected_revision: str | None = None,
        create_only: bool = False,
    ) -> dict[str, object]:
        """Create or replace one complete OKF document with optimistic concurrency."""
        return await _call(
            service.upsert,
            actor_from_request(settings),
            scope,
            path=path,
            content=content,
            idempotency_key=idempotency_key,
            reason=reason,
            expected_revision=expected_revision,
            create_only=create_only,
        )

    @mcp.tool
    async def kb_archive(
        scope: str,
        path: str,
        expected_revision: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, object]:
        """Move a current document under archive/ without destroying Git history."""
        return await _call(
            service.archive,
            actor_from_request(settings),
            scope,
            path=path,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            reason=reason,
        )

    @mcp.tool
    async def kb_history(
        scope: str,
        path: str,
        limit: int = 20,
    ) -> dict[str, object]:
        """Inspect attributable mutation receipts and the local Git history."""
        return await _call(
            service.history,
            actor_from_request(settings),
            scope,
            path,
            limit,
        )

    @mcp.tool
    async def kb_validate(
        scope: str,
        path: str | None = None,
        content: str | None = None,
    ) -> dict[str, object]:
        """Validate one proposed document, or the whole mounted bundle."""
        actor = actor_from_request(settings)
        if (path is None) != (content is None):
            raise ToolError("path and content must be provided together")
        if path is not None and content is not None:
            return await _call(service.validate_proposed, actor, scope, path, content)
        return await _call(service.validate_bundle, actor, scope)

    @mcp.tool
    async def kb_backup_status(scope: str) -> dict[str, object]:
        """Report local Git and remote Git backup recovery points."""
        return await _call(service.backup_status, actor_from_request(settings), scope)

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
