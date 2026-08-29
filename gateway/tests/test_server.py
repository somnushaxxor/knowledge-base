from __future__ import annotations

import httpx
from fastmcp import Client

from knowledge_gateway.config import Settings
from knowledge_gateway.server import create_mcp
from knowledge_gateway.service import KnowledgeGateway


async def test_mcp_exposes_the_normative_tool_contract(settings: Settings) -> None:
    server = create_mcp(settings, KnowledgeGateway(settings))
    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == {
        "kb_overview",
        "kb_search",
        "kb_get",
        "kb_upsert",
        "kb_put_file",
        "kb_get_file",
        "kb_list_files",
        "kb_archive",
        "kb_history",
    }
    overview = next(tool for tool in tools if tool.name == "kb_overview")
    assert "taxonomy" in (overview.description or "").lower()
    assert "usage" in (overview.description or "").lower()


async def test_http_endpoint_requires_the_configured_bearer_token(
    settings: Settings,
) -> None:
    access_token = "a" * 32
    token_settings = Settings(
        **{
            **settings.__dict__,
            "auth_mode": "token",
            "access_token": access_token,
            "host": "0.0.0.0",
        }
    )
    server = create_mcp(token_settings, KnowledgeGateway(token_settings))
    app = server.http_app(path="/mcp")
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            missing = await client.post("/mcp", headers=headers, json=initialize)
            incorrect = await client.post(
                "/mcp",
                headers={**headers, "Authorization": "Bearer incorrect"},
                json=initialize,
            )
            accepted = await client.post(
                "/mcp",
                headers={**headers, "Authorization": f"Bearer {access_token}"},
                json=initialize,
            )

    assert missing.status_code == 401
    assert incorrect.status_code == 401
    assert accepted.status_code == 200
