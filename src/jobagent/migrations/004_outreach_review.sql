-- Recruiter-persona review of each outreach draft.
ALTER TABLE applications
    ADD COLUMN review_score SMALLINT,
    ADD COLUMN review_notes TEXT;
