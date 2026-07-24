# Migration Baseline Runbook

This runbook creates evidence only. It does not promote a deployment or apply a
production migration.

1. Freeze the reviewed export window and record the configured calendar timezone.
2. Fetch every Raindrop page for the configured tag. Retain IDs, `lastUpdate`, source
   and cover identities, and tags.
3. Capture every v1-addressable date with its selected Raindrop ID and retained image
   route status.
4. Run `ledger initialize` without `--apply`; compare discovered, unique, proposed,
   duplicate, conflict, date, and ID facts against the export.
5. Record a decision for every duplicate and conflict. An accepted conflict must
   state that `/image/{date}` changes from a redirect to `409`.
6. Classify every selected identity as `validated_controlled_mirror`,
   `intentional_no_image`, `confirmed_withdrawal`, or `accepted_failure`. Record the
   operator, evidence, and review time in the protected manifest. Include the dated
   export's `baseline_date`; an undated artifact remains unresolved.
7. Build the canonical manifest with `build_baseline`. Do not proceed while
   `review_complete` is false or `unresolved` is non-empty. Write it once with
   `write_immutable`; review the adjacent SHA-256 file.
8. On isolated preview only, apply initialization twice. The second apply must insert
   zero rows. Verify each retained date and exact image outcome against the manifest.

Production apply requires explicit operator authorization, a reviewed target database,
and the cutover runbook. Never infer operator decisions or production outcomes from
local tests.
