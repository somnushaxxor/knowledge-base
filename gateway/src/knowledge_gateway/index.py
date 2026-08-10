"""SQLite operational state, audit log, idempotency, and FTS5 projection."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class GatewayIndex:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    path UNINDEXED,
                    title,
                    description,
                    tags,
                    body,
                    tokenize = 'unicode61'
                );

                CREATE TABLE IF NOT EXISTS idempotency (
                    scope TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scope, actor_id, key)
                );

                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    path TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    delegating_principal TEXT,
                    previous_revision TEXT,
                    revision TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    accepted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_path_id ON audit(path, id DESC);
                """
            )

    def replace_document(self, row: dict[str, str]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO documents(
                    path, revision, title, description, type, status,
                    tags_json, body, updated_at
                ) VALUES(
                    :path, :revision, :title, :description, :type, :status,
                    :tags_json, :body, :updated_at
                )
                ON CONFLICT(path) DO UPDATE SET
                    revision=excluded.revision,
                    title=excluded.title,
                    description=excluded.description,
                    type=excluded.type,
                    status=excluded.status,
                    tags_json=excluded.tags_json,
                    body=excluded.body,
                    updated_at=excluded.updated_at
                """,
                row,
            )
            connection.execute("DELETE FROM documents_fts WHERE path = ?", (row["path"],))
            connection.execute(
                """
                INSERT INTO documents_fts(path, title, description, tags, body)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["path"],
                    row["title"],
                    row["description"],
                    " ".join(json.loads(row["tags_json"])),
                    row["body"],
                ),
            )

    def remove_document(self, path: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM documents WHERE path = ?", (path,))
            connection.execute("DELETE FROM documents_fts WHERE path = ?", (path,))

    def clear_documents(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM documents_fts")

    def document_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT count(*) AS count FROM documents").fetchone()
        return int(row["count"])

    @staticmethod
    def build_match_query(query: str) -> str:
        """Build an FTS5 MATCH expression from a free-text query.

        Tokens are joined with OR so synonym-style agent queries still recall
        documents that match only a subset of the terms. BM25 keeps docs that
        hit more tokens ranked higher. Each token is phrase-quoted so FTS
        operators and punctuation are treated as literals.
        """
        tokens = [token for token in query.split() if token]
        escaped_tokens = [token.replace('"', '""') for token in tokens]
        return " OR ".join(f'"{token}"' for token in escaped_tokens)

    def search(
        self,
        query: str,
        *,
        limit: int,
        document_type: str | None,
        status: str | None,
        tags: list[str] | None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, object]]:
        match_query = self.build_match_query(query)
        clauses = []
        parameters: list[object] = []
        if document_type:
            clauses.append("d.type = ?")
            parameters.append(document_type)
        if status:
            clauses.append("d.status = ?")
            parameters.append(status)
        for tag in tags or []:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(d.tags_json) WHERE json_each.value = ?)"
            )
            parameters.append(tag)
        if since:
            clauses.append("d.updated_at >= ?")
            parameters.append(since)
        if until:
            clauses.append("d.updated_at <= ?")
            parameters.append(until)

        if match_query:
            where = ["documents_fts MATCH ?", *clauses]
            parameters = [match_query, *parameters]
            sql = f"""
                SELECT d.path, d.revision, d.title, d.description, d.type,
                       d.status, d.tags_json, d.updated_at,
                       bm25(documents_fts) AS score,
                       snippet(documents_fts, 4, '', '', ' … ', 18) AS excerpt
                FROM documents_fts
                JOIN documents d ON d.path = documents_fts.path
                WHERE {" AND ".join(where)}
                ORDER BY score
                LIMIT ?
            """
        else:
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = f"""
                SELECT d.path, d.revision, d.title, d.description, d.type,
                       d.status, d.tags_json, d.updated_at, 0.0 AS score,
                       substr(d.body, 1, 240) AS excerpt
                FROM documents d
                {where_sql}
                ORDER BY d.updated_at DESC
                LIMIT ?
            """
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [
            {
                **dict(row),
                "tags": json.loads(row["tags_json"]),
            }
            for row in rows
        ]

    def get_idempotent(
        self, scope: str, actor_id: str, key: str
    ) -> tuple[str, dict[str, object]] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT request_hash, response_json FROM idempotency
                WHERE scope = ? AND actor_id = ? AND key = ?
                """,
                (scope, actor_id, key),
            ).fetchone()
        if row is None:
            return None
        return row["request_hash"], json.loads(row["response_json"])

    def record_mutation(
        self,
        *,
        scope: str,
        actor_id: str,
        idempotency_key: str,
        request_hash: str,
        response: dict[str, object],
        audit: dict[str, object],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO idempotency(
                    scope, actor_id, key, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    actor_id,
                    idempotency_key,
                    request_hash,
                    json.dumps(response, sort_keys=True),
                    response["accepted_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO audit(
                    scope, path, operation, actor_id, delegating_principal,
                    previous_revision, revision, commit_hash, reason, accepted_at
                ) VALUES(
                    :scope, :path, :operation, :actor_id, :delegating_principal,
                    :previous_revision, :revision, :commit_hash, :reason, :accepted_at
                )
                """,
                audit,
            )

    def audit_history(self, path: str, limit: int) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT operation, actor_id, delegating_principal,
                       previous_revision, revision, commit_hash, reason, accepted_at
                FROM audit WHERE path = ? ORDER BY id DESC LIMIT ?
                """,
                (path, limit),
            ).fetchall()
        return [dict(row) for row in rows]
