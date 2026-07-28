from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from knowledge_gateway.errors import AuthorizationError, ConflictError, ValidationError
from knowledge_gateway.models import Actor
from knowledge_gateway.okf import load_taxonomy, validate_document
from knowledge_gateway.service import KnowledgeGateway


def create_note(
    service: KnowledgeGateway, actor: Actor, content: str
) -> dict[str, object]:
    return service.upsert(
        actor,
        "test",
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

    found = service.search(actor, "test", "serializes writes")
    assert found["count"] == 1
    assert found["results"][0]["path"] == "notes/fastmcp-gateway.md"

    loaded = service.get(actor, "test", "notes/fastmcp-gateway.md")
    assert loaded["revision"] == receipt["revision"]
    assert loaded["metadata"]["type"] == "Note"
    assert loaded["content"] == note


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
            "test",
            path="notes/fastmcp-gateway.md",
            content=updated_content,
            idempotency_key="update-stale",
            reason="Test a stale writer",
            expected_revision="sha256:stale",
        )

    updated = service.upsert(
        actor,
        "test",
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
            "test",
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
        "test",
        path="notes/fastmcp-gateway.md",
        expected_revision=str(created["revision"]),
        idempotency_key="archive-1",
        reason="Note became obsolete",
    )

    assert archived["archived_path"] == "archive/notes/fastmcp-gateway.md"
    assert service.search(actor, "test", "FastMCP")["count"] == 0
    history = service.history(actor, "test", "notes/fastmcp-gateway.md")
    assert [item["operation"] for item in history["audit"]] == ["archive", "upsert"]


def test_validation_and_scope_boundary(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    invalid = note.replace("/notes/another.md", "notes/another.md")
    result = service.validate_proposed(
        actor, "test", "notes/fastmcp-gateway.md", invalid
    )
    assert result["valid"] is False
    assert any("bundle-absolute" in issue["message"] for issue in result["issues"])

    with pytest.raises(AuthorizationError):
        service.overview(actor, "another-scope")


def test_taxonomy_sections_are_guidance(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    content = note.replace("## Summary", "## Context").replace(
        "## Relationships", "## Links"
    )

    result = service.validate_proposed(
        actor, "test", "notes/fastmcp-gateway.md", content
    )

    assert result == {"valid": True, "issue_count": 0, "issues": []}


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
        "test",
        path="notes/nikita.md",
        content=russian,
        idempotency_key="create-nikita",
        reason="Create Russian birthday note",
        create_only=True,
    )
    service.upsert(
        actor,
        "test",
        path="notes/anya.md",
        content=english,
        idempotency_key="create-anya",
        reason="Create English birthday note",
        create_only=True,
    )

    found = service.search(actor, "test", "Никита день рождения birthday")
    paths = [result["path"] for result in found["results"]]

    assert "notes/nikita.md" in paths
    assert "notes/anya.md" in paths
    assert paths[0] == "notes/nikita.md"
