-- Recruiter outreach drafts produced by `jsa email`.
ALTER TABLE applications
    ADD COLUMN outreach_subject TEXT,
    ADD COLUMN outreach_body    TEXT,
    ADD COLUMN recruiter_name   TEXT,
    ADD COLUMN contact_email    TEXT,
    ADD COLUMN posting_checked_at TIMESTAMPTZ,
    ADD COLUMN posting_open     BOOLEAN;
