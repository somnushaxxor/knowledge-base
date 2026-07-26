from __future__ import annotations

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
        "kb_archive",
        "kb_history",
        "kb_validate",
        "kb_backup_status",
    }
