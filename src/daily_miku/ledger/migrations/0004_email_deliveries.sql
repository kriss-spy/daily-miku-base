CREATE TABLE email_delivery_attempts (
    attempt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    selection_day DATE NOT NULL,
    recipient TEXT NOT NULL CHECK (length(trim(recipient)) > 0),
    forced BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    failure_code TEXT,
    CHECK ((status = 'pending') = (finished_at IS NULL))
);

CREATE UNIQUE INDEX email_delivery_one_pending_idx
    ON email_delivery_attempts (selection_day, recipient) WHERE status = 'pending';

CREATE INDEX email_delivery_success_idx
    ON email_delivery_attempts (selection_day, recipient) WHERE status = 'sent';
