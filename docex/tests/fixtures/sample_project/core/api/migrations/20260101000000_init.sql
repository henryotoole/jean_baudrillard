-- Initial migration: a single trivial table the test_migrate integration
-- test can probe with `\dt`.
CREATE TABLE IF NOT EXISTS health (
    checked_at TIMESTAMP NOT NULL DEFAULT NOW()
);
