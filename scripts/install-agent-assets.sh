#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_skill="$repo_root/skills/maintain-llm-wiki"
install_hooks=false
dry_run=false

usage() {
  echo "Usage: $0 [--install-hooks] [--dry-run]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-hooks) install_hooks=true ;;
    --dry-run) dry_run=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

install_link() {
  local target="$1"
  local parent
  parent="$(dirname "$target")"

  if [[ -L "$target" ]] && [[ "$(readlink "$target")" == "$source_skill" ]]; then
    echo "OK: $target"
    return
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    echo "REFUSED: $target already exists and is not the canonical link" >&2
    return 1
  fi

  if $dry_run; then
    echo "WOULD LINK: $target -> $source_skill"
  else
    mkdir -p "$parent"
    ln -s "$source_skill" "$target"
    echo "LINKED: $target -> $source_skill"
  fi
}

install_link "$HOME/.codex/skills/maintain-llm-wiki"
install_link "$HOME/.claude/skills/maintain-llm-wiki"
install_link "$HOME/.cursor/skills/maintain-llm-wiki"
install_link "$HOME/.agents/skills/maintain-llm-wiki"

if $install_hooks; then
  if $dry_run; then
    echo "WOULD CONFIGURE: git core.hooksPath hooks"
  else
    git -C "$repo_root" config core.hooksPath hooks
    echo "CONFIGURED: git core.hooksPath hooks"
  fi
fi

