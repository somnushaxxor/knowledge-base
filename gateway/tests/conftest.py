from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowledge_gateway.config import Settings
from knowledge_gateway.models import Actor
from knowledge_gateway.service import KnowledgeGateway


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
os.environ.update(
    {
        "KB_BUNDLE_PATH": "/tmp/knowledge-gateway-import-test/bundle",
        "KB_STATE_PATH": "/tmp/knowledge-gateway-import-test/state",
        "KB_TAXONOMY_PATH": str(
            _REPOSITORY_ROOT
            / "gateway"
            / "tests"
            / "fixtures"
            / "taxonomy.yaml"
        ),
        "KB_SCOPE": "test-import",
        "KB_AUTH_MODE": "disabled",
        "KB_LOCAL_ACTOR": "test-import",
        "KB_HOST": "127.0.0.1",
        "KB_PORT": "8000",
        "KB_MCP_PATH": "/mcp",
        "KB_LOG_LEVEL": "INFO",
        "KB_PUSH_AFTER_WRITE": "false",
        "KB_GIT_REMOTE": "origin",
    }
)


@pytest.fixture
def taxonomy_path() -> Path:
    return (
        _REPOSITORY_ROOT
        / "gateway"
        / "tests"
        / "fixtures"
        / "taxonomy.yaml"
    )


@pytest.fixture
def settings(tmp_path: Path, taxonomy_path: Path) -> Settings:
    return Settings(
        bundle_path=tmp_path / "bundle",
        state_path=tmp_path / "state",
        taxonomy_path=taxonomy_path,
        scope="test",
        auth_mode="disabled",
        host="127.0.0.1",
        port=8000,
        mcp_path="/mcp",
        log_level="INFO",
        push_after_write=False,
        git_remote="origin",
        local_actor="test-local",
    )


@pytest.fixture
def service(settings: Settings) -> KnowledgeGateway:
    return KnowledgeGateway(settings)


@pytest.fixture
def actor() -> Actor:
    return Actor(actor_id="agent:test")


@pytest.fixture
def note() -> str:
    return """---
type: Note
title: FastMCP Gateway
description: A gateway implementation note.
status: active
tags:
  - gateway
  - mcp
generated: false
---

## Summary

One authority for knowledge.

## Details

The gateway serializes writes.

## Relationships

See [another note](/notes/another.md).
"""
