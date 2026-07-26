#!/usr/bin/env python3
"""Validate the portable skill package without third-party dependencies."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    skill = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    skill_file = skill / "SKILL.md"
    agent_file = skill / "agents" / "openai.yaml"

    if not skill_file.is_file():
        print("ERROR: SKILL.md is missing")
        return 1
    if not agent_file.is_file():
        print("ERROR: agents/openai.yaml is missing")
        return 1

    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(?P<header>.*?)\n---\n", text, re.DOTALL)
    if not match:
        print("ERROR: SKILL.md frontmatter is missing or malformed")
        return 1

    pairs: dict[str, str] = {}
    for line in match.group("header").splitlines():
        if ":" not in line:
            print(f"ERROR: malformed frontmatter line: {line}")
            return 1
        key, value = line.split(":", 1)
        pairs[key.strip()] = value.strip()

    if set(pairs) != {"name", "description"}:
        print("ERROR: SKILL.md frontmatter must contain only name and description")
        return 1
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", pairs["name"]):
        print("ERROR: invalid skill name")
        return 1
    if not pairs["description"] or len(pairs["description"]) > 1024:
        print("ERROR: invalid skill description")
        return 1

    agent_text = agent_file.read_text(encoding="utf-8")
    required_fragments = (
        'display_name: "',
        'short_description: "',
        'default_prompt: "',
        f"${pairs['name']}",
    )
    missing = [fragment for fragment in required_fragments if fragment not in agent_text]
    if missing:
        print(f"ERROR: agents/openai.yaml is incomplete: {', '.join(missing)}")
        return 1

    print(f"OK: validated skill {pairs['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

