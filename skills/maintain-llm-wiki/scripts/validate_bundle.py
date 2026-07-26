#!/usr/bin/env python3
"""Validate a conservative OKF bundle outside the agent-kit repository."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n", re.DOTALL)
FIELD = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?:\s*(?P<value>.*))?$")
LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?P<target>[^)#?]+)(?:[?#][^)]*)?\)")
REQUIRED = {"type", "title", "description", "tags", "generated", "status"}
STATUSES = {"draft", "stable", "deprecated"}


def parse_top_level(frontmatter: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if line.startswith((" ", "\t", "-")):
            continue
        match = FIELD.match(line)
        if match:
            result[match.group("key")] = (match.group("value") or "").strip()
    return result


def check_link(bundle: Path, source: Path, target: str) -> bool:
    if "://" in target or target.startswith(("mailto:", "#")):
        return True
    candidate = bundle / target.lstrip("/") if target.startswith("/") else source.parent / target
    return candidate.resolve().is_file()


def validate(bundle: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for reserved in ("index.md", "log.md"):
        if not (bundle / reserved).is_file():
            errors.append(f"missing reserved root file: {reserved}")

    for path in sorted(bundle.rglob("*.md")):
        relative = path.relative_to(bundle)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{relative}: not valid UTF-8")
            continue

        is_reserved = relative.as_posix() in {"index.md", "log.md"}
        match = FRONTMATTER.match(text)
        if not is_reserved:
            if not match:
                errors.append(f"{relative}: missing YAML frontmatter")
            else:
                fields = parse_top_level(match.group("body"))
                missing = sorted(REQUIRED - fields.keys())
                if missing:
                    errors.append(f"{relative}: missing fields: {', '.join(missing)}")
                if fields.get("type", "") == "":
                    errors.append(f"{relative}: type must not be empty")
                status = fields.get("status")
                if status and status not in STATUSES:
                    errors.append(f"{relative}: invalid status {status!r}")

        for link in LINK.finditer(text):
            target = link.group("target").strip()
            if target and not check_link(bundle, path, target):
                warnings.append(f"{relative}: unresolved internal link {target!r}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    errors, warnings = validate(args.bundle.resolve())
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")

    if errors or (args.strict and warnings):
        return 1
    print(f"OK: validated {args.bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
