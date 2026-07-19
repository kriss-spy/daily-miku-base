# Daily Miku v2 Migration And Cutover

Decision for [Define the v2 migration and cutover](https://github.com/kriss-spy/daily-miku-base/issues/11), confirmed 2026-07-19.

## Principles

- V2 is verified on a protected Vercel preview before one atomic public cutover. There is no public beta and no route-by-route migration.
- Public cutover is a point of no return. Production never rolls back to v1; recovery rolls back between v2 deployments or fixes v2 forward.
- The Selection Ledger is initialized once from a complete Raindrop snapshot. Initialization is idempotent, auditable, and gated by an operator-reviewed dry run.
- `https://dailymiku.dev/image/{date}` is the critical retained route. Every legacy image outcome is classified before cutover, even when the accepted outcome is that no image can be delivered.
- A brief selection freeze gives initialization and cutover one stable boundary. Normal `daily-miku` tagging continues throughout preview verification and pauses only for the final cutover window.
- Cutover ships one application. Obsolete v1 handlers, dependencies, routes, and operational documentation do not remain as dormant fallbacks.

## Deployment Shape

Deploy the complete v2 application to a protected Vercel preview connected to production-shaped but isolated dependencies. The preview uses the same build, migrations, configuration validation, ASGI entrypoint, and route rewrites intended for production. Scheduled reconciliation and email delivery remain disabled there; operators invoke them explicitly.

The preview URL is temporary verification infrastructure, not a public API. Redesigned paths are not exposed as a parallel beta and no client is expected to migrate between two live definitions of a Daily Slot.

Public cutover promotes the verified v2 deployment and its configuration in one routing change. All HTML, JSON, image, health, and internal routes move together so no request combines v1 selection semantics with v2 ledger state.

## Baseline Manifest

Before initialization, export a dated, immutable migration manifest from a complete paginated Raindrop scan. It records enough evidence to repeat and review the migration without treating copied bookmark content as authoritative:

- Raindrop ID, current `lastUpdate`, derived legacy Selection Day, source URL, cover identity, and relevant tags for every current `daily-miku` match.
- Every date currently addressable by v1 and the Raindrop ID v1 would choose for that date.
- Duplicate Selection Days, duplicate IDs, normalized source URLs, and normalized cover identities.
- The observed v1 status for retained dated HTML and direct-image routes, without copying unvalidated response bodies into v2.

Store the manifest as a protected migration artifact, not application data. Raindrop remains authoritative for current title, description, source, tags, and cover metadata after migration.

## Selection Ledger Initialization

Initialization follows the contract in [Recording Selection Day](../research/selection-day.md):

1. Run all database migrations against the target database and verify the expected schema version.
2. Run `initialize` in dry-run mode against the complete tagged set and persist its report.
3. Compare the report with the baseline manifest. Counts and Raindrop IDs must match; every derived legacy date must be explainable from the captured `lastUpdate` value in the configured timezone.
4. Review every duplicate identity warning. A warning may be accepted, but it cannot disappear into logs.
5. Resolve every legacy Daily Slot conflict or explicitly accept it as a visible v2 conflict. An accepted conflict changes `/image/{date}` to `409` and must be named in the cutover record.
6. Apply initialization with atomic conflict-safe inserts and rerun the dry run. The second report must propose no new rows.
7. Compare ledger rows with the approved report by Raindrop ID, Selection Day, and `legacy` recording method.

Normal tagging may continue while preview verification proceeds. For final cutover, announce a brief operator freeze during which no `daily-miku` tags are added or removed. Take the final complete snapshot, repeat the dry-run comparison, apply any still-unseen legacy rows, and keep the freeze in place through the first successful v2 reconciliation after promotion.

Initialization never reruns after public cutover. A later unseen bookmark is recorded by routine reconciliation as `observed`; a known historical correction uses the controlled manual-correction path rather than rewriting the import.

## Image Readiness

The initializer or a companion migration command evaluates every legacy selected Slot through the v2 image policy. Each receives one reviewed classification:

- A validated controlled Blob mirror is ready.
- The selected bookmark intentionally has no image.
- The image is confirmed withdrawn.
- The upstream image cannot be authorized, validated, or fetched and the resulting v2 failure is explicitly accepted.

An unclassified image blocks cutover. A reviewed exception does not. This rule makes unknown failures unacceptable without pretending every historical Pixiv, X, or other upstream image can be made deliverable.

For each controlled mirror, verify content type from decoded bytes, content-addressed naming, immutable object caching, and a successful `307` from `/image/{date}`. For each exception, verify the exact v2 status from the HTTP contract. Never use v1's proxied bytes as trusted migration input.

## Verification Gates

Cutover is blocked until all of these gates pass on the protected preview:

- Automated tests, lint, type checks, SQL migrations, and configuration validation pass using the release artifact.
- The ledger exactly matches the approved initialization report and a repeated apply is a no-op.
- Every legacy conflict and duplicate warning has a recorded operator decision.
- Every legacy selected Slot has a reviewed image classification.
- All retained routes satisfy the v2 HTTP contract across selected, empty, conflict, malformed, future, and dependency-failure cases.
- Every v1-addressable date resolves to the same Raindrop ID in v2 unless a recorded correction or accepted conflict intentionally changes it.
- The CLI reads the same Slot states as HTTP, `doctor` passes, and email dry-run/precondition checks cannot send mail.
- Structured logs include request IDs and distinguish valid empty state from dependency failures.
- Production migrations, secrets, Blob access, SMTP configuration, scheduler authentication, monitoring, and the v2 rollback deployment are ready.
- Current operational, setup, API, CLI, email, and deployment documentation describes v2 only.

Byte-for-byte HTML, JSON, or image parity with v1 is not a gate. V2 preserves the capabilities and retained URL identified by the compatibility inventory while deliberately replacing v1's date inference, hidden conflict choice, error-as-success responses, and unsafe image forwarding.

## Cutover Runbook

1. Choose a low-traffic cutover day and announce that its daily email will intentionally be skipped.
2. Disable the v1 email workflow before its send and verify no v1 invocation remains in progress.
3. Begin the brief selection freeze and capture the final baseline manifest.
4. Run the final initialization dry run, resolve any differences, apply it, and verify the idempotent no-op rerun.
5. Complete the final image classification and retained-route checks against preview.
6. Apply production migrations and promote the verified v2 release with all public routes switched together. V2 schedules remain disabled.
7. Smoke-test `/`, one selected dated page, one empty Slot, `/archive`, one JSON Slot, `/health`, and representative `/image/{date}` success and failure outcomes on `dailymiku.dev`.
8. Invoke one authenticated reconciliation manually. Verify its run, ledger effects, and idempotent repeat.
9. End the selection freeze, perform one more routine reconciliation, and verify any newly tagged bookmark is recorded as `observed` on the correct Selection Day.
10. Enable the v2 reconciliation schedule. Enable v2 email for the next scheduled day, not the cutover day.
11. Monitor route status, dependency errors, reconciliation freshness, image outcomes, and email delivery through the stabilization window.

The cutover record contains the release identifier, manifest and report checksums, migration versions, accepted conflicts and image exceptions, timestamps for freeze and promotion, smoke-check results, and the operator who approved promotion.

## Email Boundary

No email is sent on the cutover day. The v1 workflow is disabled before promotion, and v2 email remains disabled until public smoke checks and reconciliation succeed. V2 begins on the next normal scheduled run with an empty v2 Email Delivery history; v1 sends are not backfilled or represented as v2 delivery records.

This intentional skip is preferable to either duplicate delivery or inventing idempotency evidence that v1 did not persist.

## Recovery After Cutover

V1 is not a recovery target. Once public traffic moves to v2:

- Roll back a faulty application release only to a previously verified v2 deployment whose schema compatibility is known.
- Never reverse an applied Selection Ledger migration or delete ledger rows to match an older build.
- Disable only the affected v2 trigger or route when a safe v2 deployment rollback is unavailable, then fix forward.
- Preserve the Selection Ledger, Email Delivery records, migration history, Blob mirrors, and cutover artifacts through every recovery action.
- Rerun contract smoke checks and reconciliation before re-enabling disabled schedules.

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

Migration is complete when v2 is the only deployed application, the cutover runbook and all verification gates have passed, tagging has resumed, scheduled reconciliation is healthy, the next scheduled v2 email has a durable outcome, and no obsolete v1 handler or active workflow remains. The subsequent practical roadmap may then treat the foundation rewrite as executable work rather than an unresolved migration risk.
