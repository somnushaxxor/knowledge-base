from __future__ import annotations

import pytest

from knowledge_gateway.config import Settings
from knowledge_gateway.errors import ConfigurationError


REQUIRED_ENV = (
    "KB_BUNDLE_PATH",
    "KB_STATE_PATH",
    "KB_TAXONOMY_PATH",
    "KB_SCOPE",
    "KB_AUTH_MODE",
    "KB_HOST",
    "KB_PORT",
    "KB_MCP_PATH",
    "KB_LOG_LEVEL",
    "KB_PUSH_AFTER_WRITE",
    "KB_REQUIRE_SECTIONS",
    "KB_GIT_REMOTE",
    "KB_LOCAL_ACTOR",
)


def test_missing_required_environment_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(
        ConfigurationError,
        match="required environment variable is missing: KB_AUTH_MODE",
    ):
        Settings.from_env()


def test_empty_required_environment_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_ENV:
        monkeypatch.setenv(name, "configured")
    monkeypatch.setenv("KB_AUTH_MODE", "   ")

    with pytest.raises(
        ConfigurationError,
        match="required environment variable is missing: KB_AUTH_MODE",
    ):
        Settings.from_env()


def test_selected_token_mode_requires_access_token(
    monkeypatch: pytest.MonkeyPatch, taxonomy_path
) -> None:
    values = {
        "KB_BUNDLE_PATH": "/tmp/bundle",
        "KB_STATE_PATH": "/tmp/state",
        "KB_TAXONOMY_PATH": str(taxonomy_path),
        "KB_SCOPE": "test",
        "KB_AUTH_MODE": "token",
        "KB_HOST": "0.0.0.0",
        "KB_PORT": "8000",
        "KB_MCP_PATH": "/mcp",
        "KB_LOG_LEVEL": "INFO",
        "KB_PUSH_AFTER_WRITE": "false",
        "KB_REQUIRE_SECTIONS": "true",
        "KB_GIT_REMOTE": "origin",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("KB_ACCESS_TOKEN", raising=False)

    with pytest.raises(
        ConfigurationError,
        match="KB_ACCESS_TOKEN is required when KB_AUTH_MODE=token",
    ):
        Settings.from_env().validate()


def test_selected_token_mode_rejects_short_token(settings: Settings) -> None:
    token_settings = Settings(
        **{
            **settings.__dict__,
            "auth_mode": "token",
            "access_token": "too-short",
            "host": "0.0.0.0",
        }
    )

    with pytest.raises(
        ConfigurationError,
        match="KB_ACCESS_TOKEN must contain at least 32 characters",
    ):
        token_settings.validate()


def test_runtime_data_cannot_live_in_source_repository(
    settings: Settings,
) -> None:
    source_root = settings.taxonomy_path.parent.parent
    unsafe = Settings(
        **{
            **settings.__dict__,
            "bundle_path": source_root / "runtime" / "bundle",
        }
    )

    with pytest.raises(
        ConfigurationError,
        match="KB_BUNDLE_PATH must stay outside",
    ):
        unsafe.validate()
