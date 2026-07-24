# Protected Preview Verification

This is a pending verification procedure, not evidence that preview was deployed or
approved. Complete it only after #28 produces the release artifact and #27 has a
review-complete baseline.

## Local Artifact Gate

Run `scripts/verify-local-release.sh` from a clean checkout. Record the commit, wheel
SHA-256, packaged schema version, test count, and command output. Do not substitute a
different build for preview deployment.

## Isolated Preview Gate

Use isolated Postgres, Blob, SMTP-shape, scheduler secret, logs, and test-channel
monitoring. Keep reconciliation, email, and monitoring schedules disabled. Apply
migrations only to isolated preview and prove a repeated apply is a no-op.

Record, without secrets:

- protected preview URL and deployment ID;
- release commit and wheel checksum;
- baseline manifest checksum and schema version;
- `doctor`, `/health`, `/ready`, freshness, request-correlation, cache, and rate-limit results;
- selected, empty, conflict, malformed, future, and dependency-failure HTML/JSON outcomes;
- every retained v1 date and controlled-image or approved exception outcome;
- manual reconciliation and duplicate invocation outcomes;
- email precondition checks using fake or explicitly isolated recipients, with no unintended mail;
- monitoring test-channel signals for endpoint, scheduler, image, and email failures;
- schema-compatible v2 recovery deployment ID and rehearsed smoke results.

## Verification Record

```yaml
status: pending
release_commit: null
artifact_sha256: null
baseline_sha256: null
schema_version: null
preview_deployment: null
recovery_deployment: null
gates: {}
unresolved_blockers: []
verified_by: null
verified_at: null
cutover_scheduling_approved: false
```

The verifier signs only observed results. Any failed or unavailable gate remains an
explicit blocker. This procedure never routes public traffic or authorizes #30.
