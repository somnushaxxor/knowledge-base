"""The storage and consistency core behind the MCP tool surface."""

from __future__ import annotations

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
            settings.push_after_write,
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
                    "sections": list(entry.sections),
                }
                for name, entry in self.taxonomy.items()
            },
            "document_count": self.index.document_count(),
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
    ) -> dict[str, object]:
        self._authorize(scope)
        self.ensure_ready()
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be between 1 and 100")
        if document_type and document_type not in self.taxonomy:
            raise ValidationError(f"unknown document type: {document_type}")
        results = self.index.search(
            query,
            limit=limit,
            document_type=document_type,
            status=status,
            tags=tags,
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
        document = validate_document(
            normalized,
            content,
            self.taxonomy,
            require_sections=self.settings.require_sections,
        )

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
            try:
                commit = self.git.commit(
                    [normalized],
                    operation="upsert",
                    actor_id=actor.actor_id,
                    reason=reason,
                    delegating_principal=None,
                )
            except Exception:
                self.git.unstage([normalized])
                if previous_content is None:
                    target.unlink(missing_ok=True)
                    self._remove_empty_parents(target.parent)
                else:
                    self._atomic_write(target, previous_content)
                raise
            accepted_at = now()
            revision = revision_for(content)
            self.index.replace_document(
                self._index_row(normalized, revision, document, accepted_at)
            )
            if not self.settings.push_after_write:
                self.git.mark_pending()
            backup = self.git.backup_status()["status"]
            response: dict[str, object] = {
                "path": normalized,
                "revision": revision,
                "commit": commit,
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
                    "commit_hash": commit,
                    "reason": reason,
                    "accepted_at": accepted_at,
                },
            )
            return response

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
            try:
                commit = self.git.commit(
                    [normalized, archived_path],
                    operation="archive",
                    actor_id=actor.actor_id,
                    reason=reason,
                    delegating_principal=None,
                )
            except Exception:
                self.git.unstage([normalized, archived_path])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(archived_target, target)
                self._remove_empty_parents(archived_target.parent)
                raise
            accepted_at = now()
            self.index.remove_document(normalized)
            if not self.settings.push_after_write:
                self.git.mark_pending()
            backup = self.git.backup_status()["status"]
            response: dict[str, object] = {
                "path": normalized,
                "archived_path": archived_path,
                "revision": current_revision,
                "commit": commit,
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
                    "commit_hash": commit,
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
        normalized = normalize_document_path(path)
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
            validate_document(
                path,
                content,
                self.taxonomy,
                require_sections=self.settings.require_sections,
            )
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
                    require_sections=self.settings.require_sections,
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
        return {"scope": scope, "git": self.git.backup_status()}

    def rebuild_index(self) -> None:
        self.index.clear_documents()
        for file_path in find_markdown_files(self.settings.bundle_path):
            relative = file_path.relative_to(self.settings.bundle_path).as_posix()
            if relative.startswith("archive/"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                # Index existing bundles even when section headings still drift
                # from taxonomy; writes keep full require_sections=True checks.
                document = validate_document(
                    relative,
                    content,
                    self.taxonomy,
                    require_sections=False,
                )
            except (OSError, UnicodeError, ValidationError):
                continue
            self.index.replace_document(
                self._index_row(relative, revision_for(content), document, now())
            )

    def _authorize(self, scope: str) -> None:
        if scope != self.settings.scope:
            raise AuthorizationError("scope is not available to this gateway instance")

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
        # Git has one shared index. A repository-wide lock prevents two writes
        # to different documents from racing while staging and committing.
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
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

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
            "tags_json": json.dumps(metadata["tags"], ensure_ascii=False),
            "body": document.body,
            "updated_at": accepted_at,
        }


def revision_for(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


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
