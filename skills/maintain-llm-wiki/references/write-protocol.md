# Knowledge Gateway Write Protocol

## Required tool behavior

Use the gateway tools described in `STANDARD.md`: `kb_search`, `kb_get`, `kb_validate`, `kb_upsert`, `kb_archive`, `kb_history`, and `kb_backup_status`.

## Create

1. Search for duplicates.
2. Choose a type and path permitted by the gateway-configured deployment
   taxonomy.
3. Validate the complete document.
4. Send `kb_upsert` with a unique idempotency key and create-only precondition.
5. Retain the returned receipt.

## Update

1. Hydrate the page with `kb_get`.
2. Retain its revision.
3. Prepare and validate the complete replacement document.
4. Send `kb_upsert` with the retained `expected_revision` and a unique idempotency key.
5. Retain the returned receipt.

## Receipt semantics

A receipt proves the live write is durable on the gateway host and includes a
content revision. `commit` is `null` until a scheduled backup includes the
change. `backup: pending` means the live write succeeded but the separate
off-site Git backup has not caught up. Do not describe a pending backup as
complete.

## Conflict

A revision conflict means another accepted write happened after the read. Fetch the current page, perform a semantic three-way merge, validate, and retry. Never remove another actor's new information merely to make the retry succeed.

## Failure

- Authentication failure: stop and request credential repair.
- Validation failure: repair the document; do not bypass validation.
- Gateway unavailable: do not write directly to GitHub or a local clone.
- Backup delayed: the live authority remains valid; report and monitor the lag.
- Repeated idempotency key: inspect the returned prior result before retrying.
