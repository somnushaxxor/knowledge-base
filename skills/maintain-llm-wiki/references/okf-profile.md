# OKF Profile

Canonical live copy for agents: `kb_overview` (`usage` + `taxonomy`).
This file is a human-readable duplicate.

The canonical bundle follows Open Knowledge Format v0.2 with additional local constraints.

## Bundle

- Store the live bundle at the gateway's configured runtime path, outside the
  agent-kit repository.
- Store versioned backups in a separate private backup destination.
- Reserve root `index.md` for navigation and `log.md` for notable changes.
- Reserve top-level `files/` for non-text artifacts (PDF, images, other binaries).
- Use UTF-8 Markdown.
- Use bundle-absolute internal Markdown links such as
  `/<configured-folder>/<document-slug>.md` or `/files/<artifact>`.
- Keep non-knowledge configuration outside the bundle.

## Required document metadata

Every knowledge document has YAML frontmatter with:

```yaml
---
type: ConfiguredType
title: Readable title
description: One-sentence scope.
tags: [example]
generated:
  by: agent:identifier
  at: 2026-07-26T19:56:33+06:00
status: draft
---
```

Use only document types declared in the taxonomy configured for the active
gateway deployment. Do not infer a type from repository documentation. Use
`draft`, `stable`, or `deprecated` for `status`.

Use actor values that identify the producer, for example:

- `human:somnus`
- `agent:codex/instance-id`
- `process:import/source-id`

## Sources

Add `sources` when a page contains claims from external material:

```yaml
sources:
  - id: stable-local-id
    resource: https://example.com/source
    title: Source title
    author: human:author-id
```

Each source requires `resource`. Preserve existing source fields and source identifiers. Do not mark claims verified merely because an LLM generated them.

## Body

- Start with one H1 matching the title.
- Use the sections expected by the selected taxonomy type.
- Write a coherent durable page, not a chat transcript.
- Link relevant canonical pages.
- Prefer one stable subject per page.
- Preserve meaningful contrary evidence and uncertainty.

## Editing

- Preserve unknown valid OKF fields.
- Update `generated` only when generation provenance truly changes; use verification or history for later review.
- Use `stale_after` only when the material has a meaningful review horizon.
- Archive obsolete material instead of destroying recoverable history.
