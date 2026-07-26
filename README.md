# Personal Knowledge Base Standard

This repository is both:

1. the versioned, off-site backup of a cloud-first personal knowledge base; and
2. the distribution kit for the skills, rules, hooks, schemas, and templates used by every agent that maintains it.

It is **not** the live coordination layer. Agents read and write through one cloud-hosted Knowledge Gateway. The gateway owns the live OKF bundle, serializes concurrent changes, commits accepted writes locally, and pushes those commits to this GitHub repository as a backup.

## Start here

- [STANDARD.md](STANDARD.md) — the normative architecture and operating rules.
- [knowledge/concepts/cloud-first-llm-wiki-okf.md](knowledge/concepts/cloud-first-llm-wiki-okf.md) — the concept in OKF form.
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
knowledge/       OKF bundle and backup payload
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

The standard and agent kit are usable now. The Knowledge Gateway described in the standard is intentionally a small custom service built on mature components; its production implementation and deployment configuration are the next deliverable.

