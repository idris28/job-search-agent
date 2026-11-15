-- What each search cost, a CV written for one job, interview preparation, and replies read from Gmail.
ALTER TABLE runs
    ADD COLUMN cost_usd NUMERIC(10,4),  -- what the AI calls of this search cost, when every price was known
    ADD COLUMN usage JSONB;             -- the tokens behind it, for each model and kind

ALTER TABLE applications
    ADD COLUMN tailored_cv JSONB,       -- the CV written for this job: its text, its file, whether the email carries it
    ADD COLUMN interview_prep JSONB,    -- likely questions with points for each answer, and what to revise
    ADD COLUMN reply_at TIMESTAMPTZ,    -- when the latest message from the address that was emailed arrived
    ADD COLUMN reply_kind TEXT,         -- reply | automatic | bounced
    ADD COLUMN reply_subject TEXT,
    ADD COLUMN replies_checked_at TIMESTAMPTZ;
