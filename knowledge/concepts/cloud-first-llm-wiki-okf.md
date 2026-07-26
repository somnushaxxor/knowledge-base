---
type: Concept
title: Cloud-First LLM Wiki on OKF
description: A single live personal wiki shared by many agents, stored in OKF and backed up to GitHub.
tags:
  - knowledge-base
  - llm-wiki
  - okf
  - cloud-first
  - multi-agent
generated:
  by: human:somnus
  at: 2026-07-26T19:56:33+06:00
status: draft
sources:
  - id: karpathy-llm-wiki
    resource: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    title: LLM Wiki
    author: human:karpathy
  - id: okf-v0.2
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
    title: Open Knowledge Format v0.2 Specification
    author: process:google-cloud-platform
---

# Cloud-First LLM Wiki on OKF

## Summary

The knowledge base is one continuously available cloud service, not a collection of occasionally synchronized local clones. Every authorized agent reads and writes through the same Knowledge Gateway. The durable content is an OKF bundle of Markdown files. GitHub receives a versioned backup but is not used for live reads or multi-agent coordination.

## Details

### Three distinct layers

1. **LLM Wiki is the maintenance method.** Agents curate canonical pages, link related concepts, merge duplicates, and improve the structure over time.
2. **OKF is the storage contract.** Knowledge remains portable Markdown with explicit types, provenance, sources, and links.
3. **Knowledge Gateway is the cloud runtime.** It provides authenticated MCP tools, concurrency control, atomic writes, search, validation, audit records, and backup status.

An agent does not need its own private wiki-building agent. Codex, Claude Code, Cursor, NanoClaw, and future clients can all load the same maintenance skill and call the same gateway.

### Live write path

1. Search and hydrate the relevant pages.
2. Prepare a complete OKF document.
3. Send an idempotent mutation with the expected revision.
4. Let the gateway validate, lock, write atomically, index, and create a local Git commit.
5. Receive a durable revision and current backup state.
6. Let the backup worker push the commit to GitHub and retry independently.

This preserves read-after-write consistency across devices. A failed or delayed GitHub push affects backup freshness, not the truth visible to other agents.

### Backup model

GitHub is the primary off-site versioned backup. The target recovery-point objective is five minutes, with immediate push attempts and monitored retry. An encrypted daily snapshot stored independently protects against account loss, repository deletion, and correlated failures. Restore tests are part of the backup definition.

### Search model

Full-text, vector, and graph indexes are derived views. They can accelerate retrieval but never become the canonical store. A clean deployment must be able to rebuild all indexes from the OKF bundle.

## Relationships

- See the repository-level `STANDARD.md` for normative rules.
- See `config/taxonomy.yaml` for the initial type system.
- See `skills/maintain-llm-wiki/SKILL.md` for shared agent behavior.

