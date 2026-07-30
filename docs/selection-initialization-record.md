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

## Baseline Evidence (Direct-Cover Decision)

The canonical baseline follows the direct-cover decision: no mirror-first step,
no image classification into controlled mirror / no-image / withdrawal /
accepted failure. Cover validation requires a `2xx` response, `image/*` content
type, and a valid decode.

The historical full 123-entry initialization mapping was not retained. Current
Dated Selection Tags in Raindrop serve as the approved post-correction
canonical baseline.

Evidence recorded:
- 123 assignments
- Zero tag diagnostics (no malformed tags, no multi-date assignments)
- Cover validation criteria: 2xx, image/*, valid decode

Canonical baseline evidence checksum (SHA-256):
`0d338c0f33374fed654b7fb0d2fd997eb6e2a99a6c86999e49503e21d4df046b`

## Remaining Gates

- Finish issue #32 so every v2 read path and representation follows the dated-tag contract without constructing the obsolete Selection Ledger.
- Build one v2-only release artifact with reconciliation code and workflows removed.
- Verify that artifact on protected preview against current production-shaped Raindrop data and isolated operational dependencies.
- Validate legacy direct covers (2xx, image/*, valid decode) and complete retained-route checks before public promotion.
