from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from knowledge_gateway.errors import AuthorizationError, ConflictError
from knowledge_gateway.models import Actor
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
    assert receipt["commit"]
    assert receipt["backup"] == "pending"
    assert receipt["idempotent_replay"] is False

    replay = create_note(service, actor, note)
    assert replay["commit"] == receipt["commit"]
    assert replay["idempotent_replay"] is True

    found = service.search(actor, "test", "serializes writes")
    assert found["count"] == 1
    assert found["results"][0]["path"] == "notes/fastmcp-gateway.md"

    loaded = service.get(actor, "test", "notes/fastmcp-gateway.md")
    assert loaded["revision"] == receipt["revision"]
    assert loaded["metadata"]["type"] == "Note"
    assert loaded["content"] == note


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


def test_validation_and_scope_authorization(
    service: KnowledgeGateway, actor: Actor, note: str
) -> None:
    invalid = note.replace("## Relationships", "## Missing")
    result = service.validate_proposed(
        actor, "test", "notes/fastmcp-gateway.md", invalid
    )
    assert result["valid"] is False
    assert any("Relationships" in issue["message"] for issue in result["issues"])

    with pytest.raises(AuthorizationError):
        service.overview(actor, "another-scope")

    reader = Actor("reader", frozenset({"kb:read"}))
    with pytest.raises(AuthorizationError):
        service.upsert(
            reader,
            "test",
            path="notes/fastmcp-gateway.md",
            content=note,
            idempotency_key="reader-write",
            reason="Must be rejected",
            create_only=True,
        )


def test_git_failure_rolls_back_unaccepted_file(
    service: KnowledgeGateway,
    actor: Actor,
    note: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.ensure_ready()

    def fail_commit(*args, **kwargs):
        raise RuntimeError("simulated Git failure")

    monkeypatch.setattr(service.git, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated Git failure"):
        create_note(service, actor, note)

    target = service.settings.bundle_path / "notes" / "fastmcp-gateway.md"
    assert not target.exists()
