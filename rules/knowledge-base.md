# Canonical Knowledge Base Rules

1. Treat the cloud Knowledge Gateway as the only live authority.
2. Keep live knowledge and its backups outside the agent-kit repository; use a separate private backup destination.
3. Search and read before creating or updating a page.
4. Store durable knowledge in OKF Markdown; do not store the only copy in a vector database, chat history, or private agent memory.
5. Use the gateway-configured deployment taxonomy. Do not infer or invent a
   new document type during ordinary capture.
6. Preserve unknown OKF metadata and source attribution.
7. Use optimistic concurrency. On conflict, re-read, merge semantically, and retry.
8. Never use last-write-wins for concurrent edits.
9. Never claim a write succeeded without a gateway receipt.
10. Never commit tokens, keys, passwords, private environment files, or unredacted secrets.
11. Prefer updating a canonical concept over creating a near-duplicate.
12. Keep semantic, vector, graph, and full-text indexes rebuildable from the OKF bundle.
13. Use only the gateway's configured scope. The single bearer token grants its
    owner access to the complete MCP tool surface.
14. Attribute every accepted change to the fixed `single-user` actor.
