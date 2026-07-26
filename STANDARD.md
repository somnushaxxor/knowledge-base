# Cloud-First LLM Wiki Standard

Status: **Draft v0.1**

## 1. Purpose

This standard defines one personal knowledge base that:

- is current across computers, phones, and cloud agents;
- can be read and changed concurrently by multiple agents;
- remains portable, human-readable, and usable without a vendor;
- distributes the same maintenance behavior to Codex, Claude Code, Cursor, NanoClaw, and future agents;
- has a versioned GitHub backup and an independent disaster-recovery backup.

## 2. Chosen stack

| Layer | Choice | Responsibility |
|---|---|---|
| Knowledge method | [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | Maintain a small, linked, evolving wiki rather than an append-only transcript |
| Canonical format | [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) | Markdown, YAML frontmatter, sources, provenance, links, and reserved indexes |
| Live authority | Custom Knowledge Gateway on one cloud host | Authenticate agents, search, read, serialize writes, validate, and return durable revisions |
| Agent protocol | MCP over Streamable HTTP | Give different agents one standard remote tool surface |
| Lexical search | SQLite FTS5 or QMD-compatible local index | Fast full-text retrieval over the live OKF bundle |
| Semantic search | Optional derived vector index | Improve recall; always rebuildable from OKF |
| Backup | Local Git history pushed to this private GitHub repository | Off-site, reviewable, versioned recovery copy |
| Disaster recovery | Encrypted provider snapshot/object-store archive | Recover when both the live disk and Git remote are unavailable |
| Agent behavior | Canonical skill, rules, and hooks in this repository | Make all agents follow the same workflow |

The gateway is custom because no sufficiently established project currently combines strict OKF storage, remote MCP, authenticated multi-writer concurrency, and explicit backup semantics. It should be small and boring: use mature libraries, keep OKF as the source of truth, and avoid inventing a database-specific knowledge format.

## 3. Authority and consistency

There is exactly one live authority: the persistent OKF bundle mounted by the Knowledge Gateway.

Agents must not:

- use GitHub as the source for live reads;
- edit the live files through SSH, Drive sync, or a second server;
- maintain a private canonical memory that is invisible to other agents;
- claim that a fact was saved when the gateway did not return a write receipt.

All successful gateway writes are visible to subsequent reads immediately. A phone agent and a desktop agent therefore see the same accepted revision even if GitHub backup is temporarily delayed.

## 4. Gateway contract

The gateway exposes a small MCP tool surface:

| Tool | Purpose |
|---|---|
| `kb_overview` | Read bundle identity, taxonomy, health, and latest revision |
| `kb_search` | Search metadata and content; optionally combine lexical and semantic results |
| `kb_get` | Read one hydrated document and its revision |
| `kb_upsert` | Create or replace one document using optimistic concurrency |
| `kb_archive` | Move a document to the archive without destroying history |
| `kb_history` | Inspect revisions, provenance, and change history |
| `kb_validate` | Validate a proposed document or the whole bundle |
| `kb_backup_status` | Report GitHub and snapshot recovery points and backup lag |

Every mutation requires:

- a per-agent identity derived from its bearer token;
- an idempotency key;
- `expected_revision` for an update, or an explicit create-only condition;
- a complete OKF document;
- an audit reason or source reference.

The gateway performs validation, obtains a per-document lock, checks the expected revision, writes atomically, updates the search projection, and creates a local Git commit. It then returns:

```json
{
  "path": "concepts/example.md",
  "revision": "sha256:...",
  "commit": "...",
  "backup": "synced|pending",
  "accepted_at": "RFC3339 timestamp"
}
```

On a conflict, the agent must read the new revision, merge semantically, and retry with a new idempotency key. Last-write-wins is prohibited.

## 5. Knowledge model

The live `knowledge/` directory is one OKF v0.2 bundle.

- Every knowledge document is Markdown with YAML frontmatter.
- `type` is required by OKF; this profile also requires `title`, `description`, `status`, `tags`, and `generated`.
- Claims copied or synthesized from external material include `sources`.
- Internal links are bundle-relative and begin with `/`.
- `index.md` provides navigation. `log.md` records significant changes newest first.
- Document types and their expected sections are declared in [config/taxonomy.yaml](config/taxonomy.yaml).
- Unknown valid OKF metadata must be preserved during edits.

The initial taxonomy is deliberately small. Changing it requires a decision document and a migration plan; adding random new types during ordinary capture is not allowed.

## 6. LLM Wiki maintenance method

The wiki is curated, not merely accumulated:

1. Search before creating.
2. Update an existing concept when the new information belongs there.
3. Create a new page only when it has a stable identity and useful links.
4. Separate durable knowledge from session logs and transient chat.
5. Link related concepts and record sources.
6. Periodically merge duplicates, split overloaded pages, repair links, and archive obsolete pages.
7. Treat semantic and vector indexes as disposable projections, never as the only copy.

No permanently running “wiki-building agent” is required. Any authorized agent can maintain the wiki by loading the same skill and calling the gateway. Scheduled maintenance agents are optional and use the same contract.

## 7. Backup and recovery

GitHub is a backup destination, not the live bus.

### Git backup

- The gateway creates a local commit for every accepted write or short atomic batch.
- A background worker pushes immediately and retries with exponential backoff.
- The default recovery-point objective for GitHub is five minutes.
- `kb_backup_status` exposes the last local commit, last pushed commit, lag, and failure reason.
- Backup lag above the objective triggers an alert but does not split the live authority.
- Force-pushes and destructive history rewrites are prohibited.
- The GitHub repository must be private and protected with strong account security.

### Independent backup

- Create an encrypted daily snapshot to a provider or object store separate from GitHub.
- Retain daily, weekly, and monthly recovery points according to storage budget.
- Keep encryption keys outside the live host.
- Perform and record a restore drill at least quarterly.

A backup is considered valid only after an automated restore can reconstruct the OKF bundle and pass repository validation.

## 8. Agent distribution

This repository is the canonical distribution source:

- `skills/maintain-llm-wiki/` contains the cross-agent workflow.
- `rules/knowledge-base.md` contains the invariant policy.
- `hooks/` contains deterministic repository checks.
- `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules/` are thin vendor adapters.

Adapters must point to the canonical assets and must not grow divergent copies of the policy. The installer links the same skill directory into supported user-level agent locations.

Runtime configuration is external to Git:

- gateway URL;
- bearer tokens;
- encryption keys;
- GitHub deployment credentials;
- snapshot credentials.

Commit only examples or variable names, never live secrets.

## 9. Security baseline

- Use TLS for every remote connection.
- Issue a different revocable token per agent or device.
- Separate read-only, writer, and administrator roles.
- Limit writer paths and operations where practical.
- Redact secrets before persistence and validate documents server-side.
- Record mutations with actor, timestamp, previous revision, and reason.
- Back up encrypted data and test token revocation.

## 10. Acceptance criteria

The production system is acceptable when:

1. two agents can concurrently edit the same page without silent loss;
2. a successful desktop write is visible from a phone agent on the next read;
3. an unavailable GitHub does not create a second authority;
4. backup lag and the last recovery point are observable;
5. a clean machine can restore the bundle from GitHub and pass validation;
6. a quarterly snapshot restore succeeds;
7. Codex, Claude Code, and Cursor load the same maintenance skill.

