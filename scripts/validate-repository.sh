#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$repo_root/skills/maintain-llm-wiki/scripts/validate_bundle.py" \
  "$repo_root/knowledge"

python3 "$repo_root/scripts/validate-skill.py" \
  "$repo_root/skills/maintain-llm-wiki"

echo "OK: repository validation passed"
