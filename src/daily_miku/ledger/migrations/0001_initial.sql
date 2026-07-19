CREATE TABLE selection_ledger (
    raindrop_id BIGINT PRIMARY KEY CHECK (raindrop_id > 0),
    selection_day DATE NOT NULL,
    recording_method TEXT NOT NULL
        CHECK (recording_method IN ('legacy', 'observed', 'manual')),
    first_observed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX selection_ledger_day_identity_idx
    ON selection_ledger (selection_day, raindrop_id);

CREATE TABLE selection_corrections (
    correction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raindrop_id BIGINT NOT NULL REFERENCES selection_ledger (raindrop_id),
    former_selection_day DATE NOT NULL,
    new_selection_day DATE NOT NULL,
    former_recording_method TEXT NOT NULL
        CHECK (former_recording_method IN ('legacy', 'observed', 'manual')),
    new_recording_method TEXT NOT NULL DEFAULT 'manual'
        CHECK (new_recording_method = 'manual'),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    operator TEXT NOT NULL CHECK (length(trim(operator)) > 0),
    corrected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX selection_corrections_identity_time_idx
    ON selection_corrections (raindrop_id, corrected_at);

CREATE TABLE reconciliation_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'complete', 'incomplete', 'failed')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    discovered_count INTEGER NOT NULL DEFAULT 0 CHECK (discovered_count >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    error_code TEXT,
    error_message TEXT,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (status = 'running' OR finished_at IS NOT NULL)
);

CREATE INDEX reconciliation_runs_started_at_idx
    ON reconciliation_runs (started_at DESC);
