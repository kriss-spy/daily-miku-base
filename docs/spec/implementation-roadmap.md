# Daily Miku v2 Implementation Roadmap

Decision for [Build the practical v2 roadmap](https://github.com/kriss-spy/daily-miku-base/issues/10), confirmed 2026-07-19.

## Release Boundary

V2 is delivered through three cumulative milestones on a protected Vercel preview. A milestone is an independently verifiable implementation boundary, not a partial public release. Public traffic remains on v1 until the third milestone passes every migration gate and the complete v2 deployment is promoted atomically.

Implementation proceeds as small internal vertical slices. Each slice joins domain behavior to an adapter or delivery surface and is tested through its public interface. The milestone order is fixed by dependency: establish durable Slot semantics first, build the core experience over them, then add discovery and operational proof before cutover.

## Milestone 1: Operational Foundation

Build an operational vertical slice that can parse, validate, and read Raindrop-authoritative Daily Slots without presenting a polished public surface.

### Scope

- Establish the v2 package layout, supported dependencies, configuration validation, composition root, structured logging, and request IDs.
- Implement the pure domain core: strict Dated Selection Tag parsing, Daily Slot states, malformed and multi-date rules, future-date rules, configured "today", and a controllable Clock.
- Add transactional numbered SQL migrations only for operational image and Email Delivery state; no table stores or indexes Selection Days.
- Implement Raindrop API and in-memory selection/content adapters. Complete prefix scans use documented pagination and never depend on `lastUpdate` sorting.
- Implement the Selection Tag Catalog and the minimum Slot Catalog behavior needed to resolve a dated Slot and today in all three states.
- Add documented operator commands: `selection validate`, `selection initialize`, and `selection set`.
- Remove the internal reconciliation endpoint and scheduled reconciliation workflow. Selection state is read from Raindrop and has no synchronization job.
- Establish unit, adapter-contract, migration, CLI, and HTTP test seams. Automated tests use fakes and do not contact external services.

The operator safety and output contracts are defined in [the CLI and email contract](cli-email-contract.md). The roadmap does not introduce a second definition of those commands.

### Acceptance

- A fixed Clock and timezone produce deterministic "today" behavior while encoded Selection Days remain timezone-independent.
- Empty, selected, and conflict Slots derive solely from current canonical tags; no read persists date state.
- Strict parsing ignores malformed tags while validation reports them; a multi-date bookmark blocks every named Slot until corrected.
- Initialization derives each legacy date from current `lastUpdate` in the configured timezone; its dry-run is complete and deterministic, and apply is idempotent and resumable despite Raindrop's lack of multi-item transactions.
- Failed or incomplete Raindrop scans return dependency failure and never masquerade as empty Slots.
- Tag removal or replacement changes current publication state on the next uncached complete scan.
- Configuration failures are safe and explicit; tests, lint, type checks, and migrations pass from a clean checkout.

Milestone 2 depends on this milestone's domain interfaces, schema, configuration, and fake adapters being stable.

## Milestone 2: Polished Core Preview

Build the artwork-first daily experience and every operation needed to select, deliver, and email one Daily Miku. Work is sliced by surface but remains available only on the protected preview.

### Scope

- Complete core Slot Catalog selectors and bounded calendar ranges.
- Implement the Image Pipeline, controlled Blob adapter, validation and normalization, image provenance, withdrawal tombstones, and dated redirect outcomes.
- Implement the documented `image ingest` and `image withdraw` operator commands according to [the CLI and email contract](cli-email-contract.md).
- Implement `/`, `/today`, and `/{date}` with the responsive Editorial Date Rail and complete selected, empty, and conflict treatments.
- Implement the dated Slot, today, latest, random, and range JSON contracts and the retained `/image/{date}` route.
- Implement `slot today`, `slot get`, and `doctor` CLI contracts.
- Implement `email send` with its contracted ordered validation, current-tag scan, Slot, image, reservation, send, and recording preconditions; durable per-recipient storage and retries; image-required messages; and a disabled noon Asia/Shanghai GitHub Actions email workflow.
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
- Add health and readiness behavior, dated-tag validation reporting, structured dependency failures, request correlation, cache validators, bounded rate limits, and operational dashboards or alerts sufficient to enforce the release gates.
- Export and checksum the baseline manifest, apply reviewed Dated Selection Tags to legacy bookmarks, validate every legacy cover directly, and record decisions for conflicts, duplicate identities, tag corrections, and cover outcomes.
- Replace setup, API, CLI, email, deployment, logging, and operational documentation with v2 instructions and complete the cutover and recovery runbooks.
- Remove v1 handlers, alternate route implementations, obsolete dependencies, old command wiring, and the v1 email workflow in the promoted release artifact.
- Execute every gate and cutover step in the migration specification. Skip cutover-day email and enable the v2 email schedule only after production smoke checks and a complete tag validation succeed.

### Acceptance

- Archive pagination is stable newest-first; ranges preserve empty dates; search returns complete Slot groups; statistics distinguish slots from candidates.
- All public HTML, JSON, CLI, image, and email contracts pass against the protected preview with production-shaped isolated dependencies.
- Complete dated-tag scans return current assignments without a database synchronization interval; alerts distinguish incomplete scans, malformed tags, multi-date assignments, and dependency failures.
- Every v1-addressable date resolves to the same Raindrop ID unless a recorded correction or accepted conflict intentionally changes it.
- Every legacy selected Slot separately has a reviewed direct-cover validation; an invalid cover never excuses a selection mismatch.
- Tag migration apply is idempotent and resumable, the operational schema version is verified, every legacy selected Slot has a direct-cover validation, and no unreviewed warning remains.
- Production configuration, pooled operational Postgres access, Blob access, SMTP, logs, monitoring, and a schema-compatible v2 recovery deployment are ready.
- Atomic promotion and all production smoke checks succeed; repeated complete validation is safe; tagging resumes; the next scheduled v2 email creates durable outcomes.
- V2 is the only deployed implementation and active workflow. Recovery uses a compatible v2 deployment or a fix forward, never v1.

This milestone completes Daily Miku v2 and closes the date-shift and broken-image bugs only after production verification demonstrates their replacement behavior.

## V2.1: Advanced Chronology

Three-dimensional, depth-based, or otherwise advanced chronological navigation belongs to v2.1. Begin with a throwaway prototype after v2 has stable production behavior and representative archive data. Production work is earned only through human review and must preserve normal links, all three Slot states, keyboard and reduced-motion access, acceptable mobile performance, and the non-3D archive path.

V2.1 is not a v2 release gate and is planned as a separate effort.

## Explicit Deferrals

The following do not enter the v2 milestones:

- User accounts, favorites, comments, reactions, moderation, and community features.
- An admin web application or public mutation API. Single-operator mutations use authenticated CLI commands.
- Replacement of Raindrop as authoritative content and selection storage or replacement of manual Dated Selection Tagging.
- Production deployment platforms beyond Vercel.
- A separate frontend, Node build step, SPA, or framework islands.
- Exact tag-added timestamps or tag mutation history; the encoded date is an assignment, not an event timestamp.
- Unrestricted image proxying, scraping, forged source headers, or unauthorized mirroring.
- Themes, social sharing, RSS, webhooks, GraphQL, WebSockets, offline/PWA support, and advanced visual effects.

## Implementation Issue Shape

Convert each milestone into small dependency-linked implementation issues rather than one milestone-sized branch. Prefer vertical slices that end at a testable interface: domain and migration foundations, one deep module at a time, then one delivery adapter at a time. Every issue states its upstream dependency, contract references, observable acceptance criteria, migration impact, and whether it is preview-safe. Cross-cutting cleanup belongs to the slice that makes the old path obsolete, not to a final undifferentiated rewrite task.
