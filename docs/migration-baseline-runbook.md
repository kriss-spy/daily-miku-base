# Migration Baseline Runbook

> Selection-tag initialization was completed on 2026-07-29. See [Selection Initialization Record](selection-initialization-record.md). Retain this runbook for evidence review and recovery; do not rerun initialization as a normal operation.

This runbook creates evidence only. It does not promote a deployment or apply a
production migration.

1. Freeze the reviewed export window and record the configured calendar timezone.
2. Fetch every Raindrop page for the legacy generic tag and the dated-tag prefix. Retain IDs, `lastUpdate`, source
   and cover identities, and tags.
3. Capture every v1-addressable date with its selected Raindrop ID and retained image
   route status.
4. Run `selection initialize` without `--apply`; verify every proposed date is the
   captured `lastUpdate` converted in the configured timezone, then compare unique, proposed-tag,
   duplicate, conflict, malformed, multi-date, date, and ID facts against the export.
   After production initialization, do not run this command again. Instead pass the
   captured per-ID assignments and retained correction mapping to
   `verify_current_assignments`; it intentionally never reads post-mutation
   `lastUpdate`.
5. Record a decision for every duplicate and conflict. An accepted conflict must
   state that `/image/{date}` changes from a redirect to `409`.
6. Validate direct cover evidence for every selected identity. Record the
   operator, evidence, and review time in the protected manifest. Include the dated
   export's `baseline_date`; an undated artifact remains unresolved.
   Validate cover evidence with `verify_cover_evidence`; a valid cover requires a
   `2xx` response, `image/*` content type, and successful decode.
7. Build the canonical manifest with `build_baseline`. Do not proceed while
   `review_complete` is false or `unresolved` is non-empty. Write it once with
   `write_immutable`; review the adjacent SHA-256 file.
8. Apply the reviewed tag migration once during the authorized production cutover. A
   repeated dry run must propose zero mutations. Verify each retained date and exact
   cover outcome against a fresh complete Raindrop scan and the manifest.

## Direct-Cover Decision

The canonical baseline follows the direct-cover decision: no mirror-first step,
no image classification into controlled mirror / no-image / withdrawal /
accepted failure. Cover validation requires a `2xx` response, `image/*` content
type, and a valid decode.

The historical full 123-entry initialization mapping was not retained. Current
Dated Selection Tags in Raindrop serve as the approved post-correction
canonical baseline.

## Baseline Evidence Summary

- 123 assignments
- Zero tag diagnostics (no malformed tags, no multi-date assignments)
- Cover validation criteria: 2xx, image/*, valid decode

Production apply requires explicit operator authorization, a reviewed manifest, and
 the cutover runbook. Raindrop updates are not transactional across bookmarks; preserve
 the per-item report and resume only from verified current state. Never infer operator
 decisions or production outcomes from local tests.
