# Daily Miku v2 CLI And Email Contract

Decision for [Define CLI and email contracts](https://github.com/kriss-spy/daily-miku-base/issues/8), confirmed 2026-07-17.

## Principles

- CLI commands use the Daily Slot language from `CONTEXT.md` and expose the same domain states as the HTTP contract.
- Human-readable output is the default. `--json` produces one stable JSON document on standard output. Diagnostics and logs go to standard error.
- An empty or conflicting Daily Slot is a successful result for a read command. It may still block an operation that requires exactly one selected Daily Miku.
- Commands never print tokens, passwords, connection strings, or recipient addresses beyond what the operator explicitly supplied.
- Raindrop remains authoritative for current bookmark content. Commands that need current content use the shared v2 application behavior rather than reimplementing selection rules.

## Command Surface

The following commands are the supported v2 contract:

| Command | Purpose |
| --- | --- |
| `daily-miku slot today [--json]` | Read today's Daily Slot. |
| `daily-miku slot get DATE [--json]` | Read the Daily Slot for an ISO `YYYY-MM-DD` date. |
| `daily-miku archive list [--cursor CURSOR] [--limit N] [--json]` | List non-empty Daily Slots newest-first. |
| `daily-miku doctor [--json]` | Check configuration and every required dependency without changing data or sending email. |
| `daily-miku email send [--date DATE] [--force] [--json]` | Reconcile current selections and deliver one date's selected Daily Miku. `DATE` defaults to today. |
| `daily-miku ledger initialize [--apply] [--json]` | Dry-run or apply the one-time legacy Selection Ledger initialization. |
| `daily-miku ledger reconcile [--json]` | Reconcile the complete current tagged set into the Selection Ledger. |
| `daily-miku ledger correct RAINDROP_ID DATE --reason TEXT [--json]` | Apply one audited manual Selection Day correction. |
| `daily-miku image ingest RAINDROP_ID FILE --authorization-note TEXT [--json]` | Validate, normalize, and store operator-supplied authorized image bytes. |
| `daily-miku image withdraw RAINDROP_ID --reason TEXT [--json]` | Record a withdrawal and stop controlled image delivery. |

The v1 names `fetch-today`, `fetch-date`, `test-connection`, `list`, and `send-email` are removed rather than retained as aliases. `serve` may remain a development convenience, but it is not a supported interface contract.

## Operator Commands

`ledger initialize` is dry-run by default. It completes a paginated scan, reports proposed legacy rows, conflicts, and duplicate identities, and writes only when `--apply` is present. Apply is transactional and idempotent. `ledger reconcile` performs the same routine full-set reconciliation used by email and the scheduled endpoint.

`ledger correct` is the controlled exception to insert-only Selection Days. It requires a non-blank reason, changes the row to the `manual` recording method, and appends the former and new date and method, reason, operator identity, and timestamp to correction history. It never silently moves another candidate out of a resulting conflict.

`image ingest` accepts a local raster file and an operator-supplied note describing the authorization basis. It applies the Image Pipeline's byte, type, decoding, dimension, normalization, metadata, and content-addressing policy before uploading and updating the Raindrop cover. It records provenance but does not claim that software independently verified reproduction rights.

`image withdraw` requires a reason, records a durable tombstone, and prevents controlled delivery with the contracted `410` outcome. Blob garbage collection must not remove content still referenced by another item. Neither image command exposes a public mutation endpoint.

Operator command argument and configuration failures use the common exit codes. A dry-run or idempotent no-op exits `0`; a rejected unsafe image is a domain-blocked operation and exits `5`; dependency failures exit `4`.

## Read Commands

`slot today` and `slot get` use the Slot representation in [the HTTP contract](http-contract.md). In JSON mode they emit that representation without a CLI-specific wrapper. Empty, selected, and conflicting slots all exit successfully because each is a valid read result.

`archive list` follows the HTTP archive contract: `limit` defaults to 24 and may not exceed 100, the cursor is opaque, and results are non-empty slots in descending Selection Day order. JSON mode emits the HTTP archive response envelope. An empty archive exits successfully.

Human output must identify the date and state. Selected output includes title, source URL, and Raindrop ID. Conflict output includes every candidate's title, source URL, and Raindrop ID. Empty output says that the Daily Slot is empty; it must not describe an empty slot as a dependency failure.

## Doctor

`doctor` checks all configuration and dependencies required by the deployed application:

1. Configuration values are present and parseable.
2. The Selection Ledger database is reachable and at the expected schema version.
3. Raindrop authentication works and the configured tag can be queried.
4. Vercel Blob credentials permit the required metadata and object operations without leaving a test object behind.
5. The SMTP server accepts a connection, STARTTLS, and authentication without sending a message.

Every check reports `ok`, `failed`, or `skipped`, plus a safe explanation. A failed prerequisite may cause dependent checks to be skipped. JSON mode has this shape:

```json
{
  "status": "failed",
  "checks": [
    {
      "name": "database",
      "status": "failed",
      "message": "Connection timed out."
    }
  ]
}
```

The command reports every check it can complete instead of stopping at the first failure. It never sends a test email or reveals a credential.

## Exit Codes

| Code | Meaning |
| ---: | --- |
| `0` | The command completed, including valid empty/conflict reads, an empty archive, and an already-delivered email no-op. |
| `1` | An unexpected internal failure occurred. |
| `2` | The invocation is invalid, including malformed dates, cursors, limits, options, or missing arguments. |
| `3` | Required configuration is missing or invalid. |
| `4` | A required dependency is unavailable or a transient/permanent dependency operation failed. |
| `5` | Valid domain state blocks an operation, including an empty or conflicting slot, a future email date, or a selected item without an available image. |

When several failures apply, argument validation takes precedence, then configuration, then domain state known without contacting an unavailable dependency, then dependency failure. `doctor` exits `3` if any configuration check fails, otherwise `4` if any dependency check fails.

In JSON mode, failed commands still emit one safe result document to standard output when argument parsing progressed far enough to select a command. It contains `error.code`, `error.message`, and an object-valued `error.details`; process exit status remains authoritative for shell automation.

## Email Preconditions

`email send` performs these steps in order:

1. Validate configuration and the requested date.
2. Reconcile current `daily-miku` tags into the Selection Ledger so an owner can tag a bookmark and immediately run this command.
3. Resolve the requested Daily Slot.
4. Require exactly one selected Daily Miku and one validated, controlled image mirror.
5. Reserve and send a separate message to each configured recipient that does not already have a successful Email Delivery.
6. Record each successful recipient delivery independently.

An empty slot sends nothing and exits `5`. This is not a claim that the slot is invalid; the delivery operation is blocked because it has no selected item. A conflicting slot also sends nothing, prints every candidate ID for resolution, and exits `5`. A selected item without an image sends nothing. It exits `5` when no image is available and `4` when image resolution failed because a dependency was unavailable.

The HTML email is image-focused and includes the Selection Day, title, description when present, and source attribution. It also includes a plain-text alternative. The image is embedded from validated controlled content; the sender must not emit HTML that references a missing CID or an unvalidated upstream URL.

## Recipients And Idempotency

`DAILY_MIKU_EMAIL_RECIPIENTS` contains a non-empty list of validated recipient addresses. The sender creates a separate message for each recipient so addresses are not disclosed to one another and outcomes can be tracked independently.

A successful Email Delivery is persisted by Selection Day and recipient. Later runs skip that recipient and report an `already_sent` no-op unless `--force` is present. If a batch partially succeeds, the command records successful recipients, exits `4`, and a normal rerun attempts only failed recipients. `--force` deliberately sends again to every configured recipient and creates a new delivery attempt.

Concurrent invocations must serialize delivery reservation per date and recipient. Authenticated SMTP has no provider idempotency key, so exactly-once delivery cannot be guaranteed if the process dies after the SMTP server accepts a message but before the success record commits. The implementation must document this crash window and prevent duplicates in all recorded-success and concurrent-run cases.

JSON success output has this shape:

```json
{
  "status": "sent",
  "date": "2026-07-17",
  "recipients": {
    "configured": 3,
    "sent": 2,
    "skipped": 1,
    "failed": 0
  }
}
```

`status` is one of `sent`, `already_sent`, `empty`, `conflict`, or `failed`. Output reports counts rather than recipient addresses.

## Retry Policy

Each transient dependency operation receives at most three attempts in one command run. Image mirroring completes once before recipient delivery; each recipient's SMTP operation is retried independently. Retries use bounded exponential backoff with jitter and apply only to timeouts, connection interruptions, rate limits that provide a usable retry delay, and dependency 5xx responses.

The command does not retry invalid configuration, authentication rejection, invalid recipient addresses, empty/conflicting slots, unavailable images, or other permanent failures. Successful recipient deliveries are never repeated by retry logic.

## Scheduling And Recovery

GitHub Actions owns the scheduled delivery workflow. It starts once daily at `04:00 UTC`, corresponding to `12:00` in the default `Asia/Shanghai` calendar timezone, and supports `workflow_dispatch` for manual execution. Selection Day is always resolved in `DAILY_MIKU_TIMEZONE`; scheduler process timezone does not change it.

The workflow runs `daily-miku email send`. Job status is the only owner notification channel:

- A selected slot delivered to all pending recipients exits `0`.
- An already-delivered date exits `0`.
- An empty or conflicting slot exits `5`, causing the job to fail visibly.
- Configuration, dependency, partial-delivery, and unexpected failures also fail the job with their categorized exit code.

After an empty-slot notification, the owner adds the `daily-miku` tag in Raindrop and runs `daily-miku email send` locally or through an equivalent manual workflow. The command's initial reconciliation makes a separate sync command unnecessary. There are no scheduler-level automatic retries beyond the command's three bounded dependency attempts.

## Configuration

V2 uses a clean configuration namespace and does not retain v1 environment names as aliases:

| Variable | Requirement |
| --- | --- |
| `DAILY_MIKU_TIMEZONE` | Optional; defaults to `Asia/Shanghai`. |
| `DAILY_MIKU_TAG` | Optional; defaults to `daily-miku`. |
| `DAILY_MIKU_OPERATOR` | Required for audited ledger correction and image mutation commands. |
| `DAILY_MIKU_RECONCILE_SECRET` | Required by the internal scheduled reconciliation endpoint and its caller. |
| `DAILY_MIKU_EMAIL_FROM` | Required for email; one validated sender address. |
| `DAILY_MIKU_EMAIL_RECIPIENTS` | Required for email; comma-separated validated recipient addresses. |
| `RAINDROP_TOKEN` | Required for reconciliation and Raindrop-authoritative content. |
| `DATABASE_URL` | Required for the Selection Ledger and Email Delivery records. |
| `BLOB_READ_WRITE_TOKEN` | Required for controlled image mirroring. |
| `SMTP_HOST` | Required for email. |
| `SMTP_PORT` | Optional; defaults to `587`. |
| `SMTP_USERNAME` | Required for authenticated SMTP. |
| `SMTP_PASSWORD` | Required for authenticated SMTP. |

SMTP uses STARTTLS and fails closed if encryption or authentication cannot be established. Recipient parsing trims surrounding whitespace, rejects an empty entry, and removes exact duplicate addresses while preserving configured order.

## Explicit Removals

- No token prefix or secret-derived value appears in `doctor` output.
- Dependency failures are not converted into empty Slot or archive results.
- Local filesystem counters do not control alerts, retries, or idempotency.
- The sender does not issue a separate warning email. GitHub Actions job status is the owner notification.
- A failed image fetch cannot produce a successful email with a broken embedded image.
- The scheduler does not claim success after a nonzero CLI exit.
