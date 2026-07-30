ALTER TABLE image_provenance
    DROP CONSTRAINT image_provenance_raindrop_id_fkey;

ALTER TABLE active_images
    DROP CONSTRAINT active_images_raindrop_id_fkey;

ALTER TABLE image_withdrawals
    DROP CONSTRAINT image_withdrawals_raindrop_id_fkey;

DROP TABLE selection_corrections;
DROP TABLE reconciliation_runs;
DROP TABLE selection_ledger;
