# FastMCP Knowledge Gateway

This directory contains the executable reference implementation of the
Knowledge Gateway defined in [`STANDARD.md`](../STANDARD.md). It exposes all
eight normative tools over MCP Streamable HTTP while keeping the live OKF
bundle and operational data outside this repository.

Status: **reference alpha**. The local consistency path is implemented and
tested. Read the production gaps below before exposing it beyond a controlled
environment.

## Implemented contract

| Tool | Behavior |
|---|---|
| `kb_overview` | Bundle scope, taxonomy, health, document count, and Git head |
| `kb_search` | SQLite FTS5 content search with type, status, and tag filters |
| `kb_get` | Complete Markdown, parsed metadata, and SHA-256 revision |
| `kb_upsert` | Create or replace with validation, idempotency, and concurrency checks |
| `kb_archive` | Git-tracked move under `archive/` |
| `kb_history` | Gateway audit receipts and local Git history |
| `kb_validate` | Proposed-document or whole-bundle validation |
| `kb_backup_status` | Local/remote Git and independent snapshot state |

Every mutation is serialized with an OS file lock, written atomically, and
committed to the bundle's local Git repository. A new document requires
`create_only=true`; an existing document requires its exact
`expected_revision`. Reusing an idempotency key with a different request is a
conflict.

## Local development

Python 3.11 or later and Git are required.

```bash
cd gateway
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

export KB_BUNDLE_PATH=/tmp/knowledge-gateway/bundle
export KB_STATE_PATH=/tmp/knowledge-gateway/state
export KB_TAXONOMY_PATH=/path/to/development-taxonomy.yaml
export KB_SCOPE=local
export KB_AUTH_MODE=disabled
export KB_LOCAL_ACTOR=local-development
export KB_HOST=127.0.0.1
export KB_PORT=8000
export KB_MCP_PATH=/mcp
export KB_LOG_LEVEL=INFO
export KB_PUSH_AFTER_WRITE=false
export KB_GIT_REMOTE=origin

knowledge-gateway
```

This local command explicitly selects an operator-supplied taxonomy. The
repository contains no default or example taxonomy. Select the installed
base's own taxonomy in a real deployment.

Local development authentication is accepted only on a loopback bind. The MCP
endpoint is `http://127.0.0.1:8000/mcp`.

There are no fallback values for required runtime environment variables. The
process fails during import/startup and names the missing variable. Variables
that are conditional on a selected mode fail validation too: JWT settings are
required in JWT mode, and `KB_LOCAL_ACTOR` is required when authentication is
disabled. `KB_SNAPSHOT_STATUS_PATH` is genuinely optional because the
independent snapshot integration itself is optional.

Run tests:

```bash
pytest
```

## Container

Build from the repository root:

```bash
docker build -f gateway/Dockerfile -t knowledge-gateway:0.1.0 .
```

The image deliberately contains no taxonomy. At runtime, mount the
deployment-owned taxonomy and set `KB_TAXONOMY_PATH` to its container path.
This prevents a gateway upgrade from silently selecting or replacing a
knowledge model.

For Compose:

```bash
cd gateway
cp .env.example .env
# Select KB_TAXONOMY_FILE and fill in the identity-provider values.
# Never commit .env.
docker compose up --build
```

Compose refuses to start until `KB_TAXONOMY_FILE` explicitly selects a taxonomy
prepared for that deployment. The service is published only on host loopback.
Put a TLS reverse proxy in front of remote deployments and keep `/data` on
persistent storage.

## JWT actor contract

With `KB_AUTH_MODE=jwt`, the gateway verifies bearer tokens using the configured
JWKS URI, issuer, and audience. It derives:

- actor identity from `sub`, then `client_id`;
- permissions from the token scopes `kb:read`, `kb:write`, and `kb:admin`;
- an optional delegating principal from `delegating_principal` or the standard
  actor (`act`) claim.

Use separate, revocable credentials per participant, agent, or device. A
reverse proxy does not replace token validation.

## Runtime storage

`KB_BUNDLE_PATH` is the canonical OKF bundle and receives its own local `.git`
directory. `KB_STATE_PATH` contains SQLite FTS, audit and idempotency records,
locks, and backup observations. Both paths must be persistent and must not
point into this source repository in a real deployment.

The gateway initializes the local Git repository automatically. Configure its
off-host backup separately:

```bash
git -C /data/bundle remote add origin <private-backup-repository>
```

`KB_PUSH_AFTER_WRITE=true` performs a best-effort push after each commit. Push
failure leaves the accepted local write authoritative and reports the backup
as pending.

An independent snapshot job may atomically write JSON to
`KB_SNAPSHOT_STATUS_PATH`; `kb_backup_status` returns it without treating it as
authority.

## Runtime architecture and failure boundaries

Runtime data is deliberately split from source code:

```text
/data/
├── bundle/                     canonical OKF files and local .git history
└── state/
    ├── gateway.sqlite3         FTS projection, audit, and idempotency
    ├── backup.json             last observed Git backup state
    ├── snapshot-status.json    optional snapshot-job hand-off
    └── locks/mutation.lock     cross-process mutation serialization
```

The repository-wide mutation lock is intentional: Git has one shared index, so
per-document locks alone could let one mutation enter another mutation's
commit. A write therefore authenticates and authorizes the actor, checks
idempotency, validates the complete document, acquires the mutation lock,
compares the current revision, atomically replaces the file, creates the local
Git commit, and then records the FTS projection and receipt.

An unavailable remote backup never undoes a locally committed write or creates
a second authority. FTS is rebuilt from valid active documents at startup.
Audit and idempotency state must be included in machine snapshots. A crash
between the Git commit and SQLite receipt can leave a durable content change
without an MCP receipt; production hardening must add an operation journal and
startup reconciliation. Multiple gateway processes against one bundle are not
supported until a dedicated mutation coordinator exists.

## Production hardening still required

- terminate TLS and apply network policy;
- connect a production identity provider and test revocation;
- replace inline best-effort pushes with a supervised retry worker and alerts;
- add encrypted daily/weekly/monthly snapshots plus restore drills;
- add an operation journal to reconcile the narrow crash window between a Git
  commit and its SQLite receipt;
- add rate limits, metrics, structured logging, secret scanning, and load tests;
- keep a single gateway process per bundle until a dedicated mutation
  coordinator exists.
