# Shared Knowledge Base Agent Kit

This repository contains only the versioned standard and distribution kit for
the skills, rules, hooks, schemas, and templates used by agents that maintain
a knowledge base. The same architecture supports both a personal wiki and a
shared project wiki used by multiple human participants and their agents.

It contains **neither the live knowledge base nor a backup of its content**.
Agents read and write through one cloud-hosted Knowledge Gateway. The gateway
owns the live OKF bundle, serializes concurrent changes, and sends backups to a
separate private backup destination.

## Start here

- [STANDARD.md](STANDARD.md) — the normative architecture and operating rules.
- [config/taxonomy.yaml](config/taxonomy.yaml) — the initial document types and folders.
- [skills/maintain-llm-wiki/SKILL.md](skills/maintain-llm-wiki/SKILL.md) — the reusable cross-agent maintenance skill.
- [rules/knowledge-base.md](rules/knowledge-base.md) — the concise agent contract.

## Install the agent kit

From a clone of this repository:

```bash
./scripts/install-agent-assets.sh
```

The installer creates links to the canonical skill for Codex, Claude Code, Cursor, and agents that support the common `~/.agents/skills` directory. It refuses to overwrite unrelated files. Repository hooks are enabled with:

```bash
./scripts/install-agent-assets.sh --install-hooks
```

Validate the repository:

```bash
./scripts/validate-repository.sh
```

## Repository layout

```text
config/          taxonomy and deployment-independent policy
skills/          canonical reusable agent skills
rules/           canonical agent rules
hooks/           repository-level deterministic hooks
scripts/         installation and validation
AGENTS.md        native entry point for Codex and compatible agents
CLAUDE.md        Claude Code adapter
.cursor/rules/   Cursor adapter
```

## Status

The standard and agent kit are usable now. The live bundle, its Git history,
snapshots, runtime configuration, and credentials must remain outside this
repository.
