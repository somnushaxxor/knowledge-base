from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from knowledge_gateway.errors import ConflictError, ValidationError
from knowledge_gateway.models import Actor
from knowledge_gateway.okf import load_taxonomy, validate_document
from knowledge_gateway.service import KnowledgeGateway


def create_note(
    service: KnowledgeGateway, actor: Actor, content: str
) -> dict[str, object]:
    return service.upsert(
        actor,
        path="notes/fastmcp-gateway.md",
        content=content,
        idempotency_key="create-1",
        reason="Create the gateway note",
        create_only=True,
    )


def test_create_search_get_and_idempotent_replay(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    receipt = create_note(service, actor, note)

    assert receipt["revision"].startswith("sha256:")
    assert receipt["commit"] is None
    assert receipt["backup"] == "pending"
    assert receipt["idempotent_replay"] is False
    assert service.git.has_uncommitted_changes()

    replay = create_note(service, actor, note)
    assert replay["commit"] is None
    assert replay["idempotent_replay"] is True

    found = service.search(actor, "serializes writes")
    assert found["count"] == 1
    assert found["results"][0]["path"] == "notes/fastmcp-gateway.md"
    assert "updated_at" in found["results"][0]
    assert found["results"][0]["updated_at"]

    loaded = service.get(actor, "notes/fastmcp-gateway.md")
    assert loaded["revision"] == receipt["revision"]
    assert loaded["metadata"]["type"] == "Note"
    assert loaded["content"] == note


def test_search_exposes_updated_at_and_time_bounds(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    create_note(service, actor, note)
    older = note.replace("FastMCP Gateway", "Older Note").replace(
        "A gateway implementation note.", "An older note."
    )
    service.upsert(
        actor,
        path="notes/older.md",
        content=older,
        idempotency_key="create-older",
        reason="Create an older note",
        create_only=True,
    )
    with service.index.connect() as connection:
        connection.execute(
            "UPDATE documents SET updated_at = ? WHERE path = ?",
            ("2026-08-01T10:00:00+00:00", "notes/older.md"),
        )
        connection.execute(
            "UPDATE documents SET updated_at = ? WHERE path = ?",
            ("2026-08-10T12:00:00+00:00", "notes/fastmcp-gateway.md"),
        )

    recent = service.search(
        actor,
        "",
        since="2026-08-09T00:00:00Z",
        until="2026-08-11T00:00:00+00:00",
    )
    assert [item["path"] for item in recent["results"]] == [
        "notes/fastmcp-gateway.md"
    ]
    assert recent["results"][0]["updated_at"] == "2026-08-10T12:00:00+00:00"

    lexical = service.search(
        actor,
        "gateway",
        since="2026-08-09",
    )
    assert lexical["count"] == 1
    assert lexical["results"][0]["path"] == "notes/fastmcp-gateway.md"

    with pytest.raises(ValidationError, match="ISO-8601"):
        service.search(actor, "", since="yesterday")

    with pytest.raises(ValidationError, match="less than or equal"):
        service.search(
            actor,
            "",
            since="2026-08-11T00:00:00Z",
            until="2026-08-10T00:00:00Z",
        )


def test_periodic_backup_commits_dirty_changes(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    create_note(service, actor, note)
    assert service.git.head() is None
    assert service.git.has_uncommitted_changes()

    result = service.run_backup()

    assert result["committed"] is True
    assert result["commit"]
    assert not service.git.has_uncommitted_changes()
    assert service.git.head() == result["commit"]
    log = service.git._run("log", "-1", "--pretty=%s")
    assert log.stdout.strip().startswith("backup ")


def test_update_requires_current_revision(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    created = create_note(service, actor, note)
    updated_content = note.replace(
        "The gateway serializes writes.",
        "The gateway serializes writes and records audit receipts.",
    )

    with pytest.raises(ConflictError, match="revision conflict"):
        service.upsert(
            actor,
            path="notes/fastmcp-gateway.md",
            content=updated_content,
            idempotency_key="update-stale",
            reason="Test a stale writer",
            expected_revision="sha256:stale",
        )

    updated = service.upsert(
        actor,
        path="notes/fastmcp-gateway.md",
        content=updated_content,
        idempotency_key="update-current",
        reason="Add audit behavior",
        expected_revision=str(created["revision"]),
    )
    assert updated["revision"] != created["revision"]


def test_concurrent_updates_do_not_silently_overwrite(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    created = create_note(service, actor, note)

    def update(label: str) -> dict[str, object]:
        return service.upsert(
            actor,
            path="notes/fastmcp-gateway.md",
            content=note.replace(
                "The gateway serializes writes.",
                f"The gateway accepted writer {label}.",
            ),
            idempotency_key=f"concurrent-{label}",
            reason=f"Concurrent writer {label}",
            expected_revision=str(created["revision"]),
        )

    outcomes: list[object] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, label) for label in ("A", "B")]
        for future in futures:
            try:
                outcomes.append(future.result())
            except Exception as exc:
                outcomes.append(exc)

    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ConflictError) for outcome in outcomes) == 1


def test_archive_preserves_receipt_and_history(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    created = create_note(service, actor, note)
    archived = service.archive(
        actor,
        path="notes/fastmcp-gateway.md",
        expected_revision=str(created["revision"]),
        idempotency_key="archive-1",
        reason="Note became obsolete",
    )

    assert archived["archived_path"] == "archive/notes/fastmcp-gateway.md"
    assert service.search(actor, "FastMCP")["count"] == 0
    history = service.history(actor, "notes/fastmcp-gateway.md")
    assert [item["operation"] for item in history["audit"]] == ["archive", "upsert"]


def test_upsert_rejects_relative_internal_links(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    invalid = note.replace("/notes/another.md", "notes/another.md")
    with pytest.raises(ValidationError, match="document does not satisfy") as caught:
        service.upsert(
            actor,
            path="notes/fastmcp-gateway.md",
            content=invalid,
            idempotency_key="create-invalid",
            reason="Should not persist",
            create_only=True,
        )

    assert any("bundle-absolute" in issue["message"] for issue in caught.value.issues)
    assert not (service.settings.bundle_path / "notes" / "fastmcp-gateway.md").exists()


def test_overview_is_self_describing(
    service: KnowledgeGateway, actor: Actor
) -> None:
    overview = service.overview(actor)

    assert overview["taxonomy"]["Note"]["purpose"] == (
        "Exercise gateway validation in automated tests."
    )
    assert overview["taxonomy"]["Note"]["folder"] == "notes"
    assert overview["taxonomy"]["Note"]["sections"] == [
        "Summary",
        "Details",
        "Relationships",
    ]
    assert overview["taxonomy_policy"]["unknown_types"] == "reject"
    assert overview["usage"]["document"]["required_metadata"][0] == "type"
    assert any("expected_revision" in step for step in overview["usage"]["write"])
    assert "write the live bundle or Git backup directly" in overview["usage"]["never"]
    assert overview["health"] == "ok"
    assert overview["validation_issue_count"] == 0
    assert overview["validation_issues"] == []
    assert any("invalid documents are rejected" in step for step in overview["usage"]["write"])


def test_overview_reports_existing_bundle_issues(
    service: KnowledgeGateway, actor: Actor
) -> None:
    broken = service.settings.bundle_path / "notes" / "broken.md"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text(
        "---\ntitle: Broken\n---\n\n# Broken\n",
        encoding="utf-8",
    )

    overview = service.overview(actor)

    assert overview["health"] == "degraded"
    assert overview["validation_issue_count"] >= 1
    assert any(
        issue["path"] == "notes/broken.md" for issue in overview["validation_issues"]
    )


def test_taxonomy_sections_are_guidance(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    content = note.replace("## Summary", "## Context").replace(
        "## Relationships", "## Links"
    )

    receipt = service.upsert(
        actor,
        path="notes/fastmcp-gateway.md",
        content=content,
        idempotency_key="create-sections",
        reason="Sections are guidance",
        create_only=True,
    )

    assert receipt["path"] == "notes/fastmcp-gateway.md"


def test_taxonomy_supports_wildcard_index_without_tags(tmp_path) -> None:
    taxonomy_path = tmp_path / "taxonomy.yaml"
    taxonomy_path.write_text(
        """\
version: 1
types:
  - type: index
    folder: "**"
    filename: index.md
    tags_required: false
    sections: []
""",
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(taxonomy_path)
    content = """\
---
type: index
title: Notes
description: Navigation for notes.
status: stable
generated: false
---

# Notes
"""

    document = validate_document("notes/index.md", content, taxonomy)

    assert "tags" not in document.metadata
    with pytest.raises(ValidationError, match="document does not satisfy"):
        validate_document("notes/navigation.md", content, taxonomy)


def test_search_ors_tokens_so_synonyms_do_not_kill_recall(
    service: KnowledgeGateway, actor: Actor
) -> None:
    russian = """---
type: Note
title: Nikita
description: Partner profile.
status: active
tags:
  - people
generated: false
---

## Summary

День рождения Никиты — 23 мая.

## Details

Partner notes.

## Relationships

See [another note](/notes/another.md).
"""
    english = """---
type: Note
title: Anya
description: Friend profile.
status: active
tags:
  - people
generated: false
---

## Summary

Birthday: 19 July.

## Details

Friend notes.

## Relationships

See [another note](/notes/another.md).
"""
    service.upsert(
        actor,
        path="notes/nikita.md",
        content=russian,
        idempotency_key="create-nikita",
        reason="Create Russian birthday note",
        create_only=True,
    )
    service.upsert(
        actor,
        path="notes/anya.md",
        content=english,
        idempotency_key="create-anya",
        reason="Create English birthday note",
        create_only=True,
    )

    found = service.search(actor, "Никита день рождения birthday")
    paths = [result["path"] for result in found["results"]]

    assert "notes/nikita.md" in paths
    assert "notes/anya.md" in paths
    assert paths[0] == "notes/nikita.md"
