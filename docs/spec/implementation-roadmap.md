# Daily Miku v2 Implementation Roadmap

Decision for [Build the practical v2 roadmap](https://github.com/kriss-spy/daily-miku-base/issues/10), confirmed 2026-07-19.

## Release Boundary

V2 is delivered through three cumulative milestones on a protected Vercel preview. A milestone is an independently verifiable implementation boundary, not a partial public release. Public traffic remains on v1 until the third milestone passes every migration gate and the complete v2 deployment is promoted atomically.

Implementation proceeds as small internal vertical slices. Each slice joins domain behavior to an adapter or delivery surface and is tested through its public interface. The milestone order is fixed by dependency: establish durable Slot semantics first, build the core experience over them, then add discovery and operational proof before cutover.

## Milestone 1: Operational Foundation

Build an operational vertical slice that can record and read Daily Slots without presenting a polished public surface.

### Scope

- Establish the v2 package layout, supported dependencies, configuration validation, composition root, structured logging, and request IDs.
- Implement the pure domain core: calendar timezone, Selection Day, Daily Slot states, recording methods, future-date rules, and a controllable Clock.
- Add transactional numbered SQL migrations and migration tooling for the Selection Ledger, Selection Corrections, reconciliation runs, and schema version history.
- Implement Postgres and in-memory Ledger adapters and Raindrop API and in-memory content-source adapters. Complete Raindrop scans use documented pagination and never depend on `lastUpdate` sorting.
- Implement the Reconciler and the minimum Slot Catalog behavior needed to resolve a dated Slot and today in all three states.
- Add documented operator commands: `ledger initialize`, `ledger reconcile`, and `ledger correct`.
- Add the authenticated internal reconcile endpoint. A lightweight GitHub Actions workflow calls it every 15 minutes; the endpoint and commands invoke the same Reconciler.
- Establish unit, adapter-contract, migration, CLI, and HTTP test seams. Automated tests use fakes and do not contact external services.

### Operator Safety

`daily-miku ledger initialize` is dry-run by default. It reports proposed legacy rows, conflicts, and duplicate identities; `--apply` is required to write. Applying the same approved import again is a no-op.

`daily-miku ledger reconcile` performs routine full-set reconciliation and reports inserted and already-known IDs plus run completeness. Overlapping runs are safe.

`daily-miku ledger correct RAINDROP_ID DATE --reason TEXT` is the only supported exception to normal insert-only dates. It records the old and new Selection Day, old and new recording method, reason, configured operator identity, and timestamp in append-only correction history. The resulting ledger row uses the `manual` recording method.

### Acceptance

- A fixed Clock and timezone produce deterministic Selection Days around UTC and local midnight boundaries.
- Empty, selected, and conflict Slots derive solely from ledger cardinality; no read writes or reconciles.
- Initialization dry-run is complete and deterministic, apply is transactional and idempotent, and accepted conflicts remain visible.
- Routine reconciliation inserts every unseen tagged Raindrop exactly once and preserves rows after tag removal or metadata changes.
- A correction is impossible without a reason and leaves an auditable before-and-after record.
- Failed or incomplete Raindrop scans do not claim a successful reconciliation run.
- The scheduler authenticates to the internal endpoint, duplicate invocations are harmless, and the recorded run history makes the 15-minute freshness target observable.
- Configuration failures are safe and explicit; tests, lint, type checks, and migrations pass from a clean checkout.

Milestone 2 depends on this milestone's domain interfaces, schema, configuration, and fake adapters being stable.

## Milestone 2: Polished Core Preview

Build the artwork-first daily experience and every operation needed to select, deliver, and email one Daily Miku. Work is sliced by surface but remains available only on the protected preview.

### Scope

- Complete core Slot Catalog selectors and bounded calendar ranges.
- Implement the Image Pipeline, controlled Blob adapter, validation and normalization, image provenance, withdrawal tombstones, and dated redirect outcomes.
- Add documented `image ingest` and `image withdraw` operator commands. Ingestion accepts local authorized raster bytes, requires an authorization note, validates and normalizes once, stores a content-addressed object, and updates the Raindrop cover. Withdrawal requires a reason and makes controlled delivery return `410`.
- Implement `/`, `/today`, and `/{date}` with the responsive Editorial Date Rail and complete selected, empty, and conflict treatments.
- Implement the dated Slot, today, latest, random, and range JSON contracts and the retained `/image/{date}` route.
- Implement `slot today`, `slot get`, and `doctor` CLI contracts.
- Implement durable Email Delivery storage, per-recipient reservations, retries, image-required messages, and the noon Asia/Shanghai GitHub Actions email workflow.
- Add local static typography and assets, semantic HTML, keyboard-visible focus, reduced-motion behavior, and layouts verified from 320 CSS pixels upward.

### Acceptance

- HTML, JSON, CLI reads, image delivery, and email preconditions return the same Slot state for the same date.
- Every HTTP status, error envelope, CLI exit code, and cache class in the core contracts has a deterministic test.
- Authorized images are decoded and type-validated before storage; invalid or upstream non-image bodies are never served as images.
- Blob keys are content-addressed and immutable, date redirects are mutable and short-cached, and withdrawal prevents delivery even when bytes remain cached or shared.
- Image commands do not claim or infer reproduction authorization; they persist the operator's supplied authorization basis and withdrawal reason.
- Selected, empty, and conflict pages meet the browsing model on desktop and mobile without JavaScript. Conflict never appears to select a winner.
- Email sends separate messages, discloses no recipient list, does not resend recorded successes without `--force`, and records partial outcomes for safe retry.
- `doctor` checks configuration, schema, Raindrop, Blob, and SMTP without changing durable state, leaving an object behind, or sending mail.
- Preview contract tests, accessibility checks, lint, type checks, and the full automated suite pass.

Milestone 3 depends on this milestone's controlled image and delivery behavior. No core surface is promoted independently.

## Milestone 3: Discovery, Reliability, And Cutover

Complete the public v2 contract, prove it in production-shaped preview infrastructure, and perform the irreversible atomic cutover.

### Scope

- Implement archive, search, and statistics Catalog behavior; archive and search JSON APIs; `/archive` and `/search`; and `archive list` CLI behavior.
- Finish the editorial archive grid, bounded month/range empty-state context, cursor behavior, conflict cards, and progressive enhancement.
- Add health and readiness behavior, reconciliation freshness reporting, structured dependency failures, request correlation, cache validators, bounded rate limits, and operational dashboards or alerts sufficient to enforce the release gates.
- Export and checksum the baseline manifest, initialize the production ledger, classify every legacy image, and record decisions for conflicts, duplicate identities, corrections, and image exceptions.
- Replace setup, API, CLI, email, deployment, logging, and operational documentation with v2 instructions and complete the cutover and recovery runbooks.
- Remove v1 handlers, alternate route implementations, obsolete dependencies, old command wiring, and the v1 email workflow in the promoted release artifact.
- Execute every gate and cutover step in the migration specification. Skip cutover-day email and enable v2 schedules only after production smoke checks and manual reconciliation succeed.

### Acceptance

- Archive pagination is stable newest-first; ranges preserve empty dates; search returns complete Slot groups; statistics distinguish slots from candidates.
- All public HTML, JSON, CLI, image, and email contracts pass against the protected preview with production-shaped isolated dependencies.
- Reconciliation normally begins within 15 minutes of a tag change, while alerts distinguish scheduler delay, incomplete scans, and dependency failures. The target is best-effort because GitHub Actions does not guarantee exact start time.
- Every v1-addressable date resolves to the approved Raindrop ID, accepted conflict, correction, or reviewed image exception.
- Migration apply is idempotent, schema version is verified, every legacy selected Slot has an image classification, and no unreviewed warning remains.
- Production configuration, pooled Postgres access, Blob access, SMTP, scheduler authentication, logs, monitoring, and a schema-compatible v2 recovery deployment are ready.
- Atomic promotion and all production smoke checks succeed; a manual reconciliation and its repeat are safe; tagging resumes; the next scheduled v2 email creates durable outcomes.
- V2 is the only deployed implementation and active workflow. Recovery uses a compatible v2 deployment or a fix forward, never v1.

This milestone completes Daily Miku v2 and closes the date-shift and broken-image bugs only after production verification demonstrates their replacement behavior.

## V2.1: Advanced Chronology

Three-dimensional, depth-based, or otherwise advanced chronological navigation belongs to v2.1. Begin with a throwaway prototype after v2 has stable production behavior and representative archive data. Production work is earned only through human review and must preserve normal links, all three Slot states, keyboard and reduced-motion access, acceptable mobile performance, and the non-3D archive path.

V2.1 is not a v2 release gate and is planned as a separate effort.

## Explicit Deferrals

The following do not enter the v2 milestones:

- User accounts, favorites, comments, reactions, moderation, and community features.
- An admin web application or public mutation API. Single-operator mutations use authenticated CLI commands.
- Replacement of Raindrop as authoritative content storage or replacement of manual `daily-miku` tagging.
- Production deployment platforms beyond Vercel.
- A separate frontend, Node build step, SPA, or framework islands.
- Exact tag-added timestamps, event history, or guarantees stronger than polling can support.
- Unrestricted image proxying, scraping, forged source headers, or unauthorized mirroring.
- Themes, social sharing, RSS, webhooks, GraphQL, WebSockets, offline/PWA support, and advanced visual effects.

## Implementation Issue Shape

Convert each milestone into small dependency-linked implementation issues rather than one milestone-sized branch. Prefer vertical slices that end at a testable interface: domain and migration foundations, one deep module at a time, then one delivery adapter at a time. Every issue states its upstream dependency, contract references, observable acceptance criteria, migration impact, and whether it is preview-safe. Cross-cutting cleanup belongs to the slice that makes the old path obsolete, not to a final undifferentiated rewrite task.
