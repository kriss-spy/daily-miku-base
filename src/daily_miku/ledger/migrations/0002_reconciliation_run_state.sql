ALTER TABLE reconciliation_runs
ADD CONSTRAINT reconciliation_runs_terminal_state_check CHECK (
    (
        status = 'running'
        AND finished_at IS NULL
        AND error_code IS NULL
        AND error_message IS NULL
    )
    OR (
        status = 'complete'
        AND finished_at IS NOT NULL
        AND error_code IS NULL
        AND error_message IS NULL
    )
    OR (
        status IN ('incomplete', 'failed')
        AND finished_at IS NOT NULL
        AND error_code IS NOT NULL
    )
);
