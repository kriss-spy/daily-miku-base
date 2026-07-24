# V2 Operations

`/health` is process liveness. `/ready` verifies the packaged schema version and a
complete Raindrop tag query. `/internal/reconciliation-status` reports the latest
run separately from the latest complete run and marks reconciliation stale after
30 minutes, twice the scheduled reconciliation interval.

The disabled `V2 Operational Health` workflow polls protected preview every 15
minutes when `DAILY_MIKU_MONITORING_ENABLED` is explicitly enabled. Keep its
notification destination on a test channel before cutover.

| Signal | Alert condition |
| --- | --- |
| Readiness | `/ready` is non-200 or any dependency check fails |
| Reconciliation | latest complete run is over 30 minutes old |
| Scheduler | reconciliation or email workflow job fails |
| Images | structured `image_upstream_failed`, `image_unavailable`, or `image_timeout` errors |
| Email | workflow fails or durable recipient report has `failed > 0` |

HTTP errors and structured request logs share `X-Request-ID`. Dependency errors
are `no-store`; bounded route limits return `429` and `Retry-After` without
changing valid empty or conflict Daily Slot semantics.
