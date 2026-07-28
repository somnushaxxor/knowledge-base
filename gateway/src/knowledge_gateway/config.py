"""Environment-backed gateway configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"required environment variable is missing: {name}")
    return value.strip()


def _required_env_bool(name: str) -> bool:
    value = _required_env(name)
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean, got {value!r}")


@dataclass(frozen=True)
class Settings:
    bundle_path: Path
    state_path: Path
    taxonomy_path: Path
    scope: str
    auth_mode: str
    host: str
    port: int
    mcp_path: str
    log_level: str
    push_after_write: bool
    git_remote: str
    require_sections: bool
    access_token: str | None = None
    local_actor: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        auth_mode = _required_env("KB_AUTH_MODE").lower()
        push_after_write = _required_env_bool("KB_PUSH_AFTER_WRITE")
        require_sections = _required_env_bool("KB_REQUIRE_SECTIONS")
        try:
            port = int(_required_env("KB_PORT"))
        except ValueError as exc:
            raise ConfigurationError("KB_PORT must be an integer") from exc
        return cls(
            bundle_path=Path(_required_env("KB_BUNDLE_PATH")),
            state_path=Path(_required_env("KB_STATE_PATH")),
            taxonomy_path=Path(_required_env("KB_TAXONOMY_PATH")),
            scope=_required_env("KB_SCOPE"),
            auth_mode=auth_mode,
            host=_required_env("KB_HOST"),
            port=port,
            mcp_path=_required_env("KB_MCP_PATH"),
            log_level=_required_env("KB_LOG_LEVEL").upper(),
            push_after_write=push_after_write,
            git_remote=_required_env("KB_GIT_REMOTE"),
            require_sections=require_sections,
            access_token=os.getenv("KB_ACCESS_TOKEN"),
            local_actor=os.getenv("KB_LOCAL_ACTOR"),
        )

    def validate(self) -> None:
        if not self.scope:
            raise ConfigurationError("KB_SCOPE must not be empty")
        if self.auth_mode not in {"token", "disabled"}:
            raise ConfigurationError("KB_AUTH_MODE must be 'token' or 'disabled'")
        if self.auth_mode == "token" and (
            self.access_token is None or not self.access_token.strip()
        ):
            raise ConfigurationError(
                "KB_ACCESS_TOKEN is required when KB_AUTH_MODE=token"
            )
        if self.auth_mode == "token" and len(str(self.access_token)) < 32:
            raise ConfigurationError(
                "KB_ACCESS_TOKEN must contain at least 32 characters"
            )
        if self.auth_mode == "disabled" and self.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigurationError(
                "authentication may be disabled only when KB_HOST is loopback"
            )
        if self.auth_mode == "disabled" and (
            self.local_actor is None or not self.local_actor.strip()
        ):
            raise ConfigurationError(
                "KB_LOCAL_ACTOR is required when KB_AUTH_MODE=disabled"
            )
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("KB_PORT must be between 1 and 65535")
        if not self.mcp_path.startswith("/"):
            raise ConfigurationError("KB_MCP_PATH must begin with '/'")
        if self.bundle_path.resolve() == self.state_path.resolve():
            raise ConfigurationError("bundle and state paths must be different")
        repository_root = Path(__file__).resolve().parents[3]
        if (repository_root / "STANDARD.md").is_file():
            for name, path in (
                ("KB_BUNDLE_PATH", self.bundle_path),
                ("KB_STATE_PATH", self.state_path),
            ):
                resolved = path.resolve()
                if resolved == repository_root or repository_root in resolved.parents:
                    raise ConfigurationError(
                        f"{name} must stay outside the agent-kit source repository"
                    )
