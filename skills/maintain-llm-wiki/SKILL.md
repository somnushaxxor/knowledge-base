---
name: maintain-llm-wiki
description: Maintain, search, ingest, and curate the shared cloud-first LLM Wiki through its Knowledge Gateway using the Open Knowledge Format profile. Use when an agent must remember durable information, search shared memory, turn sources or conversations into wiki pages, update or reorganize existing knowledge, resolve concurrent edits, validate OKF documents, or inspect backup status.
---

# Maintain LLM Wiki

## Overview

Use one single-user cloud Knowledge Gateway as the live authority for its
configured knowledge-base scope and OKF Markdown as the canonical
representation. Every configured client uses the same bearer token and has
access to the complete MCP tool surface. Apply the same search-before-write,
provenance, concurrency, authentication, and backup rules in every agent.

## Non-negotiable rules

- Keep the live bundle and its separate private Git backup outside the
  agent-kit repository; never use either Git repository as the live
  synchronization layer.
- Never write the live bundle directly when the gateway is configured.
- Never claim information was saved without a durable gateway receipt.
- Never use a private vector store or chat memory as the only copy.
- Preserve unknown OKF metadata and source attribution.
- Never overwrite a concurrent change with last-write-wins.
- Use only the gateway's configured scope.
- Treat mutation provenance as belonging to the fixed `single-user` actor.
- Keep secrets and unredacted credentials out of the knowledge base.

## Choose the operation

- For a question or recall request, follow **Read**.
- For “remember this,” ingestion, or durable new knowledge, follow **Create or update**.
- For restructuring, deduplication, or stale material, follow **Curate**.
- For write conflicts, follow **Resolve a conflict**.
- For recovery assurance, follow **Check backup**.

Read [references/okf-profile.md](references/okf-profile.md) before creating or structurally changing a document. Read [references/write-protocol.md](references/write-protocol.md) before a mutation or conflict resolution.

## Read

1. Call `kb_search` with the user's terms and likely synonyms.
2. Hydrate promising hits with `kb_get`; do not answer from snippets alone.
3. Follow internal links when they materially affect the answer.
4. Distinguish stored knowledge from inference.
5. Cite the relevant knowledge paths or original sources when useful.

## Create or update

1. Decide whether the information is durable, reusable, and safe to store. Do not persist transient chat or secrets.
2. Search for an existing canonical page before creating one.
3. Select a type from the gateway-configured deployment taxonomy. Do not infer
   or invent a new type.
4. Hydrate the target page and record its revision when updating.
5. Merge new information into a coherent page rather than appending a session transcript.
6. Include provenance and sources. When using
   `assets/document-template.md`, replace its type and section placeholders
   with values required by the deployment taxonomy.
7. Call `kb_validate`.
8. Call `kb_upsert` with an idempotency key and `expected_revision`, or an explicit create-only condition.
9. Keep the returned path, revision, and backup state in the working context.
10. Report success only after receiving the receipt. If backup is pending, distinguish “saved live” from “backed up.”

## Curate

1. Find duplicates, overloaded pages, broken relationships, stale claims, and orphaned captures.
2. Read all affected pages before planning a mutation.
3. Preserve useful history and sources.
4. Prefer semantic merges, explicit redirects or archive actions, and repaired links.
5. Apply small reviewable mutations with revision checks.
6. Record significant structural changes in `log.md`.

## Resolve a conflict

1. Do not retry the old payload blindly.
2. Fetch the current document and revision.
3. Compare the current document, the intended change, and the previously read revision.
4. Merge meaning, sources, and links; surface a genuine semantic contradiction to the user.
5. Validate and retry with the new revision and a new idempotency key.

## Check backup

Call `kb_backup_status`. Report the configured backup interval, dirty state,
last backup commit, last pushed commit, backup lag, and any push failure. Never
infer backup health merely because a live write succeeded.

## Gateway unavailable

Do not silently create an alternative authority. Keep the proposed content in the current conversation, state that it is not persisted, and retry when the gateway is available. Use a local queue only if an explicitly configured queue preserves idempotency and visibly reports pending state.
