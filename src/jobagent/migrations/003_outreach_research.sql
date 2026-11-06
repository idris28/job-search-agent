-- Company research notes and follow-up drafts from `jsa email`.
ALTER TABLE applications
    ADD COLUMN company_research  TEXT,
    ADD COLUMN follow_up_subject TEXT,
    ADD COLUMN follow_up_body    TEXT;
