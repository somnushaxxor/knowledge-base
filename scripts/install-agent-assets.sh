#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_root=""
taxonomy_source=""
assets_only=false
dry_run=false

usage() {
  cat <<'EOF'
Usage: install-agent-assets.sh --target PATH --taxonomy PATH [--assets-only] [--dry-run]

Install the knowledge-base runtime assets into one project that already has a
configured Knowledge Gateway connection.

Options:
  --target PATH   Existing target project directory (required)
  --taxonomy PATH Install this deployment taxonomy (required)
  --assets-only   Install .agents assets but not root vendor adapters
  --dry-run       Show what would be installed without writing files
  -h, --help      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --target requires a path" >&2
        usage >&2
        exit 2
      fi
      target_root="$2"
      shift
      ;;
    --taxonomy)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --taxonomy requires a path" >&2
        usage >&2
        exit 2
      fi
      taxonomy_source="$2"
      shift
      ;;
    --assets-only) assets_only=true ;;
    --dry-run) dry_run=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "$target_root" ]]; then
  echo "ERROR: --target is required" >&2
  usage >&2
  exit 2
fi

if [[ -z "$taxonomy_source" ]]; then
  echo "ERROR: --taxonomy is required; provide a deployment model" >&2
  usage >&2
  exit 2
fi

if [[ ! -d "$target_root" ]]; then
  echo "ERROR: target is not an existing directory: $target_root" >&2
  exit 1
fi

if [[ ! -f "$taxonomy_source" ]]; then
  echo "ERROR: taxonomy is not a file: $taxonomy_source" >&2
  exit 1
fi

target_root="$(cd "$target_root" && pwd)"
taxonomy_source="$(
  cd "$(dirname "$taxonomy_source")"
  printf '%s/%s\n' "$PWD" "$(basename "$taxonomy_source")"
)"
taxonomy_destination="$target_root/.agents/config/taxonomy.yaml"

if [[ "$target_root" == "$repo_root" ]]; then
  echo "ERROR: refusing to activate runtime assets in the agent-kit source repository" >&2
  exit 1
fi

sources=(
  "$repo_root/skills/maintain-llm-wiki/SKILL.md"
  "$repo_root/skills/maintain-llm-wiki/agents/openai.yaml"
  "$repo_root/skills/maintain-llm-wiki/assets/document-template.md"
  "$repo_root/skills/maintain-llm-wiki/references/okf-profile.md"
  "$repo_root/skills/maintain-llm-wiki/references/write-protocol.md"
  "$repo_root/skills/maintain-llm-wiki/scripts/validate_bundle.py"
  "$repo_root/rules/knowledge-base.md"
)
destinations=(
  "$target_root/.agents/skills/maintain-llm-wiki/SKILL.md"
  "$target_root/.agents/skills/maintain-llm-wiki/agents/openai.yaml"
  "$target_root/.agents/skills/maintain-llm-wiki/assets/document-template.md"
  "$target_root/.agents/skills/maintain-llm-wiki/references/okf-profile.md"
  "$target_root/.agents/skills/maintain-llm-wiki/references/write-protocol.md"
  "$target_root/.agents/skills/maintain-llm-wiki/scripts/validate_bundle.py"
  "$target_root/.agents/rules/knowledge-base.md"
)

if ! $assets_only; then
  sources+=(
    "$repo_root/templates/runtime/AGENTS.md"
    "$repo_root/templates/runtime/CLAUDE.md"
    "$repo_root/templates/runtime/.cursor/rules/knowledge-base.mdc"
    "$repo_root/templates/runtime/.github/copilot-instructions.md"
  )
  destinations+=(
    "$target_root/AGENTS.md"
    "$target_root/CLAUDE.md"
    "$target_root/.cursor/rules/knowledge-base.mdc"
    "$target_root/.github/copilot-instructions.md"
  )
fi

same_item() {
  local source="$1"
  local destination="$2"

  [[ -f "$destination" ]] && cmp -s "$source" "$destination"
}

# Preflight every destination before writing anything, so a conflict cannot
# leave a partially installed project.
conflicts=0
for index in "${!sources[@]}"; do
  source="${sources[$index]}"
  destination="${destinations[$index]}"

  if [[ -e "$destination" || -L "$destination" ]]; then
    if same_item "$source" "$destination"; then
      continue
    fi
    echo "REFUSED: $destination already exists and differs from the runtime kit" >&2
    conflicts=1
  fi
done

if [[ "$conflicts" -ne 0 ]]; then
  echo "ERROR: no files were installed; use --assets-only and merge adapter templates manually" >&2
  exit 1
fi

for index in "${!sources[@]}"; do
  source="${sources[$index]}"
  destination="${destinations[$index]}"

  if [[ -e "$destination" || -L "$destination" ]]; then
    echo "OK: $destination"
    continue
  fi

  if $dry_run; then
    echo "WOULD COPY: $source -> $destination"
    continue
  fi

  mkdir -p "$(dirname "$destination")"
  cp -R "$source" "$destination"
  echo "INSTALLED: $destination"
done

# The taxonomy is deployment-owned configuration. Create it once, then
# preserve it across kit updates.
if [[ -e "$taxonomy_destination" || -L "$taxonomy_destination" ]]; then
  echo "PRESERVED: $taxonomy_destination"
elif $dry_run; then
  echo "WOULD COPY: $taxonomy_source -> $taxonomy_destination"
else
  mkdir -p "$(dirname "$taxonomy_destination")"
  cp "$taxonomy_source" "$taxonomy_destination"
  echo "INSTALLED: $taxonomy_destination"
fi

if $assets_only; then
  echo "NOTE: merge templates/runtime adapters into the target project to activate the installed assets"
else
  echo "OK: runtime knowledge-base instructions are active in $target_root"
fi
echo "NOTE: configure the gateway's KB_TAXONOMY_PATH to use $taxonomy_destination"
