# FastMCP Knowledge Gateway

This directory contains the executable reference implementation of the
Knowledge Gateway defined in [`STANDARD.md`](../STANDARD.md). It exposes the
normative MCP tools over Streamable HTTP while keeping the live OKF
bundle and operational data outside this repository.

Status: **reference alpha**. The local consistency path is implemented and
tested. Read the production gaps below before exposing it beyond a controlled
environment.

## Implemented contract

| Tool | Behavior |
|---|---|
| `kb_overview` | Bundle scope, taxonomy, health, document count, and Git head |
| `kb_search` | SQLite FTS5 content search (OR across tokens; BM25 rank) with type, status, tag, and inclusive `updated_at` (`since` / `until`) filters; hits include `updated_at` |
| `kb_get` | Complete Markdown, parsed metadata, and SHA-256 revision |
| `kb_upsert` | Create or replace with validation, idempotency, and concurrency checks |
| `kb_put_file` | Store a non-text artifact under reserved `files/` (base64, max 10 MiB) |
| `kb_get_file` | Artifact metadata and optional base64 bytes |
| `kb_list_files` | Inventory of `files/` |
| `kb_archive` | Move under `archive/` |
| `kb_history` | Gateway audit receipts and backup Git history |
| `kb_validate` | Proposed-document or whole-bundle validation |
| `kb_backup_status` | Scheduled Git backup state and lag |

Every mutation is serialized with an OS file lock and written atomically to the
bundle. Git commits are not created on write. A background scheduler controlled
by `KB_BACKUP_INTERVAL_HOURS` periodically commits dirty changes as
`backup <timestamp>` and best-effort pushes to the private remote. A new
document requires `create_only=true`; an existing document requires its exact
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
export KB_BACKUP_INTERVAL_HOURS=6
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
that are conditional on a selected mode fail validation too:
`KB_ACCESS_TOKEN` is required in token mode, and `KB_LOCAL_ACTOR` is required
when authentication is disabled.

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
# Select KB_TAXONOMY_FILE and generate KB_ACCESS_TOKEN.
# Never commit .env.
docker compose up --build
```

Compose refuses to start until `KB_TAXONOMY_FILE` explicitly selects a taxonomy
prepared for that deployment. The service is published only on host loopback.
Put a TLS reverse proxy in front of remote deployments and keep `/data` on
persistent storage.

## Single-user bearer-token contract

With `KB_AUTH_MODE=token`, the gateway accepts exactly the opaque bearer token
stored in `KB_ACCESS_TOKEN`. Generate it from at least 32 random bytes:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Configure every MCP client to send it as
`Authorization: Bearer <token>`. A successful match grants access to all MCP
tools and records mutations as `single-user`. There are no roles, per-tool
permissions, membership records, JWT claims, or token expiry in this profile.

The comparison is constant-time. Never commit or log the token, pass it in a
URL, or expose the remote endpoint without TLS. Rotation means replacing the
deployment secret, restarting the gateway, and updating every client.

This is deliberately a pre-shared-token profile rather than a full MCP OAuth
authorization-server and discovery implementation.

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

`KB_BACKUP_INTERVAL_HOURS` (required) sets how often the gateway commits dirty
bundle files and best-effort pushes to that remote. Example: `6` means every
six hours; `0.5` means every thirty minutes; `0` disables the scheduler.
Live writes remain authoritative even when a push fails and report
`backup: pending`.

## Runtime architecture and failure boundaries

Runtime data is deliberately split from source code:

```text
/data/
├── bundle/                     canonical OKF files, files/ artifacts, and local .git history
│   └── files/                  reserved non-text artifacts (PDF, images, other binaries)
└── state/
    ├── gateway.sqlite3         FTS projection, audit, and idempotency
    ├── backup.json             last observed Git backup state
    └── locks/mutation.lock     cross-process mutation serialization
```

The repository-wide mutation lock serializes live writes against each other and
against the periodic backup. A write authenticates the single user, checks
idempotency, validates the complete document, acquires the mutation lock,
compares the current revision, atomically replaces the file, and then records
the FTS projection and receipt. Git commit and push happen later on the
configured schedule.

An unavailable remote backup never undoes a locally accepted write or creates
a second authority. FTS is rebuilt from valid active documents at startup.
Audit and idempotency state must be preserved alongside the bundle when
restoring a host. Multiple gateway processes against one bundle are not
supported until a dedicated mutation coordinator exists.

## Production hardening still required

- terminate TLS and apply network policy;
- store `KB_ACCESS_TOKEN` in a deployment secret manager and document rotation;
- alert when backup lag exceeds `KB_BACKUP_INTERVAL_HOURS`;
- add an operation journal to reconcile crash windows between file write and
  SQLite receipt;
- add rate limits, metrics, structured logging, secret scanning, and load tests;
- keep a single gateway process per bundle until a dedicated mutation
  coordinator exists.
