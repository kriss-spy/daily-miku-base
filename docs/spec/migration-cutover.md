# Daily Miku v2 Migration And Cutover

> **Current status:** production Raindrop selection-tag initialization completed on 2026-07-29 before application cutover. See the [observed initialization record](../selection-initialization-record.md). The remaining gates cover the v2 release artifact, images, preview verification, and public promotion; they must not initialize Selection Days into Postgres.

Decision for [Define the v2 migration and cutover](https://github.com/kriss-spy/daily-miku-base/issues/11), confirmed 2026-07-19.

## Principles

- V2 is verified on a protected Vercel preview before one atomic public cutover. There is no public beta and no route-by-route migration.
- Public cutover is a point of no return. Production never rolls back to v1; recovery rolls back between v2 deployments or fixes v2 forward.
- Existing generic-tag selections are converted once into canonical Dated Selection Tags using each bookmark's current `lastUpdate`. Initialization is idempotent, resumable, and gated by an operator-reviewed dry run.
- `https://dailymiku.dev/image/{date}` is the critical retained route. Every legacy image outcome is classified before cutover, even when the accepted outcome is that no image can be delivered.
- A brief selection freeze gives tag migration and cutover one stable boundary. Normal selection tagging continues throughout preview verification and pauses only for the final cutover window.
- Cutover ships one application. Obsolete v1 handlers, dependencies, routes, and operational documentation do not remain as dormant fallbacks.

## Deployment Shape

Deploy the complete v2 application to a protected Vercel preview connected to production-shaped but isolated operational dependencies and a non-mutating view of production Raindrop data. The preview uses the same build, migrations, configuration validation, ASGI entrypoint, and route rewrites intended for production. Email delivery remains disabled there.

The preview URL is temporary verification infrastructure, not a public API. Redesigned paths are not exposed as a parallel beta and no client is expected to migrate between two live definitions of a Daily Slot.

Public cutover promotes the verified v2 deployment and its configuration in one routing change. All HTML, JSON, image, and health routes move together so no request combines v1 date inference with v2 dated-tag semantics.

## Baseline Manifest

Before tag migration, export a dated, immutable migration manifest from a complete paginated Raindrop scan. It records enough evidence to repeat and review the migration without treating copied bookmark content as authoritative:

- Raindrop ID, current `lastUpdate`, Selection Day derived from that value in the configured timezone, proposed Dated Selection Tag, source URL, cover identity, and relevant tags for every current generic `daily-miku` match.
- Every date currently addressable by v1 and the Raindrop ID v1 would choose for that date.
- Duplicate Selection Days, duplicate IDs, normalized source URLs, and normalized cover identities.
- The observed v1 status for retained dated HTML and direct-image routes, without copying unvalidated response bodies into v2.

Store the manifest as a protected migration artifact, not application data. Raindrop remains authoritative for current title, description, source, tags, and cover metadata after migration.

## Dated Tag Migration

Migration follows [ADR 0001](../adr/0001-store-selection-dates-in-raindrop-tags.md):

1. Run `daily-miku selection initialize` in its default dry-run mode against every exact `daily-miku` match and persist its mutation plan. This step is complete for the production dataset recorded on 2026-07-29.
2. Compare the plan with the baseline manifest. Counts and Raindrop IDs must match, and each proposed `daily-miku-YYYY-MM-DD` tag must equal current `lastUpdate` converted to a calendar date in the configured timezone.
3. Review every duplicate identity, malformed tag, multi-date assignment, and Daily Slot conflict. Accepted conflicts remain visible and change `/image/{date}` to `409`.
4. Apply with `daily-miku selection initialize --apply`. Each bookmark update preserves unrelated tags, removes the obsolete generic `daily-miku` tag, and adds exactly one proposed Dated Selection Tag.
5. Persist each attempted mutation and Raindrop response in the protected migration report. A failure stops the run; rerunning skips bookmarks already in the desired state.
6. Complete a fresh full scan and require exact agreement with the approved manifest. A repeated dry run must propose no mutations.

Normal dated tagging may continue while preview verification proceeds. For final cutover, announce a brief operator freeze during which no generic or dated selection tags are added, removed, or replaced. Take the final complete snapshot, apply any approved differences, and keep the freeze in place through the first successful production validation after promotion.

Initialization does not rerun after its verified production apply. Later selections and corrections are direct Raindrop tag changes. The migration artifact preserves initialization evidence, but v2 does not claim ongoing tag mutation history.

## Image Readiness

The initializer or a companion migration command validates every legacy selected
Slot cover directly through the v2 image policy. Each cover receives one reviewed
validation: a direct cover requires a `2xx` response, `image/*` content type, and
a valid decode.

An unvalidated cover blocks cutover. This rule makes unknown failures
unacceptable without pretending every historical Pixiv, X, or other upstream
image can be made deliverable.

Validate cover evidence with `verify_cover_evidence`. Never use v1's proxied
bytes as trusted migration input.

## Verification Gates

Cutover is blocked until all of these gates pass on the protected preview:

- Automated tests, lint, type checks, SQL migrations, and configuration validation pass using the release artifact.
- Current Dated Selection Tags exactly match the approved migration report and a repeated apply is a no-op.
- Every legacy conflict and duplicate warning has a recorded operator decision.
- Every legacy selected Slot has a reviewed direct-cover validation (2xx,
  image/*, valid decode).
- All retained routes satisfy the v2 HTTP contract across selected, empty, conflict, malformed, future, and dependency-failure cases.
- Every v1-addressable date resolves to the same Raindrop ID in v2 unless a recorded correction or accepted conflict intentionally changes it.
- The CLI reads the same Slot states as HTTP, `doctor` passes, and email dry-run/precondition checks cannot send mail.
- Structured logs include request IDs and distinguish valid empty state from dependency failures.
- Operational database migrations, secrets, Blob access, SMTP configuration, monitoring, and the v2 rollback deployment are ready.
- Current operational, setup, API, CLI, email, and deployment documentation describes v2 only.

Byte-for-byte HTML, JSON, or image parity with v1 is not a gate. V2 preserves the capabilities and retained URL identified by the compatibility inventory while deliberately replacing v1's date inference, hidden conflict choice, error-as-success responses, and unsafe image forwarding.

## Cutover Runbook

1. Choose a low-traffic cutover day and announce that its daily email will intentionally be skipped.
2. Disable the v1 email workflow before its send and verify no v1 invocation remains in progress.
3. Begin the brief selection freeze and capture the final baseline manifest plus a current Dated Selection Tag validation report.
4. Verify the completed initialization record against current Raindrop tags. Do not rederive dates from the post-initialization `lastUpdate` values.
5. Complete the final direct-cover validation and retained-route checks against preview.
6. Apply production migrations and promote the verified v2 release with all public routes switched together. V2 schedules remain disabled.
7. Smoke-test `/`, one selected dated page, one empty Slot, `/archive`, one JSON Slot, `/health`, and representative `/image/{date}` success and failure outcomes on `dailymiku.dev`.
8. Run one complete selection validation. Verify exact manifest agreement and an identical repeat.
9. End the selection freeze, add or verify one dated selection through the normal operator workflow, and confirm it appears in the encoded Daily Slot without database synchronization.
10. Enable v2 email for the next scheduled day, not the cutover day.
11. Monitor route status, dependency errors, tag validation, image outcomes, and email delivery through the stabilization window.

The cutover record contains the release identifier, manifest and report checksums, migration versions, accepted conflicts and image exceptions, timestamps for freeze and promotion, smoke-check results, and the operator who approved promotion.

## Email Boundary

No email is sent on the cutover day. The v1 workflow is disabled before promotion, and v2 email remains disabled until public smoke checks and complete selection validation succeed. V2 begins on the next normal scheduled run with an empty v2 Email Delivery history; v1 sends are not backfilled or represented as v2 delivery records.

This intentional skip is preferable to either duplicate delivery or inventing idempotency evidence that v1 did not persist.

## Recovery After Cutover

V1 is not a recovery target. Once public traffic moves to v2:

- Roll back a faulty application release only to a previously verified v2 deployment whose schema compatibility is known.
- Never remove approved Dated Selection Tags as an application rollback mechanism.
- Disable only the affected v2 trigger or route when a safe v2 deployment rollback is unavailable, then fix forward.
- Preserve Email Delivery records, operational migration history, Blob mirrors, and cutover artifacts through every recovery action.
- Rerun contract smoke checks and complete tag validation before re-enabling disabled schedules.

Because there is no v1 fallback, failed preflight gates postpone promotion. They are not waived to meet a date.

## Removed And Redesigned URLs

The route treatment from the [v2 HTTP contract](http-contract.md) applies at cutover:

- `/image/{date}` remains stable.
- `/` and `/{date}` retain their purposes under v2 Slot semantics; `/today` becomes the specified redirect.
- `/archive` and `/search` replace v1 browsing URLs as new canonical pages.
- Removed v1 JSON and local-only routes are not redirected or emulated. They return the normal v2 `404` error envelope.
- `/list` is removed rather than kept as an alias; the current documentation and navigation point to `/archive`.

No temporary compatibility handler survives the cutover release.

## Code And Documentation Cleanup

The cutover release removes `api/hybrid.py`, alternate Vercel handlers, Mangum wiring, divergent local route implementations, and dependencies used only by v1. `api/index.py` is the sole ASGI entrypoint and `vercel.json` sends application routes to it.

Replace operational documentation in the same release. Keep the v1 compatibility inventory and other dated research as historical evidence, clearly labelled as such. Git and Vercel deployment history preserve the old implementation; dormant production code does not.

## Acceptance

Migration is complete when v2 is the only deployed application, the cutover runbook and all verification gates have passed, dated tagging has resumed, complete validation is healthy, the next scheduled v2 email has a durable outcome, and no obsolete v1 handler or active workflow remains. The subsequent practical roadmap may then treat the foundation rewrite as executable work rather than an unresolved migration risk.
