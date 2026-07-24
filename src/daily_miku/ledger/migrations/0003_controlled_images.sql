CREATE TABLE image_provenance (
    provenance_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raindrop_id BIGINT NOT NULL REFERENCES selection_ledger (raindrop_id),
    ingest_id UUID NOT NULL UNIQUE,
    digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    blob_key TEXT NOT NULL CHECK (blob_key = 'images/' || digest || '.png'),
    blob_url TEXT NOT NULL CHECK (blob_url LIKE 'https://%'),
    content_type TEXT NOT NULL CHECK (content_type = 'image/png'),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 4000000),
    width INTEGER NOT NULL CHECK (width > 0 AND width <= 8192),
    height INTEGER NOT NULL CHECK (height > 0 AND height <= 8192),
    source_format TEXT NOT NULL CHECK (source_format IN ('JPEG', 'PNG', 'WEBP')),
    authorization_note TEXT NOT NULL CHECK (length(trim(authorization_note)) > 0),
    operator TEXT NOT NULL CHECK (length(trim(operator)) > 0),
    ingested_at TIMESTAMPTZ NOT NULL,
    UNIQUE (provenance_id, raindrop_id)
);

CREATE INDEX image_provenance_identity_digest_idx
    ON image_provenance (raindrop_id, digest);

CREATE TABLE active_images (
    raindrop_id BIGINT PRIMARY KEY REFERENCES selection_ledger (raindrop_id),
    provenance_id BIGINT NOT NULL UNIQUE,
    FOREIGN KEY (provenance_id, raindrop_id)
        REFERENCES image_provenance (provenance_id, raindrop_id)
);

CREATE TABLE image_withdrawals (
    raindrop_id BIGINT PRIMARY KEY REFERENCES selection_ledger (raindrop_id),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    operator TEXT NOT NULL CHECK (length(trim(operator)) > 0),
    withdrawn_at TIMESTAMPTZ NOT NULL
);
