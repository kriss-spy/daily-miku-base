# V2 Operations

`/health` is process liveness. `/ready` verifies the packaged operational schema
version and a complete Raindrop dated-tag query. Selection dates have no database
reconciliation status: each uncached scan reads Raindrop-authoritative tags directly.
Complete snapshots are coalesced and cached in each warm process for
`DAILY_MIKU_SELECTION_SNAPSHOT_TTL` seconds (30 by default, at most 300).
Incomplete or failed scans are never cached as authoritative snapshots.

The disabled `V2 Operational Health` workflow polls protected preview every 15
minutes when `DAILY_MIKU_MONITORING_ENABLED` is explicitly enabled. Keep its
notification destination on a test channel before cutover.

| Signal | Alert condition |
| --- | --- |
| Readiness | `/ready` is non-200 or any dependency check fails |
| Selection tags | complete scan fails, or malformed or multi-date tags are present |
| Scheduler | email workflow job fails |
| Images | structured `image_upstream_failed`, `image_unavailable`, or `image_timeout` errors |
| Email | workflow fails or durable recipient report has `failed > 0` |

HTTP errors and structured request logs share `X-Request-ID`. Dependency errors
are `no-store`; bounded route limits return `429` and `Retry-After` without
changing valid empty or conflict Daily Slot semantics.
