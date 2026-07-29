# V2 Email Delivery

`daily-miku email send [--date DATE] [--force] [--json]` validates configuration,
scans current Dated Selection Tags, resolves one Daily Slot, requires
one controlled image, and sends a separate multipart message to each configured
recipient. Reports contain recipient counts, never addresses.

The scheduled GitHub Actions job runs at `04:00 UTC` but remains disabled unless
the repository variable `DAILY_MIKU_EMAIL_ENABLED` is `true`. Manual dispatch is
available for isolated preview verification.

## Idempotency

Each Selection Day and recipient is reserved durably before SMTP. Normal reruns
skip recorded successes; `--force` deliberately creates another attempt. Partial
successes remain recorded, so a normal retry sends only to recipients without a
successful outcome. A pending reservation also prevents concurrent processes from
sending the same recipient.

SMTP has no idempotency key. If SMTP accepts a message and the process dies before
the success transaction commits, the system cannot prove whether delivery occurred.
The attempt remains pending and automatic retries do not resend it. An operator must
review SMTP provider evidence before resolving that reservation or using `--force`.
This is the unavoidable SMTP-accepted-before-commit crash window.
