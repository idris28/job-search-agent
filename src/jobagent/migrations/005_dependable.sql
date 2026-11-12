-- Follow-up tracking, a send log for the daily cap, and a key for matching the same job
-- across job boards.
ALTER TABLE applications
    ADD COLUMN outreach_sent_at  TIMESTAMPTZ,
    ADD COLUMN follow_up_sent_at TIMESTAMPTZ;

ALTER TABLE jobs ADD COLUMN match_key TEXT;
CREATE INDEX jobs_match_key_idx ON jobs (match_key);
