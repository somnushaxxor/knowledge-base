# Cloud-First LLM Wiki Standard

Status: **Draft v0.1**

## 1. Purpose

This standard defines a knowledge base that:

- can serve an individual, a project team, or another explicitly defined group;
- is current across participants, computers, phones, and cloud agents;
- can be read and changed concurrently by multiple people and agents;
- remains portable, human-readable, and usable without a vendor;
- distributes the same maintenance behavior to Codex, Claude Code, Cursor, NanoClaw, and future agents;
- has a versioned backup separate from this agent-kit repository and an independent disaster-recovery backup.

Personal and project knowledge bases are deployment profiles of the same
concept, not separate architectures. Every deployed knowledge base has an
explicit scope, membership, and authorization policy. A project deployment
acts as shared project memory: authorized participants and their agents work
with the same canonical knowledge, while changes remain attributable to the
human, agent, or process that made them.

## 2. Chosen stack

| Layer | Choice | Responsibility |
|---|---|---|
| Knowledge method | [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | Maintain a small, linked, evolving wiki rather than an append-only transcript |
| Canonical format | [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) | Markdown, YAML frontmatter, sources, provenance, links, and reserved indexes |
| Live authority | Custom Knowledge Gateway on one cloud host, implemented with FastMCP | Authenticate agents, search, read, serialize writes, validate, and return durable revisions |
| Agent protocol | MCP over Streamable HTTP | Give different agents one standard remote tool surface |
| Lexical search | SQLite FTS5 or QMD-compatible local index | Fast full-text retrieval over the live OKF bundle |
| Semantic search | Optional derived vector index | Improve recall; always rebuildable from OKF |
| Backup | Local Git history pushed to a separate private Git repository | Off-site, reviewable, versioned recovery copy without mixing knowledge content into the agent kit |
| Disaster recovery | Encrypted provider snapshot/object-store archive | Recover when both the live disk and Git remote are unavailable |
| Agent behavior | Canonical skill, rules, and hooks in this repository | Make all agents follow the same workflow |

The gateway is custom because no sufficiently established project currently combines strict OKF storage, remote MCP, authenticated multi-writer concurrency, and explicit backup semantics. It should be small and boring: use mature libraries, keep OKF as the source of truth, and avoid inventing a database-specific knowledge format.

The buildable reference implementation lives in `gateway/`. FastMCP provides
the MCP protocol and Streamable HTTP transport; the custom code owns the OKF
profile, scope authorization, optimistic-concurrency protocol, idempotency,
audit receipts, Git history, and backup semantics.

### Implementation decision

The reference gateway is implemented in Python on FastMCP 3.x so the project
can spend its complexity budget on knowledge storage and consistency instead
of reimplementing MCP. FastMCP owns protocol negotiation, tool schemas,
Streamable HTTP, test clients, and JWT verification integration. The domain
service remains independent of the transport framework.

The dependency is constrained to `fastmcp>=3.4,<4`. A major-version upgrade
requires an explicit dependency review and passing gateway contract tests.
FastMCP is an upstream framework, not this product's storage format or unique
technology boundary.

## 3. Authority and consistency

There is exactly one live authority for each knowledge-base scope: the
persistent OKF bundle mounted by its Knowledge Gateway. A deployment may host
multiple scopes only when it provides equivalent workspace isolation,
authorization, and backup boundaries.

Agents must not:

- use GitHub as the source for live reads;
- edit the live files through SSH, Drive sync, or a second server;
- maintain a private canonical memory that is invisible to other agents;
- read or write knowledge outside the scope authorized for their participant or project;
- claim that a fact was saved when the gateway did not return a write receipt.

All successful gateway writes are visible to subsequent reads immediately. A
project participant, a phone agent, and a desktop agent therefore see the same
accepted revision within their shared scope even if the separate Git backup is
temporarily delayed.

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

- an authenticated actor identity derived from its credential;
- the knowledge-base scope and an authorization check for that scope;
- an idempotency key;
- `expected_revision` for an update, or an explicit create-only condition;
- a complete OKF document;
- an audit reason or source reference.

The actor identifies the human, agent, or process making the change. When an
agent acts on behalf of a person or project role, the audit record should
preserve both the agent identity and the delegating principal where the
authentication system can provide them.

The gateway authorizes the scoped operation, performs validation, obtains a
per-document lock, checks the expected revision, writes atomically, updates the
search projection, and creates a local Git commit. It then returns:

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

The gateway-managed bundle directory is one OKF v0.2 bundle. Its configured
runtime path is external to this agent-kit repository.

- Every knowledge document is Markdown with YAML frontmatter.
- `type` is required by OKF; this profile also requires `title`, `description`, `status`, `tags`, and `generated`.
- Claims copied or synthesized from external material include `sources`.
- Internal links are bundle-relative and begin with `/`.
- `index.md` provides navigation. `log.md` records significant changes newest first.
- Document types and their expected sections are declared by a
  deployment-owned taxonomy explicitly selected through
  `KB_TAXONOMY_PATH`.
- Unknown valid OKF metadata must be preserved during edits.

The standard defines the taxonomy configuration contract, not a universal list
of document types. The kit contains no default or example taxonomy.
Installation requires an explicit deployment model supplied by the operator.
The installed copy belongs to the deployment rather than to the agent kit. The
gateway must never select a taxonomy implicitly.

A taxonomy is a YAML document with this shape:

```yaml
version: 1
policy:
  unknown_types: reject
  type_changes_require_decision: true
  internal_links: bundle_absolute
types:
  - type: TypeName
    folder: folder-name
    purpose: Human-readable guidance for agents and maintainers.
    sections:
      - Required section
```

For every entry, `type` and `folder` are required. `purpose` is guidance for
agents and maintainers. `sections` is an optional list of required level-two
headings. A deployment should keep type names and top-level folders unique.
The gateway enforces declared document types, their top-level folders, and
required sections. The remaining policy keys document deployment policy for
agents and maintainers.

Once a bundle contains knowledge, changing its taxonomy requires a durable
decision and a migration plan. Adding undeclared types during ordinary capture
is not allowed. Before switching `KB_TAXONOMY_PATH`, record the reason, map
affected documents and links, migrate the bundle, and validate the complete
bundle against the proposed taxonomy.

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

In a project knowledge base, maintenance is a collaborative operation:

- all authorized participants and agents search and update the same canonical
  concepts instead of keeping isolated private copies;
- permissions may distinguish readers, contributors, and administrators;
- provenance and revision history make contributions attributable and
  reviewable;
- concurrent edits follow the same optimistic-concurrency protocol regardless
  of whether they originated from different people, agents, or devices.

## 7. Backup and recovery

The separate private Git repository is a backup destination, not the live bus.
This agent-kit repository must never receive live or backup knowledge payloads.

### Git backup

- The gateway creates a local commit for every accepted write or short atomic batch.
- A background worker pushes immediately and retries with exponential backoff.
- The default recovery-point objective for GitHub is five minutes.
- `kb_backup_status` exposes the last local commit, last pushed commit, lag, and failure reason.
- Backup lag above the objective triggers an alert but does not split the live authority.
- Force-pushes and destructive history rewrites are prohibited.
- The backup repository must be private, separate from this agent-kit
  repository, and protected with strong account security.

### Independent backup

- Create an encrypted daily snapshot to a provider or object store separate from GitHub.
- Retain daily, weekly, and monthly recovery points according to storage budget.
- Keep encryption keys outside the live host.
- Perform and record a restore drill at least quarterly.

A backup is considered valid only after an automated restore can reconstruct
the OKF bundle and pass bundle validation.

## 8. Agent distribution

This repository is the canonical distribution source:

- `gateway/` contains the buildable FastMCP reference implementation and its
  tests; it never contains runtime data.
- `skills/maintain-llm-wiki/` contains the cross-agent workflow.
- `rules/knowledge-base.md` contains the invariant policy.
- `hooks/` contains deterministic repository checks.
- `templates/runtime/` contains the active vendor adapters installed into a
  project whose agents are connected to a Knowledge Gateway.
- the root `AGENTS.md` and `CLAUDE.md` govern development of the distribution
  kit only and do not activate the runtime workflow.

Runtime adapters must point to the canonical assets and must not grow divergent
copies of the policy. The installer copies those assets into the selected
project's `.agents/` directory. It must not install the skill globally or
activate the source repository, because either action would make unrelated
sessions behave as if they had a configured knowledge base.

Activation is a deployment step and occurs only after the target agents have a
configured gateway connection. Projects with existing agent instructions
install the shared assets and merge the relevant runtime adapter template
manually.

The repository must not contain a `knowledge/` directory, live OKF documents,
or a copy of the backup payload.

Runtime configuration is external to Git:

- gateway URL;
- bearer tokens;
- encryption keys;
- GitHub deployment credentials;
- snapshot credentials.

Commit only examples or variable names, never live secrets.

## 9. Security baseline

- Use TLS for every remote connection.
- Issue a different revocable credential per person, agent, service, or device.
- Define membership separately for every personal, project, or organizational
  knowledge-base scope.
- Separate reader, contributor, and administrator roles.
- Enforce scope boundaries on every read, search, history, and mutation
  operation, not only on writes.
- Limit contributor paths and operations where practical.
- Redact secrets before persistence and validate documents server-side.
- Record mutations with actor, timestamp, previous revision, and reason.
- Back up encrypted data and test token revocation.
- Prevent one project scope from appearing in another project's search results,
  semantic index, history, logs, or backups.

## 10. Acceptance criteria

The production system is acceptable when:

1. two project participants or agents can concurrently edit the same page
   without silent loss;
2. a successful write by one authorized participant is visible to another
   authorized participant or agent on the next read;
3. an unauthorized participant cannot discover or access another personal or
   project scope;
4. revision history attributes every accepted mutation to its actor and, when
   applicable, its delegating principal;
5. an unavailable GitHub does not create a second authority;
6. backup lag and the last recovery point are observable;
7. a clean machine can restore the bundle from the separate Git backup and pass validation;
8. a quarterly snapshot restore succeeds;
9. Codex, Claude Code, and Cursor load the same maintenance skill.
