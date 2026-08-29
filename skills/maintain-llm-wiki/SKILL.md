---
name: maintain-llm-wiki
description: Maintain, search, ingest, and curate the shared cloud-first LLM Wiki through its Knowledge Gateway. Use when an agent must remember durable information, search shared memory, turn sources or conversations into wiki pages, update or reorganize existing knowledge, or inspect backup status.
---

# Maintain LLM Wiki

This skill is a **trigger**. The Knowledge Gateway MCP is self-describing.

1. Call `kb_overview` with the configured scope.
2. Follow `usage` and `taxonomy` from that result for every read and write.
3. Do not invent document types. Do not write the live bundle or Git backup.
4. Report success only after a gateway write receipt.

If the gateway is unavailable: say so, keep the draft in-chat, do not create another authority.

Human-readable copies of the same contract (optional): [okf-profile.md](references/okf-profile.md), [write-protocol.md](references/write-protocol.md).
