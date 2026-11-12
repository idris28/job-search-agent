# Graph Report - ai-job-search-agent-de61db  (2026-11-12)

## Corpus Check
- Corpus is ~19,764 words - fits in a single context window. You may not need a graph.

## Summary
- 536 nodes · 1268 edges · 22 communities (19 shown, 3 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 181 edges (avg confidence: 0.92)
- Token cost: 75,024 input · 0 output

## Community Hubs (Navigation)
- CLI Commands and Database
- Browser Sessions
- Settings and Job Sources
- Run Pipeline and Tests
- Example Configuration
- Gmail Drafts and Sending
- Email Preview Rendering
- User Guide Workflow
- Rule Filters and Recency
- LLM Task Methods
- Data Models and Prompts
- CLI and LLM Tests
- Email Template Sections
- README Command Overview
- Source Kinds and Layout
- Docker Postgres Setup
- OpenAI Provider
- Claude Provider
- Database Schema Docs
- Email Outreach Workflow
- Package Root

## God Nodes (most connected - your core abstractions)
1. `JobPosting` - 43 edges
2. `BaseLLM` - 29 edges
3. `Settings` - 24 edges
4. `run_agent()` - 24 edges
5. `cmd_email()` - 20 edges
6. `build_parser()` - 20 edges
7. `ConfigError` - 20 edges
8. `_conn()` - 19 edges
9. `SourceConfig` - 19 edges
10. `SourceContext` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_template_file_setting()` --uses--> `OutreachPrefs`  [INFERRED]
  tests/test_email.py → src/jobagent/config.py
- `test_generic_source_reads_age_and_visits_newest_first()` --uses--> `PageContent`  [INFERRED]
  tests/test_recency.py → src/jobagent/browser.py
- `test_generic_drops_hallucinated_urls_and_caps_detail_pages()` --uses--> `PageContent`  [INFERRED]
  tests/test_sources.py → src/jobagent/browser.py
- `test_parser_has_all_commands()` --calls--> `build_parser()`  [EXTRACTED]
  tests/test_cli.py → src/jobagent/cli.py
- `test_provider_selection()` --uses--> `ConfigError`  [INFERRED]
  tests/test_llm.py → src/jobagent/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Collect, Filter, Score, Shortlist, Act flow** — guide_collect_stage, guide_filter_stage, guide_score_stage, guide_shortlist_stage, guide_act_stage [EXTRACTED 1.00]
- **jsa email outreach steps: live check, research, draft, review** — readme_live_posting_check, readme_market_research_web_search, readme_builtin_email_format, readme_recruiter_review_loop, readme_email_template_mode [EXTRACTED 1.00]
- **Sections of the recruiter email template** — email_template_greeting, email_template_intro_line, email_template_key_skills, email_template_relevant_experience, email_template_location_relocation_availability, email_template_cv_and_call_ask, email_template_signoff [EXTRACTED 1.00]

## Communities (22 total, 3 thin omitted)

### Community 0 - "CLI Commands and Database"
Cohesion: 0.07
Nodes (50): build_parser(), cmd_add(), cmd_applications(), cmd_apply(), cmd_cover_letter(), cmd_digest(), cmd_email(), cmd_jobs() (+42 more)

### Community 1 - "Browser Sessions"
Cohesion: 0.06
Nodes (19): Browser, LazyBrowser, open_browser(), PageContent, PlaywrightBrowser, _session_ended(), _env(), Settings (+11 more)

### Community 2 - "Settings and Job Sources"
Cohesion: 0.10
Nodes (15): ConfigError, MatchingPrefs, SourceConfig, JobPosting, AshbySource, GreenhouseSource, _iso(), LeverSource (+7 more)

### Community 3 - "Run Pipeline and Tests"
Cohesion: 0.14
Nodes (19): RunSummary, build_source(), FakeBrowser, FakeLLM, mock_http(), test_apply_opens_each_job_and_records_the_answer(), gh(), make_cfg() (+11 more)

### Community 4 - "Example Configuration"
Cohesion: 0.06
Nodes (32): matching, concurrency, max_jobs_to_score, shortlist_min_score, outreach, email, linkedin_url, max_revisions (+24 more)

### Community 5 - "Gmail Drafts and Sending"
Cohesion: 0.08
Nodes (8): build_message(), _drafts_folder(), save_drafts(), send_messages(), FakeIMAP, test_gmail_draft_has_link_attachment_and_is_only_saved(), factory(), test_send_goes_through_gmail_smtp()

### Community 6 - "Email Preview Rendering"
Cohesion: 0.09
Nodes (17): TemplateEmail, unfilled_placeholders(), age(), email_body_html(), emails_html(), _h(), _paragraphs_html(), _trunc() (+9 more)

### Community 7 - "User Guide Workflow"
Cohesion: 0.12
Nodes (26): Act stage (email, apply, track status), Application statuses (shortlisted, applied, interviewing, offer, rejected, withdrawn, skipped), Browserbase cloud browser, Claude AI model, Collect stage (job boards read via cloud browser), .env secret keys file, Filter stage (location, title, bank, age rules), Job boards: Naukri, Naukrigulf, Bayt (+18 more)

### Community 8 - "Rule Filters and Recency"
Cohesion: 0.15
Nodes (15): SearchPrefs, _contains_any(), country_of(), reject_reason(), _norm(), job(), test_age(), test_company_exclusion() (+7 more)

### Community 9 - "LLM Task Methods"
Cohesion: 0.16
Nodes (4): OutreachPrefs, BaseLLM, RecruiterEmail, RecruiterReview

### Community 10 - "Data Models and Prompts"
Cohesion: 0.17
Nodes (7): CandidateProfile, ExtractedListing, ExtractedListings, MatchResult, PastedJob, PasteLLM, test_add_job_from_pasted_post()

### Community 11 - "CLI and LLM Tests"
Cohesion: 0.14
Nodes (9): test_missing_env_is_a_clear_error(), test_parser_has_all_commands(), _claude_server(), FakeResponses, test_claude_content_research_uses_web_search_and_resumes_pause(), test_claude_refusal_raises(), test_claude_score_job_request_shape(), test_recruiter_email_fills_the_candidates_template_when_given() (+1 more)

### Community 12 - "Email Template Sections"
Cohesion: 0.15
Nodes (15): Conditional AI/LLM/agent experience bullet (PVR Triage Agent), CV attached and short call ask, Greeting (recruiter first name or Hiring Team), Intro line (title, years, employers, job title, company), Key skills line (6 to 8 skills the job asks for, backed by resume), Location, relocation and availability line, Recruiter email template, Relevant experience bullets (under 12 words each) (+7 more)

### Community 13 - "README Command Overview"
Cohesion: 0.18
Nodes (14): AI Job Search Agent README, applications and application_events tables, cli.py (jsa commands), config.yaml search configuration, Daily scheduling with cron (jsa run && jsa digest), filters.py (rule-based pre-filter), jsa add (jobs from a pasted post), jsa apply (opens job in user's own browser) (+6 more)

### Community 14 - "Source Kinds and Layout"
Cohesion: 0.22
Nodes (14): ashby source (public posting API), browser.py (Browserbase or local Chromium behind one fetch() interface), Browserbase (remote browser for generic sources), generic source (Browserbase renders, LLM extracts postings), greenhouse source (public job board API), Source layout of src/jobagent, lever source (public postings API), llm_anthropic.py (Claude provider) (+6 more)

### Community 15 - "Docker Postgres Setup"
Cohesion: 0.17
Nodes (11): environment, image, ports, volumes, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, services (+3 more)

### Community 16 - "OpenAI Provider"
Cohesion: 0.21
Nodes (3): make_llm(), OpenAILLM, test_provider_selection()

### Community 18 - "Database Schema Docs"
Cohesion: 0.22
Nodes (9): jsa migrate, PostgreSQL database jobagent, Database schema and migrations (001_init.sql, schema_migrations), db.py (Postgres queries and migration runner), job_matches table, jobs table, profiles table, runs and run_events tables (+1 more)

### Community 19 - "Email Outreach Workflow"
Cohesion: 0.47
Nodes (4): Built-in email format (110-160 words, subject, bullets, ask, follow-up), jsa email recruiter outreach workflow, Live posting check (job still open), Recruiter market research web search (once per country per run)

## Knowledge Gaps
- **15 isolated node(s):** `jobagent`, `jsa profile import / show`, `jsa show`, `jsa runs`, `jsa cover-letter` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 164 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JobPosting` connect `Settings and Job Sources` to `CLI Commands and Database`, `Run Pipeline and Tests`, `Email Preview Rendering`, `Rule Filters and Recency`, `LLM Task Methods`, `Data Models and Prompts`, `CLI and LLM Tests`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `JobPosting` (e.g. with `upsert_job()` and `reject_reason()`) actually correct?**
  _`JobPosting` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `jobagent`, `jsa profile import / show`, `jsa show` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `CLI Commands and Database` be split into smaller, more focused modules?**
  _Cohesion score 0.06604938271604938 - nodes in this community are weakly interconnected._
- **Why does `BaseLLM` connect `LLM Task Methods` to `CLI Commands and Database`, `Settings and Job Sources`, `Email Preview Rendering`, `Rule Filters and Recency`, `Data Models and Prompts`, `OpenAI Provider`, `Claude Provider`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `BaseLLM` (e.g. with `OutreachPrefs` and `SearchPrefs`) actually correct?**
  _`BaseLLM` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Should `Browser Sessions` be split into smaller, more focused modules?**
  _Cohesion score 0.056866303690260134 - nodes in this community are weakly interconnected._