# Selection Initialization Record

This record captures the production Raindrop selection-tag initialization performed on 2026-07-29 from branch `v2/dated-selection-tags`. It is observed migration evidence, not evidence that Daily Miku v2 has been deployed.

## Outcome

- The dry run discovered 123 bookmarks carrying the exact generic `daily-miku` tag.
- Each initial Selection Day was derived from current `lastUpdate` in `Asia/Shanghai` and encoded as `daily-miku-YYYY-MM-DD`.
- Apply updated all 123 bookmarks, preserved unrelated tags, and wrote no Selection Day data to Postgres.
- The first idempotency verification found zero remaining generic tags and zero proposed initializations.
- Initialization exposed 19 same-date conflicts. The operator supplied 49 reviewed date corrections, recorded in `scripts/apply-selection-corrections.py`.
- Each correction was refetched before mutation and verified after mutation.
- The final Raindrop Tags API check found zero dated tags with more than one bookmark.
- No malformed Dated Selection Tags or multi-date assignments were observed.

## Current Boundary

Production Raindrop data now uses Dated Selection Tags and no longer carries the generic selection tag. Public v2 deployment and cutover have not occurred. The currently deployed v1 application may therefore fail to discover selections; recovery is to complete and deploy the tag-backed v2 path, not to recreate a second date authority.

The correction script is idempotent and retained as the operator-reviewed mapping from initialized dates to final dates. It contains Raindrop IDs and date assignments only, no credentials or copied bookmark content.

## Remaining Gates

- Finish issue #32 so every v2 read path and representation follows the dated-tag contract without constructing the obsolete Selection Ledger.
- Build one v2-only release artifact with reconciliation code and workflows removed.
- Verify that artifact on protected preview against current production-shaped Raindrop data and isolated operational dependencies.
- Classify legacy image outcomes and complete retained-route checks before public promotion.
