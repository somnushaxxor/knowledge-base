"""OKF Markdown parsing and profile validation."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import yaml

from .errors import ConfigurationError, ValidationError
from .files import FILES_FOLDER
from .models import ParsedDocument, TaxonomyType

REQUIRED_METADATA = ("type", "title", "description", "status", "tags", "generated")
FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)

# Returned by kb_overview so agents can write without a copied skill protocol.
GATEWAY_USAGE: dict[str, object] = {
    "read": [
        "kb_search, then kb_get promising hits; do not answer from snippets alone",
        "Follow bundle-absolute links that change the answer",
        "Distinguish stored facts from inference",
    ],
    "write": [
        "Search for an existing canonical page; prefer merge over create",
        "Use only types from this overview's taxonomy; never invent a type",
        "Write a coherent durable page, not a chat transcript",
        "Updates: kb_get, keep revision, replace the whole document",
        "kb_upsert with a unique idempotency_key; invalid documents are rejected",
        "Creates: create_only=true. Updates: expected_revision from kb_get",
        "Never reuse an idempotency_key for a different request",
        "On conflict: kb_get current, semantic merge, new key — never last-write-wins",
        "Report success only after a write receipt; backup pending means live-ok, Git lag",
    ],
    "document": {
        "format": "UTF-8 Markdown with YAML frontmatter",
        "required_metadata": list(REQUIRED_METADATA),
        "recommended_status": ["draft", "stable", "deprecated"],
        "generated": "boolean, or {by, at} with non-empty strings",
        "links": "internal links must be bundle-absolute and start with /",
        "index": "index.md for navigation",
        "log": "log.md for notable structural changes, newest first",
        "files": "non-text artifacts via kb_put_file under files/; not full-text searchable",
        "sections": "taxonomy.sections are recommended H2 headings, not hard-rejected",
    },
    "never": [
        "write the live bundle or Git backup directly",
        "claim a save without a gateway receipt",
        "store secrets or unredacted credentials",
        "use last-write-wins",
    ],
}


def _read_taxonomy_yaml(path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"taxonomy file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"taxonomy is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        raise ConfigurationError("taxonomy must contain a types list")
    return raw


def load_taxonomy_bundle(
    path: Path,
) -> tuple[dict[str, TaxonomyType], dict[str, object]]:
    raw = _read_taxonomy_yaml(path)
    policy = raw.get("policy")
    if not isinstance(policy, dict):
        policy = {}
    result: dict[str, TaxonomyType] = {}
    for item in raw["types"]:
        if not isinstance(item, dict):
            raise ConfigurationError("each taxonomy type must be an object")
        try:
            filename = item.get("filename")
            if filename is not None:
                filename = str(filename)
                if not filename or PurePosixPath(filename).name != filename:
                    raise ConfigurationError(
                        "taxonomy filename must be a non-empty basename"
                    )
            tags_required = item.get("tags_required", True)
            if not isinstance(tags_required, bool):
                raise ConfigurationError("taxonomy tags_required must be a boolean")
            purpose = item.get("purpose", "")
            if purpose is None:
                purpose = ""
            if not isinstance(purpose, str):
                raise ConfigurationError("taxonomy purpose must be a string")
            entry = TaxonomyType(
                name=str(item["type"]),
                folder=str(item["folder"]).strip("/"),
                sections=tuple(str(section) for section in item.get("sections", [])),
                filename=filename,
                tags_required=tags_required,
                purpose=purpose,
            )
        except KeyError as exc:
            raise ConfigurationError(f"taxonomy type lacks {exc.args[0]}") from exc
        result[entry.name] = entry
    return result, policy


def load_taxonomy(path: Path) -> dict[str, TaxonomyType]:
    types, _policy = load_taxonomy_bundle(path)
    return types


def normalize_document_path(value: str) -> str:
    """Return a safe bundle-relative Markdown path."""
    if not value or "\\" in value:
        raise ValidationError("path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValidationError("path must stay inside the bundle")
    if any(part.startswith(".") for part in path.parts):
        raise ValidationError("hidden paths are reserved by the gateway")
    if path.parts[0] == FILES_FOLDER:
        raise ValidationError("files/ is reserved for binary artifacts")
    if path.suffix.lower() != ".md":
        raise ValidationError("knowledge documents must use the .md extension")
    return path.as_posix()


def parse_document(content: str) -> ParsedDocument:
    match = FRONTMATTER.match(content)
    if not match:
        raise ValidationError("document must begin with YAML frontmatter")
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValidationError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValidationError("frontmatter must be a YAML mapping")
    return ParsedDocument(metadata=metadata, body=content[match.end() :], raw=content)


def validate_document(
    path: str,
    content: str,
    taxonomy: dict[str, TaxonomyType],
) -> ParsedDocument:
    normalized_path = normalize_document_path(path)
    issues: list[dict[str, str]] = []
    try:
        document = parse_document(content)
    except ValidationError as exc:
        raise ValidationError(str(exc), [{"path": normalized_path, "message": str(exc)}]) from exc

    document_type = document.metadata.get("type")
    taxonomy_type = taxonomy.get(str(document_type))
    required_metadata = REQUIRED_METADATA
    if taxonomy_type is not None and not taxonomy_type.tags_required:
        required_metadata = tuple(key for key in REQUIRED_METADATA if key != "tags")
    for key in required_metadata:
        if key not in document.metadata:
            issues.append({"path": normalized_path, "message": f"missing metadata: {key}"})

    if taxonomy_type is None:
        issues.append(
            {"path": normalized_path, "message": f"unknown document type: {document_type}"}
        )
    else:
        top_folder = PurePosixPath(normalized_path).parts[0]
        if taxonomy_type.folder != "**" and top_folder != taxonomy_type.folder:
            issues.append(
                {
                    "path": normalized_path,
                    "message": (
                        f"type {taxonomy_type.name} must be stored under "
                        f"{taxonomy_type.folder}/"
                    ),
                }
            )
        if (
            taxonomy_type.filename is not None
            and PurePosixPath(normalized_path).name != taxonomy_type.filename
        ):
            issues.append(
                {
                    "path": normalized_path,
                    "message": (
                        f"type {taxonomy_type.name} must use filename "
                        f"{taxonomy_type.filename}"
                    ),
                }
            )
    title = document.metadata.get("title")
    description = document.metadata.get("description")
    tags = document.metadata.get("tags")
    generated = document.metadata.get("generated")
    if "title" in document.metadata and (not isinstance(title, str) or not title.strip()):
        issues.append({"path": normalized_path, "message": "title must be a non-empty string"})
    if "description" in document.metadata and (
        not isinstance(description, str) or not description.strip()
    ):
        issues.append(
            {"path": normalized_path, "message": "description must be a non-empty string"}
        )
    if "tags" in document.metadata and (
        not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)
    ):
        issues.append({"path": normalized_path, "message": "tags must be a list of strings"})
    if "generated" in document.metadata:
        # Accept OKF boolean or the object form used by my-memory: {by, at}.
        if isinstance(generated, bool):
            pass
        elif (
            isinstance(generated, dict)
            and isinstance(generated.get("by"), str)
            and generated["by"].strip()
            and isinstance(generated.get("at"), str)
            and generated["at"].strip()
        ):
            pass
        else:
            issues.append(
                {
                    "path": normalized_path,
                    "message": "generated must be a boolean or {by, at} object",
                }
            )

    for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.body):
        if link.startswith(("#", "http://", "https://", "mailto:")):
            continue
        if not link.startswith("/"):
            issues.append(
                {
                    "path": normalized_path,
                    "message": f"internal link must be bundle-absolute: {link}",
                }
            )

    if issues:
        raise ValidationError("document does not satisfy the OKF profile", issues)
    return document


def find_markdown_files(bundle_path: Path) -> list[Path]:
    """Return knowledge documents while excluding gateway and Git internals."""
    if not bundle_path.exists():
        return []
    matches: list[Path] = []
    for path in bundle_path.rglob("*.md"):
        relative = path.relative_to(bundle_path)
        if ".git" in relative.parts or relative.parts[:1] == (FILES_FOLDER,):
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        matches.append(path)
    return sorted(matches)
