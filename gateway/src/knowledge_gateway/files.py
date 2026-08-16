"""Reserved bundle directory for non-text artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
from pathlib import Path, PurePosixPath

from .errors import ValidationError

FILES_FOLDER = "files"
FILE_MAX_BYTES = 10 * 1024 * 1024

# Textual knowledge belongs in OKF Markdown, not in files/.
TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".rst",
        ".csv",
        ".tsv",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".ts",
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".toml",
        ".ini",
        ".cfg",
        ".log",
        ".rtf",
    }
)


def normalize_file_path(value: str) -> str:
    """Return a safe bundle-relative path under files/."""
    if not value or "\\" in value:
        raise ValidationError("path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValidationError("path must stay inside the bundle")
    if any(part.startswith(".") for part in path.parts):
        raise ValidationError("hidden paths are reserved by the gateway")
    if path.parts[0] != FILES_FOLDER:
        raise ValidationError(f"binary artifacts must be stored under {FILES_FOLDER}/")
    if len(path.parts) < 2:
        raise ValidationError(f"path must include a filename under {FILES_FOLDER}/")
    suffix = path.suffix.lower()
    if not suffix:
        raise ValidationError("artifact path must include a file extension")
    if suffix in TEXT_EXTENSIONS:
        raise ValidationError(
            "text files belong in OKF Markdown documents, not files/"
        )
    return path.as_posix()


def decode_file_content(content_base64: str) -> bytes:
    """Decode a base64 payload and enforce the artifact size limit."""
    if not isinstance(content_base64, str) or not content_base64.strip():
        raise ValidationError("content_base64 must be a non-empty base64 string")
    compact = "".join(content_base64.split())
    try:
        data = base64.b64decode(compact, validate=True)
    except binascii.Error as exc:
        raise ValidationError("content_base64 must be valid base64") from exc
    if not data:
        raise ValidationError("file content must not be empty")
    if len(data) > FILE_MAX_BYTES:
        raise ValidationError(
            f"file exceeds the {FILE_MAX_BYTES} byte limit"
        )
    return data


def media_type_for(path: str) -> str:
    guessed, _encoding = mimetypes.guess_type(path)
    if guessed and not guessed.startswith("text/"):
        return guessed
    return "application/octet-stream"


def revision_for_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def find_artifact_files(bundle_path: Path) -> list[Path]:
    """Return files under the reserved artifacts directory."""
    root = bundle_path / FILES_FOLDER
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and not any(part.startswith(".") for part in path.parts)
    )
