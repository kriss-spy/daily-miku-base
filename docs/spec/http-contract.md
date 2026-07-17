# Daily Miku v2 HTTP Contract

Decision for [Design the v2 HTTP contracts](https://github.com/kriss-spy/daily-miku-base/issues/7), confirmed 2026-07-17.

## Principles

- A Daily Slot is the canonical HTTP resource. It represents one calendar date and has an explicit `empty`, `selected`, or `conflict` state.
- JSON endpoints use unversioned `/api/...` paths. There are no known consumers of the v1 JSON endpoints, so v2 does not preserve or redirect them.
- `https://dailymiku.dev/image/<date>` is the only retained legacy HTTP path.
- Domain states are successful representations, not transport failures. Empty and conflicting Daily Slots return JSON successfully and are never collapsed into a selected candidate.
- Raindrop remains authoritative for current bookmark content. The Selection Ledger supplies Selection Day, recording method, and first-observed time.
- All dates in paths and query parameters use the ISO 8601 `YYYY-MM-DD` calendar-date form and the configured calendar timezone.

## HTML Routes

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/` | Render today's Daily Slot. |
| `GET` | `/today` | Redirect to `/`. |
| `GET` | `/{date}` | Render the Daily Slot for `date`, including empty and conflict states. |
| `GET` | `/archive` | Render chronological archive browsing. |
| `GET` | `/search` | Render search over selected Daily Mikus. |

The browsing prototype may refine presentation and progressive enhancement, but it must consume these domain states without changing their meaning.

## Slot Representation

`GET /api/slots/{date}` returns one Daily Slot. Every syntactically valid date through the current calendar day returns `200`, including an empty date. A future date returns `422`; malformed date syntax returns `400`.

```json
{
  "date": "2026-07-17",
  "state": "selected",
  "items": [
    {
      "raindrop_id": 123,
      "title": "Daily Miku",
      "excerpt": "...",
      "source_url": "https://example.com/artwork/123",
      "image_url": "/image/2026-07-17",
      "domain": "example.com",
      "tags": ["daily-miku"],
      "recording_method": "observed",
      "first_observed_at": "2026-07-16T16:03:00Z"
    }
  ],
  "links": {
    "self": "/api/slots/2026-07-17",
    "previous": "/api/slots/2026-07-16",
    "next": null
  }
}
```

`items` has a cardinality determined by `state`:

| State | Item count | Meaning |
| --- | ---: | --- |
| `empty` | 0 | No Daily Miku occupies the date. This is valid domain state. |
| `selected` | 1 | Exactly one Daily Miku occupies the date. |
| `conflict` | 2 or more | Multiple candidates occupy the date and require operator resolution. |

The API does not expose an upstream cover URL as its delivery contract. `image_url` points to Daily Miku's controlled date route. `recording_method` is `legacy`, `observed`, or `manual`; clients must not describe `legacy` or `observed` records as exact tag-add timestamps.

## Slot Selectors

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/slots/today` | Return today's slot in any state. |
| `GET` | `/api/slots/latest` | Return the latest non-empty slot, including a conflict. |
| `GET` | `/api/slots/random` | Return a randomly selected, non-conflicting slot. Never choose a candidate from a conflict. |

Selectors return the same Slot representation as the dated endpoint. `latest` returns `404` when no non-empty slot exists. `random` returns `404` when no selected slot exists.

## Calendar Range

`GET /api/slots?from={date}&to={date}` returns an inclusive, ascending calendar range. It includes empty dates so clients can render a faithful calendar. Both bounds are required, `from` must not follow `to`, and the range may contain at most 366 days.

```json
{
  "items": [],
  "links": {
    "self": "/api/slots?from=2026-07-01&to=2026-07-17"
  }
}
```

Ranges are bounded resources and are not cursor-paginated. Invalid or oversized ranges return `400`; a range extending into the future returns `422`.

## Archive

`GET /api/archive?cursor={cursor}&limit={limit}` returns non-empty slots newest-first. `limit` defaults to 24 and may not exceed 100. The response has this shape:

```json
{
  "items": [],
  "next_cursor": null,
  "links": {
    "self": "/api/archive?limit=24",
    "next": null
  }
}
```

The cursor is opaque to clients and identifies the next stable position in descending Selection Day order. A malformed or expired cursor returns `400`. Corrections to dates already passed by a cursor may change later page results; the API does not promise snapshot isolation across separate requests.

## Search

`GET /api/search?q={query}&cursor={cursor}&limit={limit}` searches current Raindrop-authoritative content restricted to Raindrop IDs present in the Selection Ledger. Results are grouped into Slot representations so a matching conflict candidate does not hide the other occupants of its Daily Slot.

Search uses the same response envelope, cursor behavior, default limit, and maximum limit as the archive. A blank query or malformed cursor returns `400`. Search ordering is relevance-first with Selection Day descending as the deterministic tie-breaker.

## Statistics

`GET /api/statistics?from={date}&to={date}` reports statistics for an inclusive bounded period. When omitted, the bounds default to the earliest ledger date and today.

```json
{
  "from": "2025-01-01",
  "to": "2026-07-17",
  "calendar_days": 563,
  "selected_slots": 540,
  "empty_slots": 21,
  "conflict_slots": 2,
  "candidates": 544
}
```

Counts retain the distinction between slots and candidates. Range validation follows the calendar-range endpoint, except the default full-history interval is not subject to the 366-day response limit because this endpoint returns aggregates rather than Slot representations.

## Direct Images

`GET /image/{date}` resolves the dated Slot before resolving its image. It follows the mirror-first strategy in [Resilient Image Delivery](../research/image-delivery.md).

| Condition | Status | Contract |
| --- | ---: | --- |
| Selected slot with validated image | `307` | Redirect to controlled, content-addressed Blob content. |
| Invalid date syntax | `400` | Return an error response, never image-like bytes. |
| Empty slot or selected item without an image | `404` | No image is available. |
| Conflicting slot | `409` | Refuse to choose a candidate. |
| Confirmed withdrawn image | `410` | The image is intentionally unavailable. |
| Invalid, forbidden, or missing upstream without a mirror | `502` | Image resolution failed upstream. |
| Upstream timeout | `504` | Image resolution timed out. |
| Temporary service failure | `503` | A dependency is temporarily unavailable. |

The mutable date response uses short browser and CDN caching. The redirected content-addressed object is immutable and may use long caching and ETags. Five-hundred-level responses use `no-store`. The service never forwards upstream HTML or JSON as image bytes and sets `X-Content-Type-Options: nosniff` whenever it serves validated bytes through a constrained recovery path.

## Error Envelope

Every JSON error uses one stable shape:

```json
{
  "error": {
    "code": "slot_conflict",
    "message": "Multiple Daily Mikus occupy this slot.",
    "details": {},
    "request_id": "01J..."
  }
}
```

`code` is a stable machine-readable identifier. `message` is human-readable and may improve without a contract change. `details` contains safe structured context and is always an object. `request_id` correlates client reports with server logs. Dependency failures remain distinguishable from valid empty results.

## General Status Semantics

| Status | Use |
| --- | --- |
| `200` | Successful JSON or HTML representation, including empty and conflicting Slot state. |
| `307` | Mutable direct-image redirect. |
| `400` | Malformed dates, cursors, queries, ranges, or limits. |
| `404` | A selector has no eligible result, a route does not exist, or no direct image is available. |
| `409` | An operation requiring one selected item encounters a Slot conflict. |
| `410` | Confirmed withdrawal or tombstone. |
| `422` | A syntactically valid request addresses future calendar time. |
| `429` | Rate limit exceeded, with `Retry-After`. |
| `502`, `503`, `504` | Distinct dependency failure classes. |

Unexpected server errors return `500` with the standard error envelope and no internal exception details.

## Caching

- Dated Slot responses use short shared caching because manual corrections and reconciliation can change state.
- Today, latest, random, search, and statistics responses use shorter caching or `no-store` where freshness or randomness requires it.
- Historical range and archive responses may use bounded shared caching but are not declared immutable because manual corrections remain possible.
- Successful responses include validators where practical. Error caching follows the image-delivery decision: brief caching for stable `404` responses and `no-store` for dependency failures.

## Deprecation And Removal

The v1 JSON paths, including `/api/today` and `/api/list`, have no known external consumers and are removed rather than redirected. The local-only v1 latest, random, statistics, week, month, and year paths are likewise replaced by the contracts above. Requests to removed paths return the normal `404` error envelope.

The `/today` HTML purpose remains as a redirect to the canonical homepage. Dated HTML access remains available at `/{date}`. The direct-image path `/image/{date}` remains stable across the rewrite.
