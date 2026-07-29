-- migrate:up
CREATE TABLE IF NOT EXISTS pings (
    id           uuid          PRIMARY KEY,
    payload      text          NOT NULL,
    created_at   timestamptz   NOT NULL DEFAULT now(),
    processed_at timestamptz   NULL
);

CREATE INDEX IF NOT EXISTS pings_unprocessed_idx
    ON pings (created_at)
    WHERE processed_at IS NULL;

-- migrate:down
DROP INDEX IF EXISTS pings_unprocessed_idx;
DROP TABLE IF EXISTS pings;
