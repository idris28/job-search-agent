-- Where a found contact address came from, and the matcher's pay estimate.
ALTER TABLE applications
    ADD COLUMN contact_source TEXT,   -- page the address was read from; NULL = the posting itself
    ADD COLUMN contact_kind   TEXT;   -- recruiter | careers | general
ALTER TABLE job_matches ADD COLUMN salary_estimate TEXT;
