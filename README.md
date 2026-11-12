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
2. web-searches (Claude, once per country per run) what recruiters in that market say makes them
   reply: what they scan first, expected details such as visa status and notice period, and common
   mistakes. Sources are kept,
3. drafts a 110-160 word email: a "Role | credential | skills" subject, a first line with your
   title, years, stack and employers, 4-6 keywords from the posting, three quantified bullets,
   location/relocation/visa/notice line, and one specific ask, plus a 5-7 day follow-up,
4. reviews the draft as a busy recruiter in that country (score 1-10, first impression, issues)
   and rewrites it until it scores `outreach.min_review_score` or `max_revisions` is reached.

Output: `digests/emails-<date>.html` (open in a browser; "Copy email" pastes into Gmail with
formatting; each card shows the recruiter review) and a Markdown copy. Nothing is ever sent.

**Follow-ups.** When `--send` sends an email, the time is recorded. `jsa followups` lists the emails
that are `outreach.follow_up_days` (6) old with no follow-up yet; `jsa followups --send` sends the
stored follow-up text, and `--done <id>` records one you sent by hand.

**Sending limits.** `--send` and `followups --send` stop at `outreach.max_sends_per_day` (10) emails a
day and wait `outreach.send_pause_seconds` (20) between them.

**CV variants.** `outreach.resume_variants` lists other CVs with keywords. The first variant whose
keyword appears in the job's title or description is attached instead of `resume_path`.

**Spending limits.** `matching.max_tokens_per_run` and `matching.max_browser_minutes_per_run` stop a run
when reached: remaining job boards are skipped and unscored jobs wait for the next run. The run is
marked `partial` and says why. Claude calls mark the resume and template for prompt caching, so
repeated calls in one run read them at a fraction of the price.

**One job, one row.** The same job on two boards is stored once: it is matched on company name
(without "Pvt Ltd" and similar), the title's meaningful words, and country.

**Every morning.** `jsa daily` runs the search, writes `digests/<date>.md`, lists follow-ups due and,
when Gmail is configured, emails you one summary. `jsa schedule install --time 08:00` sets macOS to
run it daily; `jsa schedule status` and `jsa schedule remove` manage it.

**Web page.** `jsa web` opens a page on this Mac only (http://127.0.0.1:8765) with your shortlist,
scores, email drafts and status, and buttons to mark a job applied or skipped.

**New jobs first.** The agent reads how long ago each job was posted ("2 days ago") from the
job boards. `search.max_age_days` (7 in the example) drops older postings, and lists, emails and
`jsa apply` go newest first. A job whose age the board does not show is kept and listed last.

**Jobs from a post.** `jsa add` takes text you paste, such as a LinkedIn post asking for CVs by
email (paste, then Ctrl-D, or pass a text file). It reads the role, company and email address,
scores the job and shortlists it; `jsa email <id> --send` then emails that address.

**Sending.** `jsa email --send` sends each ready email from your Gmail with the CV from
`outreach.resume_path` attached, then marks the job applied so it is never emailed twice.
`jsa email --gmail-drafts` saves them to Gmail Drafts instead, for you to review and send. Both need
`GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (a Google app password) in `.env`. An email is ready only
when the posting shows a recipient address, is still open, and no placeholder is unfilled; other
jobs are listed with their apply link.

**Applying.** `jsa apply` opens each shortlisted job's page in your own browser, where you are
already signed in, and asks whether you applied; it records your answer. The click is yours
because job sites block automated browsers (Bayt and Google both refused one in testing).
`--dry-run` lists the jobs without opening them.

**Your own wording.** When `email_template.txt` is in the folder you run `jsa` from, step 3
fills in that template instead of using the format above. Text in `[square brackets]` is replaced
for each job. A blank can be a label such as `[Job Title]` or a short description of what to
write, such as `[the skills this job asks for that my resume backs]`. The job title and company
come from the posting; your skills, experience and employers come from your resume, chosen to
match what that posting asks for, and when you can join comes from `outreach.notice_period`. The
rest of the template is kept as you wrote it. Steps 2 and 4 are skipped, since they exist to shape
wording that is now fixed, so a template draft is one model call per job. The preview flags any
placeholder that was left unfilled. Edit the file to change the wording; delete it, or set
`outreach.template_file: ""` in `config.yaml`, to go back to the built-in format.

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
  mailer.py     Gmail: save drafts or send
  web.py        local web page of the shortlist
  scheduler.py  macOS launchd job for `jsa daily`
  browser.py    Browserbase session (or local Chromium) behind one fetch() interface
  llm.py        shared prompts + OpenAI provider: profile, match score, listing extraction, cover letter
  llm_anthropic.py  Claude provider for the same tasks
  filters.py    rule-based pre-filter
  db.py         Postgres queries and migration runner
  models.py     JobPosting and LLM output schemas
```
