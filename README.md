# AI Job Search Agent

Finds jobs, scores each one against your resume with Claude or OpenAI, and tracks your applications in
PostgreSQL. Job pages that need a real browser are opened with Browserbase.

```
sources ──► collect ──► dedupe + store ──► rule filters ──► LLM scoring   ──► shortlist + digest
(Greenhouse, Lever, Ashby APIs;        (jobs)        (location,     (job_matches)     (applications)
 any careers page via Browserbase)                    title, age)
```

The agent never applies for you. It shortlists strong matches, drafts cover letters on request,
and records the status you set.

## Setup

Requires Python 3.11+ and PostgreSQL 14+. On a Mac, the built-in `python3` is 3.9, which is too
old: install a newer one with `brew install python@3.12` and use `python3.12` below.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python --version                     # must print 3.11 or newer
python -m pip install --upgrade pip  # editable installs need pip 21.3+
pip install -e ".[dev]"
playwright install chromium          # only needed for JOBAGENT_BROWSER=local

cp .env.example .env                 # fill in your keys
cp config.example.yaml config.yaml   # add your sources
# Start Postgres. On a Mac, Homebrew is simplest (then DATABASE_URL=postgresql://localhost/jobagent):
#   brew install postgresql@16 && brew services start postgresql@16
#   export PATH="$(brew --prefix postgresql@16)/bin:$PATH" && createdb jobagent
# Or with Docker (Docker Desktop must be running):
docker run -d --name jobagent-db -p 5432:5432 -e POSTGRES_USER=jobagent \
  -e POSTGRES_PASSWORD=jobagent -e POSTGRES_DB=jobagent \
  -v jobagent-pg:/var/lib/postgresql/data postgres:16
#   docker compose up -d      (Docker Compose v2)
#   docker-compose up -d      (older standalone Compose)
jsa migrate
jsa profile import path/to/resume.pdf
```

### What you need to supply

| Variable | Needed for | Where to get it |
|---|---|---|
| `LLM_MODEL` | which model scores jobs, e.g. `claude-sonnet-5-5`, `claude-opus-5-5`, `gpt-5.4-mini` | |
| `LLM_PROVIDER` (optional) | `anthropic` or `openai`; inferred from `LLM_MODEL` when omitted | |
| `LLM_EFFORT` (optional) | Claude reasoning effort: `low` … `max` | |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | the key for your provider | console.anthropic.com → API Keys, or platform.openai.com/api-keys |
| `DATABASE_URL` | everything | e.g. `postgresql://localhost/jobagent` (Homebrew) |
| `BROWSERBASE_API_KEY` (+ optional `BROWSERBASE_PROJECT_ID`) | `generic` sources only | browserbase.com → Settings |
| `JOBAGENT_BROWSER=local` (optional) | use local Chromium instead of Browserbase while developing | |

The model is set only in `.env`; nothing is hard-coded. To switch, change `LLM_MODEL` (and the
API key if you change provider). Claude calls use structured outputs and server-side refusal
fallback, so a declined request is retried on a fallback model.

## Configuring the search

Everything lives in `config.yaml` (see `config.example.yaml`):

- `search.locations` is preset for India, the UAE, Saudi Arabia, and Qatar (countries and major
  cities). Jobs with another location are dropped before scoring. Remote jobs and jobs with no
  location go through, and the matcher decides from the description.
- `search.include_title_keywords` and `exclude_title_keywords` are whole-word filters on the title.
- `search.notes` is free text the matcher reads (relocation, visa, preferences).
- `matching.shortlist_min_score` auto-shortlists jobs at or above this score (default 75).
- `matching.max_jobs_to_score` caps LLM scoring calls per run.

### Sources

| kind | config | how it works |
|---|---|---|
| `greenhouse` | `board: <token>` from `boards.greenhouse.io/<token>` | public job board API |
| `lever` | `board: <company>` from `jobs.lever.co/<company>` | public postings API |
| `ashby` | `board: <name>` from `jobs.ashbyhq.com/<name>` | public posting API |
| `generic` | `urls: [...]` any careers or search results page | Browserbase renders it, the LLM picks out the postings (URLs must exist on the page), then up to `max_detail_pages` detail pages are visited |

## Daily use

```bash
jsa run                          # collect + score; prints the top new matches
jsa run --source "Acme" --no-score
jsa jobs --min-score 75          # best matches across all runs
jsa show 42 --full               # one job, with matched skills, gaps, red flags
jsa cover-letter 42              # draft, saved on the application record
jsa email                        # recruiter emails for your top shortlisted jobs
jsa email 94 96                  # ...or for specific jobs; --no-browse skips the live check
jsa status 42 applied --note "via referral"
jsa applications                 # your pipeline
jsa digest --out digests/today.md
jsa runs                         # run history, tokens used, errors
```

`jsa email` prepares recruiter outreach for your top shortlisted jobs. For each job it:
1. opens the live posting in Browserbase and checks the job is still open,
2. web-searches the company with Claude (recent news, engineering blog posts, a named recruiter or
   hiring manager, a careers email) and keeps the sources,
3. drafts a 110-160 word email following recruiter guidance: a short "Role | credential | skills"
   subject, a greeting by name, an opener that uses one sourced company fact, three quantified
   bullets mapped to the posting, a location/relocation/visa line, and one specific ask,
4. drafts a follow-up for 5-7 days later.

Output: `digests/emails-<date>.html` (open it in a browser; "Copy email" pastes into Gmail with
formatting) and a Markdown copy. Set `outreach.notice_period` and `outreach.resume_link` in
`config.yaml` to include them. Nothing is ever sent.

Re-running is cheap: jobs are deduplicated by company, title, and location, and a job is only
re-scored when its text changes. One failing source marks the run `partial` and the rest
continue. Details are in the `run_events` table.

To run it daily, schedule `jsa run && jsa digest --out digests/$(date +%F).md` with cron or a
CI scheduler.

## Database

Schema: `src/jobagent/migrations/001_init.sql`. Add new numbered `.sql` files for changes; `jsa
migrate` applies the ones not yet recorded in `schema_migrations`.

| table | holds |
|---|---|
| `profiles` | resume text and the structured profile extracted from it |
| `sources` | configured boards and pages |
| `jobs` | every distinct posting, deduplicated by fingerprint |
| `job_matches` | score, verdict, matched and missing skills, red flags per profile and job |
| `applications`, `application_events` | your status per job, with full history |
| `runs`, `run_events` | each run's counts, tokens, errors, and log |

## Tests

```bash
pytest                                            # unit tests
TEST_DATABASE_URL=postgresql://... pytest         # plus database and pipeline tests (wipes that DB)
```

## Layout

```
src/jobagent/
  cli.py        jsa commands
  pipeline.py   one run: collect → store → filter → score → shortlist
  sources/      greenhouse, lever, ashby (ats.py) and generic (Browserbase + LLM)
  browser.py    Browserbase session (or local Chromium) behind one fetch() interface
  llm.py        shared prompts + OpenAI provider: profile, match score, listing extraction, cover letter
  llm_anthropic.py  Claude provider for the same tasks
  filters.py    rule-based pre-filter
  db.py         Postgres queries and migration runner
  models.py     JobPosting and LLM output schemas
```
