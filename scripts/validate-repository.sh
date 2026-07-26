#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -e "$repo_root/knowledge" ]]; then
  echo "ERROR: knowledge/ must not exist in the agent-kit repository" >&2
  exit 1
fi

python3 "$repo_root/scripts/validate-skill.py" \
  "$repo_root/skills/maintain-llm-wiki"

echo "OK: repository validation passed"
