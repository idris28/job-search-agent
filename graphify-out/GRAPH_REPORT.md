# Graph Report - ai-job-search-agent-de61db  (2026-11-12)

## Corpus Check
- 1 files · ~20,679 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 569 nodes · 1326 edges · 28 communities (25 shown, 3 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 183 edges (avg confidence: 0.92)
- Token cost: 73,569 input · 0 output

## Community Hubs (Navigation)
- CLI Commands and Database
- Settings and Job Sources
- Rule Filters and Recency
- Run Pipeline and Tests
- Architecture Document
- Example Configuration
- Gmail Drafts and Sending
- User Guide Workflow
- Data Models and Prompts
- LLM Task Methods
- Email Template Sections
- Email Command Tests
- LLM Tests
- Lazy Browser Reopen
- README Command Overview
- Source Kinds and Layout
- Browser Interface
- Playwright Page Fetch
- Docker Postgres Setup
- OpenAI Provider
- Claude Provider
- Database Schema Docs
- Browser Session Tests
- Environment Settings
- Email Outreach Workflow
- Pasted Job Intake
- Package Root

## God Nodes (most connected - your core abstractions)
1. `JobPosting` - 43 edges
2. `BaseLLM` - 29 edges
3. `Settings` - 24 edges
4. `run_agent()` - 24 edges
5. `ConfigError` - 20 edges
6. `build_parser()` - 20 edges
7. `cmd_email()` - 20 edges
8. `SourceConfig` - 19 edges
9. `SourceContext` - 19 edges
10. `conn()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_template_file_setting()` --uses--> `OutreachPrefs`  [INFERRED]
  tests/test_email.py → src/jobagent/config.py
- `make_cfg()` --uses--> `AgentConfig`  [INFERRED]
  tests/test_pipeline.py → src/jobagent/config.py
- `test_generic_source_reads_age_and_visits_newest_first()` --uses--> `PageContent`  [INFERRED]
  tests/test_recency.py → src/jobagent/browser.py
- `test_generic_drops_hallucinated_urls_and_caps_detail_pages()` --uses--> `PageContent`  [INFERRED]
  tests/test_sources.py → src/jobagent/browser.py
- `test_apply_opens_each_job_and_records_the_answer()` --uses--> `Settings`  [INFERRED]
  tests/test_apply.py → src/jobagent/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Sections of the recruiter email template** — email_template_greeting, email_template_intro_line, email_template_key_skills, email_template_relevant_experience, email_template_location_relocation_availability, email_template_cv_and_call_ask, email_template_signoff [EXTRACTED 1.00]
- **Collect, Filter, Score, Shortlist, Act flow** — guide_collect_stage, guide_filter_stage, guide_score_stage, guide_shortlist_stage, guide_act_stage [EXTRACTED 1.00]
- **jsa email outreach steps: live check, research, draft, review** — readme_live_posting_check, readme_market_research_web_search, readme_builtin_email_format, readme_recruiter_review_loop, readme_email_template_mode [EXTRACTED 1.00]
- **jsa run pipeline: collect, store, filter, score, shortlist** — architecture_cli, architecture_pipeline, architecture_sources, architecture_browser, architecture_ai_model, architecture_rule_filters, architecture_database [EXTRACTED 1.00]
- **Four commands that meet only in the database** — architecture_jsa_run, architecture_jsa_add, architecture_jsa_email, architecture_jsa_apply, architecture_database [EXTRACTED 1.00]
- **Email draft, preview and guarded delivery flow** — architecture_cli, architecture_recruiter_email_drafting, architecture_preview, architecture_ready_criteria, architecture_gmail, architecture_application_status [EXTRACTED 1.00]

## Communities (28 total, 3 thin omitted)

### Community 0 - "CLI Commands and Database"
Cohesion: 0.07
Nodes (50): build_parser(), cmd_add(), cmd_applications(), cmd_apply(), cmd_cover_letter(), cmd_digest(), cmd_email(), cmd_jobs() (+42 more)

### Community 1 - "Settings and Job Sources"
Cohesion: 0.10
Nodes (16): ConfigError, MatchingPrefs, SourceConfig, JobPosting, AshbySource, GreenhouseSource, _iso(), LeverSource (+8 more)

### Community 2 - "Rule Filters and Recency"
Cohesion: 0.10
Nodes (21): SearchPrefs, _contains_any(), country_of(), reject_reason(), _norm(), age(), email_body_html(), emails_html() (+13 more)

### Community 3 - "Run Pipeline and Tests"
Cohesion: 0.14
Nodes (19): build_source(), FakeBrowser, FakeLLM, mock_http(), test_apply_opens_each_job_and_records_the_answer(), test_missing_env_is_a_clear_error(), test_parser_has_all_commands(), gh() (+11 more)

### Community 4 - "Architecture Document"
Cohesion: 0.11
Nodes (24): AI model (src/jobagent/llm.py, llm_anthropic.py), Application status tracking (set_application_status: applied or skipped), Architecture (ARCHITECTURE.md), Browser - Browserbase session or local Chromium (src/jobagent/browser.py), jsa commands (src/jobagent/cli.py), Data shapes (src/jobagent/models.py), Database - PostgreSQL (src/jobagent/db.py, migrations/), Full application flow (sequence diagram) (+16 more)

### Community 5 - "Example Configuration"
Cohesion: 0.06
Nodes (32): matching, concurrency, max_jobs_to_score, shortlist_min_score, outreach, email, linkedin_url, max_revisions (+24 more)

### Community 6 - "Gmail Drafts and Sending"
Cohesion: 0.08
Nodes (8): build_message(), _drafts_folder(), save_drafts(), send_messages(), FakeIMAP, test_gmail_draft_has_link_attachment_and_is_only_saved(), factory(), test_send_goes_through_gmail_smtp()

### Community 7 - "User Guide Workflow"
Cohesion: 0.12
Nodes (26): Act stage (email, apply, track status), Application statuses (shortlisted, applied, interviewing, offer, rejected, withdrawn, skipped), Browserbase cloud browser, Claude AI model, Collect stage (job boards read via cloud browser), .env secret keys file, Filter stage (location, title, bank, age rules), Job boards: Naukri, Naukrigulf, Bayt (+18 more)

### Community 8 - "Data Models and Prompts"
Cohesion: 0.18
Nodes (6): CandidateProfile, ExtractedListing, ExtractedListings, MatchResult, RecruiterReview, TemplateEmail

### Community 9 - "LLM Task Methods"
Cohesion: 0.18
Nodes (3): OutreachPrefs, BaseLLM, RecruiterEmail

### Community 10 - "Email Template Sections"
Cohesion: 0.15
Nodes (15): Conditional AI/LLM/agent experience bullet (PVR Triage Agent), CV attached and short call ask, Greeting (recruiter first name or Hiring Team), Intro line (title, years, employers, job title, company), Key skills line (6 to 8 skills the job asks for, backed by resume), Location, relocation and availability line, Recruiter email template, Relevant experience bullets (under 12 words each) (+7 more)

### Community 11 - "Email Command Tests"
Cohesion: 0.16
Nodes (10): unfilled_placeholders(), EmailLLM, filled(), TemplateLLM, test_email_fills_the_users_template(), test_email_shortlisted(), test_send_emails_only_ready_drafts_and_never_twice(), test_template_email_preview_keeps_paragraphs_and_line_breaks() (+2 more)

### Community 12 - "LLM Tests"
Cohesion: 0.17
Nodes (7): _claude_server(), FakeResponses, test_claude_content_research_uses_web_search_and_resumes_pause(), test_claude_refusal_raises(), test_claude_score_job_request_shape(), test_recruiter_email_fills_the_candidates_template_when_given(), test_score_job_sends_profile_prefs_and_clamps()

### Community 13 - "Lazy Browser Reopen"
Cohesion: 0.19
Nodes (6): LazyBrowser, _session_ended(), test_gives_up_when_the_new_session_ends_too(), test_other_errors_propagate(), test_reopens_dead_session(), fake_open()

### Community 14 - "README Command Overview"
Cohesion: 0.18
Nodes (14): AI Job Search Agent README, applications and application_events tables, cli.py (jsa commands), config.yaml search configuration, Daily scheduling with cron (jsa run && jsa digest), filters.py (rule-based pre-filter), jsa add (jobs from a pasted post), jsa apply (opens job in user's own browser) (+6 more)

### Community 15 - "Source Kinds and Layout"
Cohesion: 0.22
Nodes (14): ashby source (public posting API), browser.py (Browserbase or local Chromium behind one fetch() interface), Browserbase (remote browser for generic sources), generic source (Browserbase renders, LLM extracts postings), greenhouse source (public job board API), Source layout of src/jobagent, lever source (public postings API), llm_anthropic.py (Claude provider) (+6 more)

### Community 16 - "Browser Interface"
Cohesion: 0.19
Nodes (3): Browser, open_browser(), RunSummary

### Community 17 - "Playwright Page Fetch"
Cohesion: 0.19
Nodes (4): PlaywrightBrowser, FailingPage, test_failed_load_waits_for_the_error_page_before_reporting(), test_other_load_failures_are_reported_at_once()

### Community 18 - "Docker Postgres Setup"
Cohesion: 0.17
Nodes (11): environment, image, ports, volumes, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, services (+3 more)

### Community 19 - "OpenAI Provider"
Cohesion: 0.21
Nodes (3): make_llm(), OpenAILLM, test_provider_selection()

### Community 21 - "Database Schema Docs"
Cohesion: 0.22
Nodes (9): jsa migrate, PostgreSQL database jobagent, Database schema and migrations (001_init.sql, schema_migrations), db.py (Postgres queries and migration runner), job_matches table, jobs table, profiles table, runs and run_events tables (+1 more)

### Community 22 - "Browser Session Tests"
Cohesion: 0.24
Nodes (3): PageContent, Dying, FakeLazy

### Community 23 - "Environment Settings"
Cohesion: 0.28
Nodes (4): _env(), Settings, test_placeholder_keys_are_ignored(), test_env_vars()

### Community 24 - "Email Outreach Workflow"
Cohesion: 0.47
Nodes (4): Built-in email format (110-160 words, subject, bullets, ask, follow-up), jsa email recruiter outreach workflow, Live posting check (job still open), Recruiter market research web search (once per country per run)

### Community 25 - "Pasted Job Intake"
Cohesion: 0.40
Nodes (3): PastedJob, PasteLLM, test_add_job_from_pasted_post()

## Knowledge Gaps
- **18 isolated node(s):** `jobagent`, `Conditional AI/LLM/agent experience bullet (PVR Triage Agent)`, `Greeting (recruiter first name or Hiring Team)`, `Intro line (title, years, employers, job title, company)`, `Key skills line (6 to 8 skills the job asks for, backed by resume)` (+13 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 168 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JobPosting` connect `Settings and Job Sources` to `CLI Commands and Database`, `Rule Filters and Recency`, `Run Pipeline and Tests`, `Data Models and Prompts`, `LLM Task Methods`, `Email Command Tests`, `LLM Tests`, `Browser Interface`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `JobPosting` (e.g. with `upsert_job()` and `reject_reason()`) actually correct?**
  _`JobPosting` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `jobagent`, `Conditional AI/LLM/agent experience bullet (PVR Triage Agent)`, `Greeting (recruiter first name or Hiring Team)` to the rest of the system?**
  _18 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `CLI Commands and Database` be split into smaller, more focused modules?**
  _Cohesion score 0.06604938271604938 - nodes in this community are weakly interconnected._
- **Why does `BaseLLM` connect `LLM Task Methods` to `CLI Commands and Database`, `Settings and Job Sources`, `Rule Filters and Recency`, `Data Models and Prompts`, `OpenAI Provider`, `Claude Provider`, `Pasted Job Intake`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `BaseLLM` (e.g. with `OutreachPrefs` and `SearchPrefs`) actually correct?**
  _`BaseLLM` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Should `Settings and Job Sources` be split into smaller, more focused modules?**
  _Cohesion score 0.10040816326530612 - nodes in this community are weakly interconnected._