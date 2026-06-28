-- Aurora DSQL schema for OmniSwarm localization jobs.
--
-- Notes on DSQL compatibility:
--   * Primary keys must be declared at table-creation time (no ALTER ... ADD PK).
--   * Secondary indexes are created asynchronously (CREATE INDEX ASYNC).
--   * We store nested structures (markets/forks/agents/results/logs) as JSON
--     text for parity with the Python worker, which serializes via json.dumps.

CREATE TABLE IF NOT EXISTS localization_jobs (
    id            text PRIMARY KEY,
    campaign_id   text        NOT NULL,
    status        text        NOT NULL DEFAULT 'initializing',
    markets       text        NOT NULL DEFAULT '[]',
    video_key     text        NOT NULL,
    audio_key     text        NOT NULL,
    source_bucket text        NOT NULL,
    forks         text        NOT NULL DEFAULT '{}',
    agents        text        NOT NULL DEFAULT '{}',
    results       text        NOT NULL DEFAULT '{}',
    logs          text        NOT NULL DEFAULT '[]',
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Optional secondary indexes (DSQL builds these asynchronously).
-- Safe to ignore "already exists" errors on re-run.
CREATE INDEX ASYNC idx_jobs_status   ON localization_jobs (status);
CREATE INDEX ASYNC idx_jobs_campaign ON localization_jobs (campaign_id);
