# Store Selection Dates In Raindrop Tags

Status: accepted

Daily Miku v2 stores each Selection Day in Raindrop as exactly one canonical `daily-miku-YYYY-MM-DD` tag instead of persisting date assignments in a Selection Ledger. This makes the operator's explicit date the source of truth, removes polling uncertainty and reconciliation infrastructure, and keeps a selected bookmark portable with its Raindrop metadata; Postgres remains only for operational state such as image provenance and Email Delivery idempotency, never as an authoritative or required index of Selection Days.

The suffix is a strict, zero-padded Gregorian date. Two or more bookmarks with the same dated tag form a Daily Slot conflict. A bookmark with more than one dated selection tag is invalid and blocks operations involving any of those dates until corrected. Tags matching the prefix but not the canonical form are reported by validation and do not assign a Slot. Adding, removing, or replacing a dated tag changes current publication state; Raindrop does not provide mutation history, so v2 does not claim an audit trail for Selection Corrections.

The former insert-only ledger decision in [Recording Selection Day](../research/selection-day.md) is superseded. A database-backed date cache or search index may be introduced later only as disposable derived data and must not become a second source of truth.

V2 initialization converts the existing generic-tag collection in place. For each bookmark carrying `daily-miku`, it derives the legacy Selection Day from that bookmark's current `lastUpdate` using the configured calendar timezone, removes `daily-miku`, and adds `daily-miku-YYYY-MM-DD`. This deliberately freezes the date pairing used by v1 into Raindrop metadata; later bookmark updates cannot move it. Initialization is idempotent and must report conflicts and likely duplicate identities before applying any tag changes.
