# Canonical Knowledge Base Rules

1. Treat the cloud Knowledge Gateway as the only live authority.
2. Keep live knowledge and its backups outside the agent-kit repository; use a separate private backup destination.
3. Before the first write in a session, call `kb_overview` and follow its `usage` and `taxonomy`.
4. Search and read before creating or updating a page.
5. Store durable knowledge in OKF Markdown; do not store the only copy in a vector database, chat history, or private agent memory. Store non-text artifacts under reserved `files/` through the gateway; do not put textual knowledge there.
6. Use only types from `kb_overview` taxonomy. Do not infer or invent a new document type during ordinary capture.
7. Preserve unknown OKF metadata and source attribution.
8. Use optimistic concurrency. On conflict, re-read, merge semantically, and retry.
9. Never use last-write-wins for concurrent edits.
10. Never claim a write succeeded without a gateway receipt.
11. Never commit tokens, keys, passwords, private environment files, or unredacted secrets.
12. Prefer updating a canonical concept over creating a near-duplicate.
13. Keep semantic, vector, graph, and full-text indexes rebuildable from the OKF bundle.
14. Use only the gateway's configured scope. The single bearer token grants its owner access to the complete MCP tool surface.
15. Attribute every accepted change to the fixed `single-user` actor.
