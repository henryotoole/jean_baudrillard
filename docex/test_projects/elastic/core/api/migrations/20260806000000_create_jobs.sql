-- The deferred-job queue the `api.clock` core service writes and the
-- `api.worker` core service drains. Owned by this codebase because only
-- the codebase that owns a schema may write to it — which is why the
-- clock lives here (clock.md § The clock defers; it does not work).
--
-- Additive and backward compatible with the previous application
-- version: nothing that shipped before this migration reads or writes
-- `jobs`, so a rolling deploy or a rollback across it is safe.

-- migrate:up
CREATE TABLE IF NOT EXISTS jobs (
    id          uuid        PRIMARY KEY,
    name        text        NOT NULL,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz NULL,
    finished_at timestamptz NULL,
    error       text        NULL
);

-- The claim query's exact predicate and order: partial on the pending set
-- so the index stays small however much history accumulates.
CREATE INDEX IF NOT EXISTS jobs_pending_idx
    ON jobs (enqueued_at)
    WHERE started_at IS NULL;

-- migrate:down
DROP INDEX IF EXISTS jobs_pending_idx;
DROP TABLE IF EXISTS jobs;
