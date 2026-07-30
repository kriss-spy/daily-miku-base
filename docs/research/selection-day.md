# Recording Selection Day

> **Superseded on 2026-07-27 by [ADR 0001](../adr/0001-store-selection-dates-in-raindrop-tags.md).** V2 now records the explicit Selection Day in a canonical `daily-miku-YYYY-MM-DD` Raindrop tag and does not use a Selection Ledger. This document remains as historical research explaining why a generic `daily-miku` tag could not provide an exact date.

Research for [Determine how to record Selection Day](https://github.com/kriss-spy/daily-miku-base/issues/4), conducted 2026-07-17.

## Decision

Raindrop cannot provide the exact time when the `daily-miku` tag was added. Daily Miku v2 should use an insert-only Selection Ledger in Postgres and describe its automatically captured timestamp as **first observed at**, not tag-added at.

The synchronizer should repeatedly reconcile the complete set of bookmarks matching `#daily-miku`. A separate, one-time initialization run imports existing matches using their current `lastUpdate` date to preserve v1 dated URLs, while explicitly marking those dates as legacy approximations. On later reconciliations, a previously unseen match receives the current UTC observation instant and the calendar date of that instant in the configured timezone. An operator may replace an approximate date with a known historical Selection Day, but the system must never present a legacy `lastUpdate` date as the exact tag-added day.

This design keeps Raindrop authoritative for bookmark content and current tag membership. The ledger is authoritative only for the first observation and any explicitly recorded Selection Day.

## Raindrop Evidence

Raindrop's documented bookmark representation includes `_id`, `tags`, `created`, and `lastUpdate`. It includes neither tag history nor a timestamp for an individual tag. `created` is the bookmark creation date and `lastUpdate` is a general update date.[^raindrop-fields]

Tags, title, note, cover, collection, and other properties can all be updated. Consequently, `lastUpdate` cannot establish which property changed or preserve evidence of the update that first added `daily-miku`.[^single-raindrop] The Tags API exposes tag names and counts, not membership events or timestamps.[^tags]

No webhook, change-feed, event-subscription, or tag-event resource appears in the official API index. This establishes that there is no supported public event contract, not that Raindrop has no internal events.[^api-index]

The supported observation mechanism is therefore polling:

- `GET /rest/v1/raindrops/0` searches all bookmarks except Trash.[^multiple-raindrops]
- `search=#daily-miku` selects the current tagged set.[^search]
- Results use zero-based pages with at most 50 bookmarks per page.[^multiple-raindrops]
- Documented sort values cover creation date, relevance, manual order, title, and domain. Sorting by `lastUpdate` is not documented.[^multiple-raindrops]
- Search can filter `lastUpdate` by a date, but this is an update-date filter rather than a tag-event cursor.[^search]
- API timestamps use ISO 8601 UTC.[^api-overview]

The existing v1 client sorts by the undocumented value `-lastUpdate` and treats that timestamp as Selection Day. That can approximate recently changed bookmarks, but it is not a durable v2 contract: any later edit can move a Daily Miku to another day.

## Observation Limits

For a bookmark first seen with the tag at time `T`, the exact defensible statement is: "the bookmark had `daily-miku` when observed at `T`." If a complete preceding reconciliation at `P` did not contain it, the addition is bounded to `(P, T]` only if the tag remained present and both scans were complete.

The following information cannot be recovered:

- If polling is unavailable across a calendar boundary, the true Selection Day is ambiguous.
- If the tag is added and removed between polls, the selection is permanently invisible.
- Existing tagged bookmarks can be enumerated during initialization, but their historical Selection Days cannot be reconstructed from `created` or `lastUpdate`.
- If a bookmark is removed and later re-tagged, a ledger keyed by bookmark records only its first observed selection. Recording every selection episode would require an event stream that Raindrop does not expose.
- Raindrop does not document snapshot consistency across paginated results. Concurrent changes may cause a scan to duplicate or skip a bookmark. Idempotent writes and repeated full reconciliation reduce this risk but cannot recover a transient tag.

Polling frequency narrows but never removes the uncertainty window. Vercel Cron delivery is best effort, failed invocations are not retried, duplicate and overlapping invocations can occur, and Hobby schedules run at most daily and at any point in the configured hour.[^vercel-cron] A product requirement for exact tag-added day would therefore require changing the selection workflow so that an application-controlled operation records the ledger entry while applying the tag; polling manual changes in Raindrop cannot satisfy it.

## Synchronization Contract

Each run should:

1. Record one UTC `observed_at` instant for the run.
2. Fetch every page matching `#daily-miku`, following the documented pagination contract rather than relying on `-lastUpdate` ordering.
3. Insert each previously unseen Raindrop ID using an atomic conflict-safe write.
4. On an explicit initialization run, mark current matches as `legacy` and derive their approximate date from `lastUpdate` in the configured calendar timezone.
5. Before applying initialization, report multiple Raindrop IDs assigned to one date and duplicate IDs, normalized source URLs, or normalized cover identities anywhere in the import for operator review.
6. On routine runs, mark unseen matches as `observed` and derive their Selection Day from `observed_at` in the configured IANA calendar timezone.
7. Preserve rows when tags are removed or bookmark metadata changes.
8. Resolve current title, source, cover, tags, and other content from Raindrop rather than copying them into the ledger.

Full reconciliation is required for correctness. A conservative, overlapping `lastUpdate` query may reduce work, but it cannot be the only scan because it has date granularity, reflects unrelated updates, and lacks a supported corresponding sort order.

The operation must be idempotent because Vercel recommends reconciliation-based handling of missed and duplicate Cron deliveries.[^vercel-cron] A unique Raindrop ID and `INSERT ... ON CONFLICT DO NOTHING` make duplicate or overlapping runs harmless.

## Minimal Selection Ledger

```sql
create type selection_recording_method as enum ('legacy', 'observed', 'manual');

create table selection_ledger (
    raindrop_id bigint primary key,
    first_observed_at timestamptz not null,
    selection_day date not null,
    recording_method selection_recording_method not null
);

create index selection_ledger_day_idx on selection_ledger (selection_day);
```

Field semantics:

| Field | Contract |
| --- | --- |
| `raindrop_id` | Stable Raindrop `_id`; identity and conflict key. |
| `first_observed_at` | UTC instant when this service first completed an observation of the bookmark carrying `daily-miku`; never represented as the exact tag-add time. |
| `selection_day` | Immutable calendar date in the configured timezone. For `legacy` rows this is only the date needed to preserve v1 behavior. |
| `recording_method` | `legacy` for an initialization date derived from current `lastUpdate`, `observed` for a polling-derived day, or `manual` for an operator-supplied historical day. |

`selection_day` must not be unique. Multiple bookmarks on one day represent a Daily Slot conflict that initialization must report and downstream interfaces must expose. The primary key prevents one Raindrop ID from occupying two dates in the ledger. Duplicate source URLs or image identities across different Raindrop IDs require a dry-run warning because they may represent the same work, but they cannot be rejected automatically. The ledger is insert-only during normal synchronization; a narrowly controlled manual correction may replace a legacy approximation and method, with an audit mechanism specified during implementation.

The initializer cannot discover a bookmark's former v1 date after `lastUpdate` changes unless an external snapshot recorded it. Comparing the current tagged set can detect collisions and duplicate identities, not reconstruct overwritten history.

A sync-run table would improve monitoring and preserve negative-observation bounds, but it is not part of the smallest ledger contract. Operational design should add one if alerting or measurable synchronization lag is required.

## Timezone Rules

- Store `first_observed_at` as a UTC instant.
- Derive `selection_day` once using the configured IANA timezone, currently `Asia/Shanghai`.
- Persist the derived date so a later timezone configuration change does not move historical Daily Slots.
- Use the function's actual observation time, not the Cron expression's nominal time. Vercel may invoke Hobby Cron at any point in the scheduled hour.[^vercel-cron]
- Treat Raindrop date-only search boundaries conservatively; its search documentation does not define their timezone interpretation.[^search]

## Persistence Choice

Use a serverless Postgres provider from Vercel Marketplace, with Neon as the default when there is no existing provider preference. Vercel supports managed Postgres integrations including Neon, Supabase, Prisma Postgres, and Aurora, injects credentials through environment variables, and identifies Postgres as the structured-data option with transactional behavior.[^vercel-storage]

Postgres provides the uniqueness, atomic insert, date query, and future migration behavior this ledger needs without application-managed object concurrency. Redis is oriented toward key-value workloads such as caching and rate limiting, while a JSON blob would require whole-object concurrency and migration logic.[^vercel-storage]

## Consequences For V2

- Product and API language must distinguish **Selection Day** from an automatically observed day. An observed day is an approximation unless selection is performed through an application-controlled write path.
- Initialization is a separate dry-run/apply operation; it must paginate the full tagged set and report conflicts and likely duplicates before writing legacy dates.
- Empty Daily Slots remain valid; multiple entries on one date remain visible conflicts, including legacy entries.
- The migration plan must preserve legacy dates without claiming they are exact and define how operators correct known historical dates.
- Reliability requirements must choose an acceptable maximum observation delay and a Vercel plan or external trigger capable of that polling interval.

[^raindrop-fields]: [Raindrop API: Raindrop fields](https://developer.raindrop.io/v1/raindrops)
[^single-raindrop]: [Raindrop API: Single raindrop](https://developer.raindrop.io/v1/raindrops/single)
[^tags]: [Raindrop API: Tags](https://developer.raindrop.io/v1/tags)
[^api-index]: [Raindrop API documentation index](https://developer.raindrop.io/llms.txt)
[^multiple-raindrops]: [Raindrop API: Multiple raindrops](https://developer.raindrop.io/v1/raindrops/multiple)
[^search]: [Raindrop Help: Search filters](https://help.raindrop.io/filters)
[^api-overview]: [Raindrop API overview](https://developer.raindrop.io/readme)
[^vercel-cron]: [Vercel: Managing Cron Jobs](https://vercel.com/docs/cron-jobs/manage-cron-jobs)
[^vercel-storage]: [Vercel: Storage on Vercel Marketplace](https://vercel.com/docs/marketplace-storage)
