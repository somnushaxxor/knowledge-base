from __future__ import annotations

import base64

import pytest

from knowledge_gateway.errors import ConflictError, NotFoundError, ValidationError
from knowledge_gateway.files import FILE_MAX_BYTES, decode_file_content, normalize_file_path
from knowledge_gateway.models import Actor
from knowledge_gateway.okf import find_markdown_files, normalize_document_path
from knowledge_gateway.service import KnowledgeGateway


PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def put_pdf(
    service: KnowledgeGateway,
    actor: Actor,
    *,
    path: str = "files/receipts/tax.pdf",
    content: bytes = PDF_BYTES,
    idempotency_key: str = "file-create-1",
) -> dict[str, object]:
    return service.put_file(
        actor,
        path=path,
        content_base64=base64.b64encode(content).decode("ascii"),
        idempotency_key=idempotency_key,
        reason="Store a scanned receipt",
        create_only=True,
    )


def test_normalize_file_path_requires_files_prefix() -> None:
    assert normalize_file_path("files/photo.png") == "files/photo.png"
    with pytest.raises(ValidationError, match="under files/"):
        normalize_file_path("photo.png")
    with pytest.raises(ValidationError, match="text files belong"):
        normalize_file_path("files/notes.md")
    with pytest.raises(ValidationError, match="text files belong"):
        normalize_file_path("files/dump.json")
    with pytest.raises(ValidationError, match="inside the bundle"):
        normalize_file_path("files/../secret.pdf")


def test_documents_cannot_use_the_files_tree() -> None:
    with pytest.raises(ValidationError, match="reserved for binary"):
        normalize_document_path("files/note.md")


def test_decode_file_content_rejects_invalid_or_oversized_payloads() -> None:
    with pytest.raises(ValidationError, match="valid base64"):
        decode_file_content("!!!!")
    oversized = base64.b64encode(b"a" * (FILE_MAX_BYTES + 1)).decode("ascii")
    with pytest.raises(ValidationError, match="byte limit"):
        decode_file_content(oversized)


def test_put_get_list_and_idempotent_replay(
    service: KnowledgeGateway, actor: Actor
) -> None:
    receipt = put_pdf(service, actor)
    assert receipt["path"] == "files/receipts/tax.pdf"
    assert receipt["media_type"] == "application/pdf"
    assert receipt["bytes"] == len(PDF_BYTES)
    assert receipt["revision"].startswith("sha256:")
    assert receipt["commit"] is None
    assert receipt["backup"] == "pending"

    replay = put_pdf(service, actor)
    assert replay["idempotent_replay"] is True
    assert replay["revision"] == receipt["revision"]

    loaded = service.get_file(actor, "files/receipts/tax.pdf")
    assert loaded["revision"] == receipt["revision"]
    assert base64.b64decode(str(loaded["content_base64"])) == PDF_BYTES
    meta_only = service.get_file(
        actor, "files/receipts/tax.pdf", include_content=False
    )
    assert "content_base64" not in meta_only

    listed = service.list_files(actor)
    assert listed["count"] == 1
    assert listed["files"][0]["path"] == "files/receipts/tax.pdf"
    assert service.overview(actor)["file_count"] == 1


def test_file_update_requires_current_revision(
    service: KnowledgeGateway, actor: Actor
) -> None:
    created = put_pdf(service, actor)
    replacement = PDF_BYTES + b"\n% updated\n"

    with pytest.raises(ConflictError, match="revision conflict"):
        service.put_file(
            actor,
            path="files/receipts/tax.pdf",
            content_base64=base64.b64encode(replacement).decode("ascii"),
            idempotency_key="file-update-stale",
            reason="Overwrite with stale revision",
            expected_revision="sha256:stale",
        )

    updated = service.put_file(
        actor,
        path="files/receipts/tax.pdf",
        content_base64=base64.b64encode(replacement).decode("ascii"),
        idempotency_key="file-update-current",
        reason="Replace the receipt scan",
        expected_revision=str(created["revision"]),
    )
    assert updated["revision"] != created["revision"]
    history = service.history(actor, "files/receipts/tax.pdf")
    assert [item["operation"] for item in history["audit"]] == ["put_file", "put_file"]


def test_missing_file_is_not_found(service: KnowledgeGateway, actor: Actor) -> None:
    with pytest.raises(NotFoundError, match="does not exist"):
        service.get_file(actor, "files/missing.pdf")


def test_markdown_under_files_is_ignored_by_bundle_validation(
    service: KnowledgeGateway, actor: Actor
) -> None:
    stray = service.settings.bundle_path / "files" / "ignored.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("# not a knowledge document\n", encoding="utf-8")
    assert find_markdown_files(service.settings.bundle_path) == []
    assert service.validate_bundle(actor)["valid"] is True


def test_backup_commits_binary_artifacts(
    service: KnowledgeGateway, actor: Actor
) -> None:
    put_pdf(service, actor)
    result = service.run_backup()
    assert result["committed"] is True
    assert not service.git.has_uncommitted_changes()
    stored = (
        service.settings.bundle_path / "files" / "receipts" / "tax.pdf"
    ).read_bytes()
    assert stored == PDF_BYTES
