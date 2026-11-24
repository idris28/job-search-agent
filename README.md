# AI Job Search Agent

A personal job search assistant. It reads job boards and company career sites every morning,
scores each job against your resume with Claude (or OpenAI), and keeps your shortlist,
applications and follow-ups in PostgreSQL. For the jobs worth acting on it writes the recruiter
email, the cover letter, the application-form answers, a LinkedIn message, a CV arranged for that
job and interview preparation. Everything runs on your own computer, from a local website or the
`jsa` command.

![The Shortlist screen of the website, with made-up jobs](screenshots/01-shortlist.png)

*The website's home screen. Every picture in this project shows a demo copy with made-up people and
employers; [screenshots/README.md](screenshots/README.md) has one for each screen and function.*

## What it does

- **Finds jobs.** Company career sites (Greenhouse, Lever, Ashby, Workday, Amazon, Microsoft) are
  read directly; job boards such as Naukri, Bayt or Cutshort are opened in a browser, either
  Chromium on your computer or Browserbase. A job posted as a LinkedIn post, a WhatsApp message, an
  email or even a screenshot can be added by pasting it.
- **Scores them.** Rule filters drop the clear misses for free (place, title, age, salary). The
  rest are scored 0 to 100 against your resume, with the skills you have, the ones you lack, red
  flags and an estimate of the pay. Strong matches land on your shortlist and, if you like, on
  your phone.
- **Helps you apply.** For one job: a recruiter email written in your own template, the
  application address found on the company's own site, a cover letter, short answers for the job
  site's form, a LinkedIn note and message, a CV arranged for that posting, and interview
  preparation. Emails go from your Gmail only when you say so.
- **Keeps track.** Every status change, email and follow-up is recorded. Follow-ups fall due by
  themselves, replies can be read from Gmail, and the Insights screen shows the skills postings
  ask for most that your resume lacks.
- **Keeps costs down.** Cheaper models can read pages and rule out misses, scoring can go as a
  half-price batch, and every search shows what it cost in US dollars, with a limit you set.

## What it never does

- It never applies on a job site, and never signs in to a job site or to LinkedIn. Job sites block
  automated browsers, so the click is always yours.
- It never sends an email you have not asked it to send, and never emails the same job twice by
  itself.
- It never tries to get past a site that refuses it: the site is reported as not read.
- It never invents facts about you. Emails, answers, messages and CVs use only what your resume
  says, and a CV written for one job is checked against your resume before it is saved.
- It looks in your Gmail only when you switch that on, and then only reads who wrote, when, and
  the subject line.
- Your keys, settings, backups and database stay on your computer: `.gitignore` keeps them out of
  the repository.

## Quick start

Requires Python 3.11+ and PostgreSQL 14+. On a Mac the built-in `python3` is too old: install a
newer one with `brew install python@3.12`.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip   # editable installs need pip 21.3+
pip install -e ".[dev]"
playwright install chromium           # the local browser: job boards, CV PDFs and the page tests

cp .env.example .env                  # then fill in your keys
cp config.example.yaml config.yaml    # then set your places, titles and sites
```

Start PostgreSQL, one of these ways:

```bash
# On a Mac, with Homebrew (then DATABASE_URL=postgresql://localhost/jobagent):
brew install postgresql@16 && brew services start postgresql@16
export PATH="$(brew --prefix postgresql@16)/bin:$PATH" && createdb jobagent

# Or with Docker Desktop running (then DATABASE_URL=postgresql://jobagent:jobagent@localhost/jobagent):
docker compose up -d
```

Then create the tables and import your resume:

```bash
jsa migrate
jsa profile import path/to/resume.pdf
```

### What goes in `.env`

| Variable | Needed for | Where to get it |
|---|---|---|
| `LLM_MODEL` | the model that scores jobs and writes, e.g. `claude-sonnet-5-5`, `claude-opus-5-5`, `gpt-5.4-mini` | |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | the key for your provider | console.anthropic.com → API Keys, or platform.openai.com/api-keys |
| `DATABASE_URL` | everything | e.g. `postgresql://localhost/jobagent` |
| `LLM_PROVIDER` (optional) | `anthropic` or `openai`; worked out from `LLM_MODEL` when left out | |
| `LLM_EFFORT` (optional) | Claude's reasoning effort: `low` … `max` | |
| `JOBAGENT_BROWSER=local` (optional) | open job boards in Chromium on this computer instead of Browserbase | |
| `BROWSERBASE_API_KEY` (+ optional `BROWSERBASE_PROJECT_ID`) | job boards read with Browserbase (see "A browser per job board") | browserbase.com → Settings |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (optional) | sending emails, Gmail drafts, the morning summary, reading replies | a Google app password: myaccount.google.com/apppasswords |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional) | phone notifications | a bot from @BotFather |

The main model is set only in `.env`; nothing is hard-coded. Claude calls use structured outputs
and server-side refusal fallback, so a declined request is retried on a fallback model.

## Using it

### The website (no terminal needed)

Double-click **Job Search.app** in the project folder (macOS), or run `jsa web`. A page opens at
http://127.0.0.1:8765, on this computer only, where every command is a button: search, score,
draft, find addresses, send, follow up, write a CV or LinkedIn message for a job, schedule the
morning routine, change the settings, switch a job site off, back up. Slow commands run as one
background task at a time, with live progress and a Stop button.

[WEBSITE_GUIDE.md](WEBSITE_GUIDE.md) explains it screen by screen, and [GUIDE.md](GUIDE.md) maps
every button to its command.

### The terminal

```bash
jsa run                          # search every site, score, and print the best new jobs
jsa run --source "Acme" --no-score
jsa score                        # score jobs a search left waiting, without searching again
jsa score --batch                # the same as one batch: half the price, answered later (Claude only)
jsa jobs --min-score 75          # best matches across all searches
jsa show 42 --full               # one job, with matched skills, gaps and red flags
jsa add post.txt --url <link>    # add a job from a post (text, or a picture of it)
jsa email                        # recruiter emails for your top shortlisted jobs
jsa email 94 96 --send           # ...for these jobs, and send the ready ones from your Gmail
jsa cover-letter 42              # a cover letter, saved with the job
jsa answers 42                   # short answers for the job site's application form
jsa linkedin 42                  # a LinkedIn connection note and message for the recruiter
jsa cv 42                        # your resume arranged for this job, checked against it, as a PDF
jsa prep 42                      # interview preparation: likely questions, points for each answer
jsa apply                        # open each shortlisted job in your browser and record what you did
jsa status 42 applied --note "via referral"
jsa followups --send             # send the follow-ups that are due
jsa replies                      # look in Gmail for answers to your emails (only when switched on)
jsa runs                         # past searches: counts, tokens, cost, and why one was only partial
jsa daily                        # the morning routine: search, digest, summary email, backup
jsa backup                       # copy the database, and the code's history, into backups/
```

`jsa --help` lists every command, and [GUIDE.md](GUIDE.md) explains each one.

## Configuring the search

Everything lives in `config.yaml` (start from `config.example.yaml`). Most of it can also be changed
on the website, under Settings: **Search and limits**, and **Sites** to switch a site on or off.
The page never rewrites `config.yaml`: what you change there is kept in `config.overrides.yaml`
beside it and applies to terminal commands too. Delete that file to go back to `config.yaml` alone.

- `search.locations` is preset for India, the UAE, Saudi Arabia and Qatar (countries and major
  cities). Jobs elsewhere are dropped before scoring. A job with no location goes through, and the
  matcher decides from the description. A remote job goes through when it says only "Remote",
  names one of your places, or names a wide region such as "Worldwide" or "APAC"; one tied to
  another country ("Remote, Brazil") is dropped.
- `search.include_title_keywords` and `exclude_title_keywords` are whole-word filters on the title.
- `search.max_age_days` (7 in the example) drops older postings.
- `search.min_salary_lpa` drops rupee jobs that state a salary below it (lakhs a year). Jobs with
  no stated salary are kept, and the matcher flags pay stated in another currency.
- `search.notes` is free text the matcher reads (relocation, visa, preferences).
- `matching.shortlist_min_score` shortlists jobs at or above this score (75).
- `matching.max_jobs_to_score` caps the scoring calls of one search.
- `matching.max_tokens_per_run`, `max_cost_per_run` and `max_browser_minutes_per_run` stop a search
  at a number of tokens, an amount in US dollars, or minutes of browser time.
- `matching.prescreen_model`, `reader_model`, `batch_scoring` and `batch_searches` spend less on AI;
  all are off until you set them (see "Scoring and what it costs").
- `outreach` holds your details for emails and forms, the CV files, the email templates, the
  sending limits and the follow-up wait; `backup` where and how many backups are kept.

### Sources

| kind | config | how it works |
|---|---|---|
| `greenhouse` | `board: <token>` from `boards.greenhouse.io/<token>` | public job board API |
| `lever` | `board: <company>` from `jobs.lever.co/<company>` | public postings API |
| `ashby` | `board: <name>` from `jobs.ashbyhq.com/<name>` | public posting API |
| `amazon` | nothing | amazon.jobs search feed, asked for your countries only |
| `microsoft` | nothing | Microsoft careers search, then one request per job that fits your rules |
| `workday` | `urls: [<careers address>]`, e.g. `https://adobe.wd5.myworkdayjobs.com/external_experienced` | the careers system shared by Salesforce, eBay, HP and many others; filtered to your countries |
| `generic` | `urls: [...]` any careers or search results page | a browser opens it, the AI model picks out the postings (their links must be on the page), then up to `max_detail_pages` job pages are opened per search. A job is scored only after its own page was read, and each page is opened once |

## How it works

```
sources ──► collect ──► dedupe + store ──► rule filters ──► AI scoring    ──► shortlist + digest
(company feeds over HTTP;     (jobs)        (place, title,   (job_matches)     (applications)
 job boards in a browser)                    age, salary)
```

Re-running is cheap. Jobs are stored once, matched on company, title and country, and a job is
scored again only when its text changes. A job board's list gives just a title, a company and a
place, so a job from a board is not scored until its own page has been read. Each search opens up
to `max_detail_pages` such pages per board, only for jobs the rule filters would keep: first the
ones listed now, then ones listed in the last 7 days and still unread. A page is never opened twice,
and a board that lists nothing is not asked for job pages.

Company career sites are read six at a time while the job boards are read one after another, which
brought 69 sites from about 194 seconds to 46 in one measurement. One failing site marks the search
`partial` and the rest carry on. A search that is stopped (Ctrl-C, or **Stop** on the page) is also
marked `partial`: it shortlists what it had already scored and records where it ended. Details are
in the `run_events` table. [ARCHITECTURE.md](ARCHITECTURE.md) describes how the parts fit together.

## Features in detail

### Finding jobs

**A browser per job board.** `JOBAGENT_BROWSER` names the usual browser. A `generic` source can name
its own with `browser: browserbase` or `browser: local` (in `config.yaml`, or under Settings,
**Sites**). Some boards refuse the browser on your computer and accept Browserbase, so this keeps
Browserbase time for just those boards. A browser is started only when a board that names it is
read, and the search's summary says how many minutes were on Browserbase. A site that refuses the
browser (an "Access Denied" answer, a bot check) is reported as not read, never read as empty, and
nothing tries to get past it.

**New jobs first.** The agent reads how long ago each job was posted ("2 days ago"). Lists, emails
and `jsa apply` go newest first; a job whose age the board does not show is kept and listed last.

**Jobs from a post.** `jsa add` takes the text of a post that asks for CVs by email (paste it, then
Ctrl-D, or pass a file). It reads the role, company and email address, scores the job and
shortlists it. `jsa add post.png` takes a picture of the post instead (PNG, JPG, WebP or GIF): the
AI model reads its text, prints it, and the job is added from it. On the website a picture is
pasted, dropped or chosen in the **Add from a post** box, and its text fills the box for you to check
before you click **Add the job**; a tall phone screenshot is sent in pieces so the small print stays
readable. Adding a post you added before updates that job instead of making a second one.

**Saving a job from your own browser.** Settings has a **Save to Job Search** button to drag to the
bookmarks bar. Clicked on a job's page, it opens the website with the selected text (or the whole
page's), the title and the link in the **Add from a post** box. The text travels in the part of the
address after `#`, which no server is sent, and is removed from the address at once. Nothing is
added until you click **Add the job**.

**Site health.** Under Settings, **Sites**, a site whose last search failed, or that has listed no
job in its last three searches, is marked. **Sites with a problem** lists only those, with one
button to switch them all off.

### Scoring and what it costs

**What a search cost.** Each search's summary, `jsa runs` and the Past searches table on the
website give the cost of its AI calls in US dollars, for each model. It is worked out from the token
counts (input, output, read from and written to the prompt cache, and those of a batch at half
price) and the price list in `src/jobagent/costs.py`. For a model not on the list, or when prices
change, give your own under `matching.prices` (`model: [input, output, cache read]`, in dollars
per million tokens). It is an estimate: the provider's bill is what counts.

**Spending less on AI.** Four settings, all off until you switch them on:

- *A quick first check.* Set `matching.prescreen_model` to a cheaper model (for Claude,
  `claude-haiku-5-5`). It reads each job first and rules out the clear misses: another profession,
  an internship for a senior engineer, an excluded industry. Those are stored with a score of 20
  and a summary starting "Quick check:", so they are not looked at again. Every other job, and any
  job the check failed on, gets the full scoring.
- *A cheaper page reader.* Set `matching.reader_model` the same way. That model turns each job-site
  page into a list of jobs, which is mechanical work and takes a quarter to half of a search's
  tokens; scoring and writing keep the main model. A page it cannot read is read by the main model
  instead, with a warning in the search's log.
- *Batch scoring.* `jsa score --batch`, or `matching.batch_scoring: true` for `jsa daily`, sends the
  scoring as one batch (Claude only). A batch costs half and is answered later, usually within the
  hour. The search waits up to `matching.batch_wait_minutes` (120); if the answers are not back by
  then, the next search of any kind stores them. Jobs in a batch still running are not scored twice.
- *Batch scoring for ordinary searches.* With `matching.batch_searches: true`, `jsa run` sends its
  scoring as a batch too and ends at once. The scores are stored by the next search, or by
  `jsa score`; the website's Next steps says how many jobs are being scored.

**Spending limits.** `matching.max_tokens_per_run`, `max_cost_per_run` and
`max_browser_minutes_per_run` stop a search when reached: remaining job boards are skipped and
unscored jobs wait for the next search, which is marked `partial` and says why. The dollar limit is
the truer one, because a cheaper model's tokens cost a small fraction of the main model's. Claude
calls mark the resume and template for prompt caching, so repeated calls in one search read them at
a fraction of the price.

**Pay.** The matcher returns the stated pay, or its own estimate marked as one.

### Applying

**Applying on a job site.** `jsa apply`, or **Apply on the job site** in a job's panel, opens the
posting in your own browser, where you are already signed in, and then asks whether you applied.
`--dry-run` lists the jobs without opening them.

**Application answers.** `jsa answers <id>` (or **Write the answers** in a job's panel) writes short
answers to what a job site's form usually asks: why this role, why you, an introduction, key
skills, and years per skill where the resume makes them clear. The panel shows them with a **Copy**
button each, next to your own details (name, email, phone, LinkedIn, when you can join, current and
expected salary, from `outreach` in the settings). You paste them in; nothing is submitted for you.

**A CV for one job.** `jsa cv <id>` (or **Write a CV for this job**) has the model arrange your
resume for that posting: every job you held, with the lines and skills this posting asks for put
first. Before anything is saved, the result is checked against your resume text (`tailor.py`): a
skill or employer the resume does not name is dropped, a line with a figure the resume does not
give is dropped, and a changed job title or date is flagged. Each of these is listed for you. The
result is a plain one-column PDF in `resumes/job-<id>/`, named `outreach.resume_filename`. A job's
email keeps your usual CV until you switch on **Attach it to this job's email** in its panel.

**CV variants.** `outreach.resume_variants` lists other CVs with keywords. The first variant whose
keyword appears in the job's title or description is attached instead of `resume_path`.

**Cover letters.** `jsa cover-letter <id>` fills in `cover_letter_template.txt` for the job, the
same way as the email template; remove the file, or set `outreach.cover_letter_template_file: ""`,
for a short built-in letter.

**LinkedIn messages.** `jsa linkedin <id>` (or **Write LinkedIn messages**) writes a connection note,
cut to LinkedIn's 300 characters at the end of a sentence, and a direct message of 60 to 110 words
for the recruiter of that job. Both lead with your title, years and the skills the posting asks
for, use the recruiter's name only when it is known, and say when you can join. You send them on
LinkedIn yourself.

**Interview preparation.** `jsa prep <id>` (or **Prepare for the interview**) writes what to revise
first, likely technical questions, likely questions about your own work with points for each
answer from your resume, and questions to ask.

### Recruiter emails

`jsa email` prepares outreach for your top shortlisted jobs. For each job it:

1. opens the live posting in the browser and checks the job is still open,
2. web-searches (Claude, once per country per run) what recruiters in that market say makes them
   reply: what they scan first, details they expect such as visa status and notice period, and
   common mistakes,
3. drafts a 110 to 160 word email: a "Role | credential | skills" subject, a first line with your
   title, years, stack and employers, 4 to 6 keywords from the posting, three quantified bullets,
   a location, relocation, visa and notice line, and one specific ask, plus a follow-up,
4. reviews the draft as a busy recruiter in that country (score 1 to 10, first impression, issues)
   and rewrites it until it scores `outreach.min_review_score` or `max_revisions` is reached.

The drafts are saved with each job, and also written to `digests/emails-<date>.html` (open it in a
browser; "Copy email" pastes into Gmail with formatting) and a Markdown copy.

**Your own wording.** When `email_template.txt` is in the folder you run `jsa` from, step 3 fills in
that template instead. Text in `[square brackets]` is replaced for each job: a label such as
`[Job Title]`, or a short description such as `[the skills this job asks for that my resume backs]`.
The job title and company come from the posting; your skills, experience and employers come from
your resume, chosen to match the posting; when you can join comes from `outreach.notice_period`.
The rest is kept as you wrote it. Steps 2 and 4 are skipped, so a template draft is one model call
per job. A placeholder left unfilled is flagged. Delete the file, or set
`outreach.template_file: ""`, to go back to the built-in format.

**Finding an address.** `jsa contacts` web-searches each shortlisted company's own site for a
published application address (Claude only). `contacts.py` then fetches the page and keeps the
address only if it is printed there and the page looks like that company's site; contact-database
sites are refused. General inboxes are stored but not emailed without `--general`.

**Sending.** `jsa email --send` (or **Send email** on the website) sends each ready email from your
Gmail with your CV attached, then marks the job applied so it is not emailed twice by accident; a
deliberate second email goes from the website, with **Send again** in that job's panel.
`jsa email --gmail-drafts` saves them to Gmail Drafts instead, for you to review and send. `jsa send`
sends saved drafts as they are, edits included. An email is ready only when there is a recipient
address, the posting is still open and no placeholder is unfilled. Sending stops at
`outreach.max_sends_per_day` (10) emails a day and waits `outreach.send_pause_seconds` (20)
between them.

**General applications.** `jsa add-contacts` (or **Add HR addresses** on the website) puts HR
addresses that have no posting on the shortlist. Their emails are drafted from
`general_email_template.txt` and sent under the same daily limit.

**Follow-ups.** `jsa followups` lists the emails that are `outreach.follow_up_days` (6) old with no
follow-up yet; `jsa followups --send` sends the stored follow-up text, and `--done <id>` records one
you sent by hand.

**Replies.** Off unless `outreach.check_replies: true` (or **Look in Gmail for replies** under
Settings). Then `jsa replies`, **Check for replies** on the website and `jsa daily` look in the
Gmail inbox for answers to the emails that were sent. The inbox is opened read-only; only the
sender, the date and the subject line are read, and only of messages from an address that was
written to, messages under one of the sent subject lines, and delivery failures. A job a person
answered is marked Replied and one whose address refused the email is marked Not delivered;
neither gets a follow-up. An automatic reply is recorded but does not count as an answer. The
job's status is never changed: what a reply means is yours to say.

### Every day

**Every morning.** `jsa daily` runs the search, writes `digests/<date>.md`, lists follow-ups due,
emails you one summary when Gmail is set up, and makes a backup. On a Mac,
`jsa schedule install --time 08:00` (or **Every morning** under Settings) runs it daily;
`jsa schedule status` and `jsa schedule remove` manage it. On another system, schedule `jsa daily`
with cron.

**Notifications.** New jobs at or above `matching.notify_min_score` are sent to Telegram
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) or, failing that, emailed to you.

**Reports.** `jsa gaps` counts the skills most often missing across scored jobs. `jsa progress`
summarises the week and shows which sources deliver. `jsa dedupe [--apply]` merges jobs stored
twice. `jsa digest --out <file>` writes the best matches as Markdown.

**Backups.** `jsa backup` writes the whole database to `backups/jobagent-<date-time>.dump` and, when
the folder is a git repository, the code's history to `backups/code-<date-time>.bundle`. The newest
`backup.keep` (7) of each are kept, and `jsa daily` makes one at its end unless `backup.daily` is
`false`. To bring one back:
`pg_restore --clean --if-exists --no-owner --dbname jobagent backups/<file>.dump`. The copies are on
your computer, so keep the folder somewhere else as well if a lost disk worries you. `pg_dump` and
`pg_restore` come with PostgreSQL.

## Database

The schema is built from the numbered files in `src/jobagent/migrations/`; `jsa migrate` applies the
ones not yet recorded in `schema_migrations`. Add a new numbered `.sql` file for each change.

| table | holds |
|---|---|
| `profiles` | resume text and the structured profile read from it |
| `sources` | the configured sites |
| `jobs` | every distinct posting, stored once |
| `job_matches` | score, verdict, matched and missing skills, red flags and pay, per profile and job |
| `applications`, `application_events` | your status per job with its full history, and what was written for it: email, follow-up, cover letter, answers, LinkedIn messages, CV, interview preparation, replies |
| `runs`, `run_events` | each search's counts, tokens, cost, errors and log |

## Tests

```bash
pytest                                            # the tests that need no database
TEST_DATABASE_URL=postgresql://... pytest         # all of them (over 200); wipes that database
```

With `TEST_DATABASE_URL` set, `tests/test_page.py` also drives the website in a real browser: every
screen at a wide and a narrow window, the table, a job's panel, tasks, settings, live updates, and
what the page says when the resume or a database update is missing. It needs Playwright's Chromium
and is skipped without it. No test calls a paid service, opens a mailbox or starts a real `jsa`
task. Never point `TEST_DATABASE_URL` at the database you use.

## Layout

```
src/jobagent/
  cli.py        jsa commands
  pipeline.py   one search: collect → store → filter → score → shortlist
  sources/      greenhouse, lever, ashby (ats.py); amazon, microsoft, workday (big.py); generic (browser + AI)
  browser.py    Browserbase session or local Chromium behind one fetch(); reports a site that refuses it
  llm.py        shared prompts and the OpenAI provider: profile, scoring, page reading, writing
  llm_anthropic.py  the Claude provider for the same tasks, plus batch scoring
  filters.py    rule-based filters before any AI call
  costs.py      what a search's AI calls cost, from token counts and a price list
  tailor.py     a CV for one job: checks what the model wrote against the resume, makes the PDF
  actions.py    add a pasted job, add HR addresses, send a stored draft (shared by the commands and the website)
  contacts.py   check a found application address against the company's own page
  mailer.py     Gmail: save drafts or send
  replies.py    a read-only look in Gmail for answers to the emails that were sent
  notifier.py   Telegram or email message about strong new matches
  web.py        the local website: JSON API, and a runner that executes jsa commands as tasks
  static/       the page: app.html, its stylesheet (app.css) and six scripts
                (base, chrome, lists, drawer, pages, actions)
  scheduler.py  the macOS launchd job for `jsa daily`
  backup.py     pg_dump copy of the database, plus a git bundle of the code
  report.py     terminal tables, the Markdown digest, the HTML email preview
  resume.py     reads the resume file (PDF or text)
  config.py     .env secrets, config.yaml, and the settings changed on the page (config.overrides.yaml)
  db.py         PostgreSQL queries and the migration runner
  models.py     JobPosting and the AI's structured answers
  migrations/   the numbered schema changes
tools/
  take_screenshots.py   retakes every picture in screenshots/ on a demo copy with made-up data
Job Search.app  double-click launcher for the website (macOS)
```

## Documents

| File | For |
|---|---|
| [WEBSITE_GUIDE.md](WEBSITE_GUIDE.md) | using the website, screen by screen |
| [GUIDE.md](GUIDE.md) | every `jsa` command, and which button on the website does the same |
| [screenshots/README.md](screenshots/README.md) | the website in pictures, one for each screen and function |
| [ARCHITECTURE.md](ARCHITECTURE.md) | how the parts fit together; `app-flow.html` and `architecture-live.html` show it as pictures |
| [DESIGN.md](DESIGN.md) | how the website looks and reads: colours, type, spacing, wording |
| [GITHUB_GUIDE.md](GITHUB_GUIDE.md) | putting the project on GitHub, step by step, and sending later changes |
