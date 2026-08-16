"""The storage and consistency core behind the MCP tool surface."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .config import Settings
from .errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from .files import (
    FILES_FOLDER,
    decode_file_content,
    find_artifact_files,
    media_type_for,
    normalize_file_path,
    revision_for_bytes,
)
from .git_backend import GitBackend
from .index import GatewayIndex
from .models import Actor, ParsedDocument
from .okf import (
    find_markdown_files,
    load_taxonomy,
    normalize_document_path,
    parse_document,
    validate_document,
)


class KnowledgeGateway:
    """Single-scope authority for one mounted OKF bundle."""

    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings
        self.taxonomy = load_taxonomy(settings.taxonomy_path)
        self.index = GatewayIndex(settings.state_path / "gateway.sqlite3")
        self.git = GitBackend(
            settings.bundle_path,
            settings.state_path,
            settings.git_remote,
        )
        self._initialization_lock = threading.Lock()
        self._ready = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        with self._initialization_lock:
            if self._ready:
                return
            self.settings.bundle_path.mkdir(parents=True, exist_ok=True)
            self.settings.state_path.mkdir(parents=True, exist_ok=True)
            (self.settings.state_path / "locks").mkdir(parents=True, exist_ok=True)
            self.index.initialize()
            self.git.ensure_repository()
            self.rebuild_index()
            self._ready = True

    def overview(self, actor: Actor, scope: str) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        validation = self.validate_bundle(actor, scope)
        return {
            "scope": self.settings.scope,
            "bundle_path": str(self.settings.bundle_path),
            "taxonomy": {
                name: {
                    "folder": entry.folder,
                    "filename": entry.filename,
                    "tags_required": entry.tags_required,
                    "sections": list(entry.sections),
                }
                for name, entry in self.taxonomy.items()
            },
            "document_count": self.index.document_count(),
            "file_count": len(find_artifact_files(self.settings.bundle_path)),
            "latest_commit": self.git.head(),
            "health": "ok" if validation["valid"] else "degraded",
            "validation_issue_count": validation["issue_count"],
        }

    def search(
        self,
        actor: Actor,
        scope: str,
        query: str,
        *,
        limit: int = 10,
        document_type: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be between 1 and 100")
        if document_type and document_type not in self.taxonomy:
            raise ValidationError(f"unknown document type: {document_type}")
        since_bound = parse_time_bound(since, "since")
        until_bound = parse_time_bound(until, "until")
        if since_bound and until_bound and since_bound > until_bound:
            raise ValidationError("since must be less than or equal to until")
        results = self.index.search(
            query,
            limit=limit,
            document_type=document_type,
            status=status,
            tags=tags,
            since=since_bound,
            until=until_bound,
        )
        for result in results:
            result.pop("tags_json", None)
        return {"scope": scope, "query": query, "count": len(results), "results": results}

    def get(self, actor: Actor, scope: str, path: str) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = normalize_document_path(path)
        target = self._target(normalized)
        if not target.is_file():
            raise NotFoundError(f"document does not exist: {normalized}")
        content = target.read_text(encoding="utf-8")
        document = parse_document(content)
        return {
            "scope": scope,
            "path": normalized,
            "revision": revision_for(content),
            "metadata": document.metadata,
            "content": content,
        }

    def upsert(
        self,
        actor: Actor,
        scope: str,
        *,
        path: str,
        content: str,
        idempotency_key: str,
        reason: str,
        expected_revision: str | None = None,
        create_only: bool = False,
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = normalize_document_path(path)
        self._require_mutation_fields(idempotency_key, reason)
        request_hash = hash_request(
            {
                "operation": "upsert",
                "scope": scope,
                "path": normalized,
                "content": content,
                "expected_revision": expected_revision,
                "create_only": create_only,
                "reason": reason,
            }
        )
        replay = self._idempotent_replay(actor, idempotency_key, request_hash)
        if replay is not None:
            return replay
        document = validate_document(normalized, content, self.taxonomy)

        with self._mutation_lock():
            replay = self._idempotent_replay(actor, idempotency_key, request_hash)
            if replay is not None:
                return replay
            target = self._target(normalized)
            exists = target.is_file()
            previous_content = target.read_text(encoding="utf-8") if exists else None
            previous_revision = (
                revision_for(previous_content) if previous_content is not None else None
            )
            if exists and create_only:
                raise ConflictError(f"create-only document already exists: {normalized}")
            if exists and expected_revision is None:
                raise ConflictError("expected_revision is required when updating")
            if exists and expected_revision != previous_revision:
                raise ConflictError(
                    f"revision conflict: expected {expected_revision}, current {previous_revision}"
                )
            if not exists and not create_only:
                raise ConflictError("new documents require create_only=true")
            if not exists and expected_revision is not None:
                raise ConflictError("expected_revision must be omitted when creating")

            self._atomic_write(target, content)
            accepted_at = now()
            revision = revision_for(content)
            self.index.replace_document(
                self._index_row(normalized, revision, document, accepted_at)
            )
            self.git.mark_pending()
            backup = self.git.backup_status()["status"]
            response: dict[str, object] = {
                "path": normalized,
                "revision": revision,
                "commit": None,
                "backup": backup,
                "accepted_at": accepted_at,
                "idempotent_replay": False,
            }
            self.index.record_mutation(
                scope=scope,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response=response,
                audit={
                    "scope": scope,
                    "path": normalized,
                    "operation": "upsert",
                    "actor_id": actor.actor_id,
                    "delegating_principal": None,
                    "previous_revision": previous_revision,
                    "revision": revision,
                    "commit_hash": "",
                    "reason": reason,
                    "accepted_at": accepted_at,
                },
            )
            return response

    def put_file(
        self,
        actor: Actor,
        scope: str,
        *,
        path: str,
        content_base64: str,
        idempotency_key: str,
        reason: str,
        expected_revision: str | None = None,
        create_only: bool = False,
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = normalize_file_path(path)
        self._require_mutation_fields(idempotency_key, reason)
        content = decode_file_content(content_base64)
        revision = revision_for_bytes(content)
        request_hash = hash_request(
            {
                "operation": "put_file",
                "scope": scope,
                "path": normalized,
                "revision": revision,
                "expected_revision": expected_revision,
                "create_only": create_only,
                "reason": reason,
            }
        )
        replay = self._idempotent_replay(actor, idempotency_key, request_hash)
        if replay is not None:
            return replay

        with self._mutation_lock():
            replay = self._idempotent_replay(actor, idempotency_key, request_hash)
            if replay is not None:
                return replay
            target = self._target(normalized)
            exists = target.is_file()
            previous_content = target.read_bytes() if exists else None
            previous_revision = (
                revision_for_bytes(previous_content)
                if previous_content is not None
                else None
            )
            if exists and create_only:
                raise ConflictError(f"create-only file already exists: {normalized}")
            if exists and expected_revision is None:
                raise ConflictError("expected_revision is required when updating")
            if exists and expected_revision != previous_revision:
                raise ConflictError(
                    f"revision conflict: expected {expected_revision}, current {previous_revision}"
                )
            if not exists and not create_only:
                raise ConflictError("new files require create_only=true")
            if not exists and expected_revision is not None:
                raise ConflictError("expected_revision must be omitted when creating")

            self._atomic_write_bytes(target, content)
            accepted_at = now()
            self.git.mark_pending()
            backup = self.git.backup_status()["status"]
            response: dict[str, object] = {
                "path": normalized,
                "revision": revision,
                "bytes": len(content),
                "media_type": media_type_for(normalized),
                "commit": None,
                "backup": backup,
                "accepted_at": accepted_at,
                "idempotent_replay": False,
            }
            self.index.record_mutation(
                scope=scope,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response=response,
                audit={
                    "scope": scope,
                    "path": normalized,
                    "operation": "put_file",
                    "actor_id": actor.actor_id,
                    "delegating_principal": None,
                    "previous_revision": previous_revision,
                    "revision": revision,
                    "commit_hash": "",
                    "reason": reason,
                    "accepted_at": accepted_at,
                },
            )
            return response

    def get_file(
        self,
        actor: Actor,
        scope: str,
        path: str,
        *,
        include_content: bool = True,
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = normalize_file_path(path)
        target = self._target(normalized)
        if not target.is_file():
            raise NotFoundError(f"file does not exist: {normalized}")
        content = target.read_bytes()
        payload: dict[str, object] = {
            "scope": scope,
            "path": normalized,
            "revision": revision_for_bytes(content),
            "bytes": len(content),
            "media_type": media_type_for(normalized),
        }
        if include_content:
            payload["content_base64"] = base64.b64encode(content).decode("ascii")
        return payload

    def list_files(self, actor: Actor, scope: str) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        files = []
        for file_path in find_artifact_files(self.settings.bundle_path):
            relative = file_path.relative_to(self.settings.bundle_path).as_posix()
            content = file_path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "revision": revision_for_bytes(content),
                    "bytes": len(content),
                    "media_type": media_type_for(relative),
                }
            )
        return {
            "scope": scope,
            "folder": FILES_FOLDER,
            "count": len(files),
            "files": files,
        }

    def archive(
        self,
        actor: Actor,
        scope: str,
        *,
        path: str,
        expected_revision: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = normalize_document_path(path)
        self._require_mutation_fields(idempotency_key, reason)
        request_hash = hash_request(
            {
                "operation": "archive",
                "scope": scope,
                "path": normalized,
                "expected_revision": expected_revision,
                "reason": reason,
            }
        )
        replay = self._idempotent_replay(actor, idempotency_key, request_hash)
        if replay is not None:
            return replay

        with self._mutation_lock():
            replay = self._idempotent_replay(actor, idempotency_key, request_hash)
            if replay is not None:
                return replay
            target = self._target(normalized)
            if not target.is_file():
                raise NotFoundError(f"document does not exist: {normalized}")
            content = target.read_text(encoding="utf-8")
            current_revision = revision_for(content)
            if expected_revision != current_revision:
                raise ConflictError(
                    f"revision conflict: expected {expected_revision}, current {current_revision}"
                )
            archived_path = f"archive/{normalized}"
            archived_target = self._target(archived_path)
            if archived_target.exists():
                raise ConflictError(f"archive target already exists: {archived_path}")
            archived_target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, archived_target)
            self._remove_empty_parents(target.parent)
            accepted_at = now()
            self.index.remove_document(normalized)
            self.git.mark_pending()
            backup = self.git.backup_status()["status"]
            response: dict[str, object] = {
                "path": normalized,
                "archived_path": archived_path,
                "revision": current_revision,
                "commit": None,
                "backup": backup,
                "accepted_at": accepted_at,
                "idempotent_replay": False,
            }
            self.index.record_mutation(
                scope=scope,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response=response,
                audit={
                    "scope": scope,
                    "path": normalized,
                    "operation": "archive",
                    "actor_id": actor.actor_id,
                    "delegating_principal": None,
                    "previous_revision": current_revision,
                    "revision": current_revision,
                    "commit_hash": "",
                    "reason": reason,
                    "accepted_at": accepted_at,
                },
            )
            return response

    def history(
        self, actor: Actor, scope: str, path: str, limit: int = 20
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        normalized = self._normalize_stored_path(path)
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be between 1 and 100")
        return {
            "scope": scope,
            "path": normalized,
            "audit": self.index.audit_history(normalized, limit),
            "git": self.git.history(normalized, limit),
        }

    def validate_proposed(
        self, actor: Actor, scope: str, path: str, content: str
    ) -> dict[str, object]:
        self._authorize(scope)
        try:
            validate_document(path, content, self.taxonomy)
        except ValidationError as exc:
            return {"valid": False, "issue_count": len(exc.issues), "issues": exc.issues}
        return {"valid": True, "issue_count": 0, "issues": []}

    def validate_bundle(self, actor: Actor, scope: str) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        issues: list[dict[str, str]] = []
        for file_path in find_markdown_files(self.settings.bundle_path):
            relative = file_path.relative_to(self.settings.bundle_path).as_posix()
            validation_path = relative.removeprefix("archive/")
            try:
                validate_document(
                    validation_path,
                    file_path.read_text(encoding="utf-8"),
                    self.taxonomy,
                )
            except (OSError, UnicodeError, ValidationError) as exc:
                if isinstance(exc, ValidationError) and exc.issues:
                    issues.extend(
                        {**issue, "path": relative}
                        for issue in exc.issues
                    )
                else:
                    issues.append({"path": relative, "message": str(exc)})
        return {"valid": not issues, "issue_count": len(issues), "issues": issues}

    def backup_status(self, actor: Actor, scope: str) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        return {
            "scope": scope,
            "backup_interval_hours": self.settings.backup_interval_hours,
            "git": self.git.backup_status(),
        }

    def run_backup(self) -> dict[str, object]:
        """Commit dirty bundle files and best-effort push to the private remote."""
        self.ensure_ready()
        with self._mutation_lock():
            timestamp = now()
            dirty_before = self.git.has_uncommitted_changes()
            commit = self.git.create_backup_commit(timestamp)
            pushed = self.git.try_push(commit)
            status = self.git.backup_status()
            return {
                "timestamp": timestamp,
                "committed": dirty_before and commit is not None,
                "commit": commit,
                "pushed": pushed,
                "status": status["status"],
            }

    def rebuild_index(self) -> None:
        self.index.clear_documents()
        for file_path in find_markdown_files(self.settings.bundle_path):
            relative = file_path.relative_to(self.settings.bundle_path).as_posix()
            if relative.startswith("archive/"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                document = validate_document(relative, content, self.taxonomy)
            except (OSError, UnicodeError, ValidationError):
                continue
            self.index.replace_document(
                self._index_row(relative, revision_for(content), document, now())
            )

    def _authorize(self, scope: str) -> None:
        if scope != self.settings.scope:
            raise AuthorizationError("scope is not available to this gateway instance")

    def _normalize_stored_path(self, path: str) -> str:
        stripped = path.lstrip("/")
        if stripped == FILES_FOLDER or stripped.startswith(f"{FILES_FOLDER}/"):
            return normalize_file_path(path)
        return normalize_document_path(path)

    def _target(self, normalized_path: str) -> Path:
        target = self.settings.bundle_path.joinpath(*normalized_path.split("/"))
        bundle = self.settings.bundle_path.resolve()
        resolved = target.resolve()
        if resolved != bundle and bundle not in resolved.parents:
            raise ValidationError("path escapes the bundle")
        return target

    def _require_mutation_fields(self, idempotency_key: str, reason: str) -> None:
        if not idempotency_key.strip():
            raise ValidationError("idempotency_key must not be empty")
        if len(idempotency_key) > 200:
            raise ValidationError("idempotency_key must not exceed 200 characters")
        if not reason.strip():
            raise ValidationError("reason must not be empty")

    def _idempotent_replay(
        self, actor: Actor, key: str, request_hash: str
    ) -> dict[str, object] | None:
        stored = self.index.get_idempotent(self.settings.scope, actor.actor_id, key)
        if stored is None:
            return None
        stored_hash, response = stored
        if stored_hash != request_hash:
            raise ConflictError("idempotency key was already used for another request")
        return {**response, "idempotent_replay": True}

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        # Repository-wide lock serializes live writes against each other and
        # against the periodic backup commit/push.
        lock_path = self.settings.state_path / "locks" / "mutation.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _atomic_write(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_write_bytes(self, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _fsync_directory(self, directory: Path) -> None:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _remove_empty_parents(self, start: Path) -> None:
        bundle = self.settings.bundle_path.resolve()
        current = start
        while current.resolve() != bundle:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _index_row(
        self,
        path: str,
        revision: str,
        document: ParsedDocument,
        accepted_at: str,
    ) -> dict[str, str]:
        metadata = document.metadata
        return {
            "path": path,
            "revision": revision,
            "title": str(metadata["title"]),
            "description": str(metadata["description"]),
            "type": str(metadata["type"]),
            "status": str(metadata["status"]),
            "tags_json": json.dumps(metadata.get("tags", []), ensure_ascii=False),
            "body": document.body,
            "updated_at": accepted_at,
        }


def revision_for(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def parse_time_bound(value: str | None, field: str) -> str | None:
    """Normalize an inclusive ISO-8601 bound for updated_at filtering."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        raise ValidationError(f"{field} must be a non-empty ISO-8601 timestamp")
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def hash_request(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()
