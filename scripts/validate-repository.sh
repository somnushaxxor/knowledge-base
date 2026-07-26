#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -e "$repo_root/knowledge" ]]; then
  echo "ERROR: knowledge/ must not exist in the agent-kit repository" >&2
  exit 1
fi

required_runtime_files=(
  "templates/runtime/AGENTS.md"
  "templates/runtime/CLAUDE.md"
  "templates/runtime/.cursor/rules/knowledge-base.mdc"
  "templates/runtime/.github/copilot-instructions.md"
)

for relative_path in "${required_runtime_files[@]}"; do
  if [[ ! -f "$repo_root/$relative_path" ]]; then
    echo "ERROR: runtime adapter is missing: $relative_path" >&2
    exit 1
  fi
done

neutral_adapters=(
  "AGENTS.md"
  "CLAUDE.md"
)

for relative_path in "${neutral_adapters[@]}"; do
  if ! grep -qi "not .*connected knowledge base" "$repo_root/$relative_path"; then
    echo "ERROR: source-repository adapter is not explicitly neutral: $relative_path" >&2
    exit 1
  fi
done

if grep -Eq '\.codex/skills|\.claude/skills|\.cursor/skills' \
  "$repo_root/scripts/install-agent-assets.sh"; then
  echo "ERROR: installer must not activate the runtime skill globally" >&2
  exit 1
fi

bash -n "$repo_root/scripts/install-agent-assets.sh"

if [[ -e "$repo_root/config/taxonomy.yaml" ]]; then
  echo "ERROR: the kit must not contain a default config/taxonomy.yaml" >&2
  exit 1
fi

if [[ -d "$repo_root/examples/taxonomies" ]]; then
  echo "ERROR: the kit must not contain example taxonomies" >&2
  exit 1
fi

if ! grep -q -- "--taxonomy is required" \
  "$repo_root/scripts/install-agent-assets.sh"; then
  echo "ERROR: installer must require explicit taxonomy selection" >&2
  exit 1
fi

if grep -Eq '^COPY[[:space:]].*taxonomy.*\.ya?ml' \
  "$repo_root/gateway/Dockerfile"; then
  echo "ERROR: gateway image must not embed an implicit deployment taxonomy" >&2
  exit 1
fi

required_gateway_files=(
  ".dockerignore"
  "gateway/pyproject.toml"
  "gateway/Dockerfile"
  "gateway/.env.example"
  "gateway/src/knowledge_gateway/server.py"
  "gateway/src/knowledge_gateway/service.py"
  "gateway/tests/test_server.py"
)

for relative_path in "${required_gateway_files[@]}"; do
  if [[ ! -f "$repo_root/$relative_path" ]]; then
    echo "ERROR: gateway artifact is missing: $relative_path" >&2
    exit 1
  fi
done

python3 -m compileall -q "$repo_root/gateway/src"

python3 "$repo_root/scripts/validate-skill.py" \
  "$repo_root/skills/maintain-llm-wiki"

echo "OK: repository validation passed"
