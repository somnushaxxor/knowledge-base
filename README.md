# Shared Knowledge Base Agent Kit

This repository contains the versioned standard, agent distribution kit, and
buildable reference implementation of the Knowledge Gateway used by agents
that maintain a knowledge base. The same architecture supports both a personal
wiki and a shared project wiki used by multiple human participants and their
agents.

It contains **neither the live knowledge base nor a backup of its content**.
Agents read and write through one cloud-hosted Knowledge Gateway. The gateway
owns the live OKF bundle, serializes concurrent changes, and sends backups to a
separate private backup destination.

This source checkout is deliberately **not** an activated knowledge-base
project. Its root `AGENTS.md` and `CLAUDE.md` govern development of the kit
only. Active runtime adapters live under `templates/runtime/` and are installed
into a connected target project.

## Start here

- [STANDARD.md](STANDARD.md) — the normative architecture and operating rules.
- [gateway/README.md](gateway/README.md) — build, test, configure, and run the FastMCP gateway.
- [skills/maintain-llm-wiki/SKILL.md](skills/maintain-llm-wiki/SKILL.md) — the reusable cross-agent maintenance skill.
- [rules/knowledge-base.md](rules/knowledge-base.md) — the concise agent contract.

## Activate the kit in a connected project

First configure the target agents with access to the deployed Knowledge Gateway
and verify that its MCP tools are available. Then, from a clone of this
repository, install the runtime assets into that specific project:

```bash
./scripts/install-agent-assets.sh \
  --target /path/to/connected-project \
  --taxonomy /path/to/deployment-taxonomy.yaml
```

The installer copies the canonical rule and skill into the target project's
`.agents/` directory, installs the explicitly selected taxonomy as
deployment-owned configuration, and installs thin adapters for Codex, Claude
Code, Cursor, and GitHub Copilot. It never writes to user-level skill
directories, so the workflow is scoped to the selected project. It also
refuses to install into this source repository or overwrite a differing
managed file.

The resulting `.agents/config/taxonomy.yaml` belongs to the target knowledge
base. Later kit updates preserve it.
Configure the gateway's `KB_TAXONOMY_PATH` to point to this deployment-owned
copy. The kit contains no default or example taxonomy; the configuration
contract and migration rules are defined in [STANDARD.md](STANDARD.md).

If the target already has one or more agent instruction files, install only the
shared assets:

```bash
./scripts/install-agent-assets.sh \
  --target /path/to/connected-project \
  --taxonomy /path/to/that-base-taxonomy.yaml \
  --assets-only
```

Then merge the relevant files from `templates/runtime/` into the target's
existing adapters. Do not copy credentials or gateway connection settings into
the repository.

Preview either operation with `--dry-run`.

## Develop the agent kit

Validate the repository:

```bash
./scripts/validate-repository.sh
```

Enable its optional local pre-commit validation hook with:

```bash
git config core.hooksPath hooks
```

## Repository layout

```text
gateway/         buildable FastMCP Knowledge Gateway
skills/          canonical reusable agent skills
rules/           canonical agent rules
templates/       active adapters copied only into connected projects
hooks/           repository-level deterministic hooks
scripts/         installation and validation
AGENTS.md        neutral instructions for developing this source repository
CLAUDE.md        neutral Claude Code source-repository adapter
```

## Status

The standard and agent kit are usable now. The gateway is a tested reference
alpha; its README lists the remaining production-hardening work. The live
bundle, its Git history, snapshots, runtime configuration, and credentials must
remain outside this repository.
