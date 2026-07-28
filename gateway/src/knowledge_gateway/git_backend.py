"""Local Git history and best-effort remote backup operations."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .errors import GatewayError


class GitBackend:
    def __init__(
        self,
        bundle_path: Path,
        state_path: Path,
        remote: str = "origin",
        push_after_write: bool = False,
    ):
        self.bundle_path = bundle_path
        self.state_path = state_path
        self.remote = remote
        self.push_after_write = push_after_write
        self.backup_state_path = state_path / "backup.json"

    def _run(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.bundle_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise GatewayError(f"git {' '.join(args)} failed: {message}")
        return result

    def ensure_repository(self) -> None:
        if not (self.bundle_path / ".git").exists():
            result = self._run("init", "--initial-branch=main", check=False)
            if result.returncode != 0:
                self._run("init")
        self._run("config", "user.name", "Knowledge Gateway")
        self._run("config", "user.email", "gateway@localhost")
        # Allow Git operations when the process uid matches the bind-mounted owner
        # but /etc/passwd naming or mount metadata would otherwise trip safe.directory.
        self._run(
            "config",
            "--global",
            "--add",
            "safe.directory",
            str(self.bundle_path.resolve()),
            check=False,
        )

    def head(self) -> str | None:
        result = self._run("rev-parse", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def commit(
        self,
        paths: list[str],
        *,
        operation: str,
        actor_id: str,
        reason: str,
        delegating_principal: str | None,
    ) -> str:
        self._run("add", "--", *paths)
        staged = self._run("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            head = self.head()
            if head is None:
                raise GatewayError("mutation produced no Git change")
            return head

        subject = f"kb({operation}): {', '.join(paths)}"
        body = [
            subject,
            "",
            f"Actor: {actor_id}",
            f"Reason: {reason}",
        ]
        if delegating_principal:
            body.append(f"Delegating-Principal: {delegating_principal}")
        self._run("commit", "--message", "\n".join(body))
        commit = self.head()
        if commit is None:
            raise GatewayError("Git commit was not created")
        if self.push_after_write:
            self.try_push(commit)
        return commit

    def unstage(self, paths: list[str]) -> None:
        """Best-effort cleanup after a mutation fails before its Git commit."""
        if self.head() is None:
            self._run(
                "rm",
                "--cached",
                "--ignore-unmatch",
                "--",
                *paths,
                check=False,
            )
        else:
            self._run("reset", "--quiet", "HEAD", "--", *paths, check=False)

    def has_remote(self) -> bool:
        result = self._run("remote", "get-url", self.remote, check=False)
        return result.returncode == 0

    def try_push(self, commit: str | None = None) -> bool:
        commit = commit or self.head()
        if commit is None or not self.has_remote():
            return False
        state = self._read_backup_state()
        try:
            self._run("push", self.remote, "HEAD", timeout=60)
        except (GatewayError, subprocess.TimeoutExpired) as exc:
            state.update(
                {
                    "last_attempt_at": _now(),
                    "failure": str(exc),
                    "pending_since": state.get("pending_since") or _now(),
                }
            )
            self._write_backup_state(state)
            return False
        state.update(
            {
                "last_attempt_at": _now(),
                "last_pushed_commit": commit,
                "last_pushed_at": _now(),
                "failure": None,
                "pending_since": None,
            }
        )
        self._write_backup_state(state)
        return True

    def mark_pending(self) -> None:
        state = self._read_backup_state()
        if not state.get("pending_since"):
            state["pending_since"] = _now()
            self._write_backup_state(state)

    def backup_status(self) -> dict[str, object]:
        head = self.head()
        state = self._read_backup_state()
        synced = head is not None and state.get("last_pushed_commit") == head
        if head and not synced:
            self.mark_pending()
            state = self._read_backup_state()
        return {
            "remote": self.remote if self.has_remote() else None,
            "local_commit": head,
            "last_pushed_commit": state.get("last_pushed_commit"),
            "last_pushed_at": state.get("last_pushed_at"),
            "pending_since": state.get("pending_since"),
            "failure": state.get("failure"),
            "status": "synced" if synced else "pending",
        }

    def history(self, path: str, limit: int) -> list[dict[str, object]]:
        format_string = "%H%x1f%aI%x1f%s%x1e"
        result = self._run(
            "log",
            "--follow",
            f"--max-count={limit}",
            f"--format={format_string}",
            "--",
            path,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return []
        entries: list[dict[str, object]] = []
        for record in result.stdout.strip("\x1e\n").split("\x1e"):
            fields = record.strip().split("\x1f")
            if len(fields) == 3:
                entries.append(
                    {"commit": fields[0], "accepted_at": fields[1], "summary": fields[2]}
                )
        return entries

    def _read_backup_state(self) -> dict[str, object]:
        try:
            value = json.loads(self.backup_state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_backup_state(self, state: dict[str, object]) -> None:
        self.state_path.mkdir(parents=True, exist_ok=True)
        temporary = self.backup_state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.backup_state_path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
