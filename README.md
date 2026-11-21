# AI Job Search Agent

Finds jobs, scores each one against your resume with Claude or OpenAI, and tracks your applications in
PostgreSQL. Job pages that need a real browser are opened with Browserbase, or with Chromium on your
own machine.

```
sources ──► collect ──► dedupe + store ──► rule filters ──► LLM scoring   ──► shortlist + digest
(company job feeds over HTTP;          (jobs)        (location,     (job_matches)     (applications)
 any careers page via a browser)                      title, age)
```

The agent never applies for you. It shortlists strong matches, drafts emails and cover letters on
request, sends an email only when you tell it to, and records the status you set.

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
| `BROWSERBASE_API_KEY` (+ optional `BROWSERBASE_PROJECT_ID`) | `generic` sources, unless the browser is local | browserbase.com → Settings |
| `JOBAGENT_BROWSER=local` (optional) | open job pages in Chromium on this machine instead of Browserbase; no Browserbase key is needed, unless a job board names Browserbase for itself (see "A browser per job board") | |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (optional) | sending emails, saving Gmail drafts, the morning summary | a Google app password: myaccount.google.com/apppasswords |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional) | phone notifications | a bot from @BotFather |

The main model is set only in `.env`; nothing is hard-coded. Two optional cheaper models, for
reading job-site pages and for a quick first check of each job, are settings instead
(`matching.reader_model`, `matching.prescreen_model`; see "Spending less on AI"). To switch, change `LLM_MODEL` (and the
API key if you change provider). Claude calls use structured outputs and server-side refusal
fallback, so a declined request is retried on a fallback model.

## Configuring the search

Everything lives in `config.yaml` (see `config.example.yaml`):

- `search.locations` is preset for India, the UAE, Saudi Arabia, and Qatar (countries and major
  cities). Jobs with another location are dropped before scoring. A job with no location goes
  through, and the matcher decides from the description. A remote job goes through when it says
  only "Remote", names one of your places, or names a wide region such as "Worldwide" or "APAC";
  one tied to another country ("Remote, Brazil") is dropped.
- `search.include_title_keywords` and `exclude_title_keywords` are whole-word filters on the title.
- `search.min_salary_lpa` drops rupee jobs that state a salary below it (lakhs a year). Jobs with
  no stated salary are kept, and the matcher flags pay stated in another currency.
- `search.notes` is free text the matcher reads (relocation, visa, preferences).
- `matching.shortlist_min_score` auto-shortlists jobs at or above this score (default 75).
- `matching.max_jobs_to_score` caps LLM scoring calls per run.
- `matching.prescreen_model` (empty, so off) names a cheaper model that takes a quick first look at
  each job; only the jobs it does not rule out get the full scoring.
- `matching.reader_model` (empty, so off) names a cheaper model that reads the job-site pages.
- `matching.batch_scoring` (off) makes `jsa daily` send its scoring as one batch at half price, and
  `matching.batch_searches` (off) does the same for `jsa run`.
  These are described under "Spending less on AI" below.
- `matching.max_cost_per_run` (0, so off) stops a run once its AI calls have cost about this many
  US dollars.

Most of these can also be changed on the website, under Settings: **Search and limits**, and
**Sites** to switch a job site on or off. The page never rewrites `config.yaml`. What you change
there is kept in `config.overrides.yaml` beside it and applies to terminal commands too; delete
that file to go back to `config.yaml` alone.

### Sources

| kind | config | how it works |
|---|---|---|
| `greenhouse` | `board: <token>` from `boards.greenhouse.io/<token>` | public job board API |
| `lever` | `board: <company>` from `jobs.lever.co/<company>` | public postings API |
| `ashby` | `board: <name>` from `jobs.ashbyhq.com/<name>` | public posting API |
| `amazon` | nothing | amazon.jobs search feed, asked for your countries only |
| `microsoft` | nothing | Microsoft careers search, then one request per job that fits your rules |
| `workday` | `urls: [<careers address>]`, e.g. `https://adobe.wd5.myworkdayjobs.com/external_experienced` | the careers system shared by Salesforce, eBay, HP and many others; filtered to your countries |
| `generic` | `urls: [...]` any careers or search results page | Browserbase renders it, the LLM picks out the postings (URLs must exist on the page), then up to `max_detail_pages` job pages are opened per run. A job is scored only after its own page was read, and each page is opened once |

## Daily use

```bash
jsa run                          # collect + score; prints the top new matches
jsa run --source "Acme" --no-score
jsa score                        # score stored jobs a run left unscored, without searching again
jsa score --batch                # the same as one batch: half the price, answered later (Claude only)
jsa jobs --min-score 75          # best matches across all runs
jsa show 42 --full               # one job, with matched skills, gaps, red flags
jsa cover-letter 42              # draft, saved on the application record
jsa answers 42                   # short answers for the site's application form, to paste in yourself
jsa linkedin 42                  # a LinkedIn connection note and message for the recruiter, to send yourself
jsa cv 42                        # your resume arranged for this job, checked against it, as a PDF in resumes/
jsa prep 42                      # interview preparation: likely questions, points for each answer, what to revise
jsa replies                      # look in Gmail for answers to your emails (only when switched on)
jsa email                        # recruiter emails for your top shortlisted jobs
jsa email 94 96                  # ...or for specific jobs; --no-browse skips the live check
jsa status 42 applied --note "via referral"
jsa applications                 # your pipeline
jsa delete 42                    # remove a pasted post or HR address you added (asks first)
jsa digest --out digests/today.md
jsa runs                         # run history, tokens used, what it cost, and why a run was only partial
jsa backup                       # copy the database, and the code's history, into backups/
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
formatting; each email is shown on a sheet, with the recruiter review above it) and a Markdown copy.
Nothing is sent unless you add `--send`.

**Finding an address.** `jsa contacts` web-searches each shortlisted company's own site for a
published application address (Claude only). `contacts.py` then fetches the page and keeps the
address only if it is printed there and the page looks like that company's site; contact-database
sites are refused. General inboxes are stored but not emailed without `--general`.

**Pay.** The matcher returns `salary_estimate`: stated pay, or its own estimate marked as one.

**Reports.** `jsa gaps` counts the skills most often missing across scored jobs. `jsa progress`
summarises the week and shows which sources deliver. `jsa dedupe [--apply]` merges jobs stored twice.

**Spending less on AI.** Three settings, all off until you switch them on:

- *A quick first check.* Set `matching.prescreen_model` to a cheaper model (for Claude,
  `claude-haiku-5-5`). It reads each job first and rules out the clear misses: another profession,
  an internship for a senior engineer, an excluded industry. Those are stored with a score of 20
  and a summary starting "Quick check:", so they are not looked at again. Every other job, and any
  job the check failed on, gets the full scoring as before. Both models count toward
  `matching.max_tokens_per_run`.
- *A cheaper page reader.* Set `matching.reader_model` the same way. That model turns each job-site
  page into a list of jobs, which is mechanical work and takes a quarter to half of a run's tokens;
  scoring and emails keep the main model. A page it cannot read (a mistyped model name, an outage)
  is read by the main model instead, with a warning in the run's log, so no site is lost.
- *Batch scoring.* `jsa score --batch`, or `matching.batch_scoring: true` for `jsa daily`, sends the
  scoring requests as one batch (Claude only). A batch costs half and is answered later, usually
  within the hour. The run waits up to `matching.batch_wait_minutes` (120). If the answers are not
  back by then the run ends as `partial`, and the next run of any kind stores them. Jobs in a batch
  that is still running are not scored a second time.
- *Batch scoring for ordinary searches.* With `matching.batch_searches: true`, `jsa run` sends its
  scoring as a batch too and ends at once, without waiting. The scores are stored by the next
  run, or by `jsa score`; the page's Next steps says how many jobs are being scored.

**What a search cost.** Each run's summary, `jsa runs` and the Past searches table on the page give
the cost of its AI calls in US dollars, for each model. It is worked out from the token counts
(input, output, read from the cache, written to the cache, and those of a batch at half price)
and the price list in `src/jobagent/costs.py`. For a model that is not on the list, or when prices
change, give your own under `matching.prices` (`model: [input, output, cache read]`, in dollars per
million tokens). It is an estimate: the provider's bill is what counts.

**A browser per job board.** `JOBAGENT_BROWSER` names the usual browser. A `generic` source can
name its own with `browser: browserbase` or `browser: local` (in `config.yaml`, or under Settings,
**Sites**, on the website). Some boards refuse the browser on this machine and accept Browserbase,
so this keeps Browserbase time for just those boards: a browser is started only when a board that
names it is read, and the run's summary says how many of its browser minutes were on Browserbase.
If Browserbase will not start a browser, for example because its time is used up, those boards
are reported as not read and the run carries on.

**Backups.** `jsa backup` writes the whole database to `backups/jobagent-<date-time>.dump` and, when
the folder is a git repository, the code's history to `backups/code-<date-time>.bundle`. The newest
`backup.keep` (7) of each are kept. `jsa daily` makes one at its end unless `backup.daily` is
`false`; a backup that fails is reported and does not fail the run. To bring one back:
`pg_restore --clean --if-exists --no-owner --dbname jobagent backups/<file>.dump`. The copies are
on this Mac, so keep the folder somewhere else as well if a lost disk worries you. `pg_dump` and
`pg_restore` come with PostgreSQL.

**Notifications.** New jobs at or above `matching.notify_min_score` are sent to Telegram
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) or, failing that, emailed to you.

**Follow-ups.** When `--send` sends an email, the time is recorded. `jsa followups` lists the emails
that are `outreach.follow_up_days` (6) old with no follow-up yet; `jsa followups --send` sends the
stored follow-up text, and `--done <id>` records one you sent by hand.

**Replies.** Off unless `outreach.check_replies: true` (or **Look in Gmail for replies** under
Settings). Then `jsa replies`, **Check for replies** on the page and `jsa daily` look in the Gmail
inbox for answers to the emails that were sent. The inbox is opened read-only; only the sender,
the date and the subject line are read, and only of messages from an address that was written
to, messages under one of the sent subject lines, and delivery failures. A job a person answered
is marked Replied and one whose address refused the email is marked Not delivered; neither gets
a follow-up. An automatic reply is recorded but does not count as an answer. The job's status is
never changed: what a reply means is yours to say.

**Sending limits.** `--send` and `followups --send` stop at `outreach.max_sends_per_day` (10) emails a
day and wait `outreach.send_pause_seconds` (20) between them.

**CV variants.** `outreach.resume_variants` lists other CVs with keywords. The first variant whose
keyword appears in the job's title or description is attached instead of `resume_path`.

**Spending limits.** `matching.max_tokens_per_run` and `matching.max_browser_minutes_per_run` stop a run
when reached: remaining job boards are skipped and unscored jobs wait for the next run. The token
limit counts every model's tokens alike, so tokens of a cheaper model count in full although they
cost less. The run is
marked `partial` and says why. Claude calls mark the resume and template for prompt caching, so
repeated calls in one run read them at a fraction of the price.

**One job, one row.** The same job on two boards is stored once: it is matched on company name
(without "Pvt Ltd" and similar), the title's meaningful words, and country.

**Every morning.** `jsa daily` runs the search, writes `digests/<date>.md`, lists follow-ups due and,
when Gmail is configured, emails you one summary. `jsa schedule install --time 08:00` sets macOS to
run it daily; `jsa schedule status` and `jsa schedule remove` manage it.

**No terminal needed.** Double-click `Job Search.app` in the project folder, or run `jsa web`. A page
opens on this Mac only (http://127.0.0.1:8765) where every command is a button: search, draft, find
addresses, send, follow up, schedule the morning routine, import a resume, update the database,
change the search settings, switch a job site off, back up. Slow
commands run as one background task at a time, with live progress and a Stop button. GUIDE.md has the
full map of buttons to commands, WEBSITE_GUIDE.md explains how to use the website, and DESIGN.md
records how the page should look and read. `jsa send` sends saved drafts as they are (the page uses it).

**New jobs first.** The agent reads how long ago each job was posted ("2 days ago") from the
job boards. `search.max_age_days` (7 in the example) drops older postings, and lists, emails and
`jsa apply` go newest first. A job whose age the board does not show is kept and listed last.

**Jobs from a post.** `jsa add` takes text you paste, such as a LinkedIn post asking for CVs by
email (paste, then Ctrl-D, or pass a text file). It reads the role, company and email address,
scores the job and shortlists it; `jsa email <id> --send` then emails that address. Pasting a post
you added before updates that job; if its email has gone, the command says when and sends nothing.
`jsa add post.png` takes a picture of the post instead (PNG, JPG, WebP or GIF): the AI model reads
its text, the command prints it, and the job is added from it. On the website, a picture is pasted,
dropped or chosen in the **Add from a post** box, and its text fills the box for you to check
before you click **Add the job**; a tall screenshot is sent in pieces so the small print stays
readable.

**Sending.** `jsa email --send` sends each ready email from your Gmail with the CV from
`outreach.resume_path` attached, then marks the job applied so it is not emailed twice by accident (a deliberate second email goes
from the website, with **Send again** in that job's panel).
`jsa email --gmail-drafts` saves them to Gmail Drafts instead, for you to review and send. Both need
`GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (a Google app password) in `.env`. An email is ready only
when the posting shows a recipient address, is still open, and no placeholder is unfilled; other
jobs are listed with their apply link.

**Applying.** `jsa apply` opens each shortlisted job's page in your own browser, where you are
already signed in, and asks whether you applied; it records your answer. The click is yours
because job sites block automated browsers (Bayt and Google both refused one in testing).
`--dry-run` lists the jobs without opening them.

**General applications.** `jsa add-contacts` (or "Add HR addresses" on the website) puts HR addresses
that have no posting on the shortlist. Their emails are drafted from `general_email_template.txt`
and sent under the same daily limit as any other.

**LinkedIn messages.** `jsa linkedin <id>` (or **Write LinkedIn messages** in a job's panel) writes
a connection note, cut to LinkedIn's 300 characters at the end of a sentence, and a direct message
of 60 to 110 words, for the recruiter of that job. Both lead with the current title, years and the
skills the posting asks for, use the recruiter's name only when the posting or the draft names
them, and say when you can join (`outreach.notice_period`). They are saved with the job and copied
from the panel; you send them on LinkedIn yourself.

**Application answers.** `jsa answers <id>` (or **Write the answers** in a job's panel) writes
short answers to what a job site's form usually asks: why this role, why you, an introduction, key
skills, and years per skill where the resume makes them clear. They are written from the resume
and the posting only, and saved with the job. The panel shows them with a **Copy** button each,
next to your own details (name, email, phone, LinkedIn, when you can join, current and expected
salary, from `outreach` in the settings). You paste them into the site's form in your own
browser; the program fills in and submits nothing.

**A CV for one job.** `jsa cv <id>` (or **Write a CV for this job** in a job's panel) has the model
arrange your resume for that posting: every job you held, with the lines and skills this posting
asks for put first. Before anything is saved, what the model wrote is checked against the resume
text (`tailor.py`): a skill or an employer the resume does not name is dropped, a line with a
figure the resume does not give is dropped, and a changed job title or date is flagged. Each of
these is listed for you. The result is a plain one-column PDF in `resumes/job-<id>/`, named
`outreach.resume_filename`. An email keeps carrying your usual CV until you switch on **Attach it
to this job's email** in the job's panel.

**Interview preparation.** `jsa prep <id>` (or **Prepare for the interview**) writes what to revise
first, likely technical questions, likely questions about your own work with points for each
answer from the resume, and questions to ask. It is saved with the job.

**Site health.** Under Settings, **Sites**, a site whose last search failed, or that has listed no
job in its last three searches, is marked, and **Sites with a problem** lists them with one button
to switch them all off. It is read from what each run wrote down about each site.

**Saving a job from your own browser.** Settings has a **Save to Job Search** button to drag to the
bookmarks bar. Clicked on a job's page, it opens the Job Search page with the selected text (or
the whole page's), the title and the link in the **Add from a post** box. The text travels in the
part of the address after `#`, which no server is sent, and is removed from the address at once.
Nothing is added until you click **Add the job**.

**Cover letters.** `jsa cover-letter <id>` fills in `cover_letter_template.txt` for the job, the same
way as the email template below; remove the file or set `outreach.cover_letter_template_file: ""`
for a short built-in letter.

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
re-scored when its text changes. A job board's list gives just a title, a company and a place, so a
job from a board is not scored until its own page has been read. Each run opens up to
`max_detail_pages` such pages per board, only for jobs the rule filters would keep: first the ones
listed now, then ones listed in the last 7 days and still unread. The rest wait for the next run,
and a page is never opened twice. A board that lists nothing is not asked for job pages. Company
career sites are read six at the same time while the job boards are read one after another, which
brought 69 sites from about 194 seconds to 46 in one measurement. One failing source marks the run `partial` and the rest
continue. A run that is stopped (Ctrl-C, or **Stop** on the page) is also marked `partial`: it
shortlists what it had already scored and records where it ended. A run whose program was closed
before it could do that is given its end the next time runs are listed or a new run starts.
Details are in the `run_events` table.

To run it daily on a Mac, use `jsa schedule install` (see "Every morning" above). On another
system, schedule `jsa daily` with cron.

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

With `TEST_DATABASE_URL` set, `tests/test_page.py` also drives the website in a real browser: every
screen at a wide and a narrow window, the table, a job's panel, tasks, settings, live updates, and
what the page says when the resume or a database update is missing. It needs Playwright's Chromium
(`playwright install chromium`) and is skipped without it. No test calls a paid service, opens a
mailbox or starts a real `jsa` task.

## Layout

```
src/jobagent/
  cli.py        jsa commands
  pipeline.py   one run: collect → store → filter → score → shortlist
  sources/      greenhouse, lever, ashby (ats.py); amazon, microsoft, workday (big.py); generic (Browserbase + LLM)
  mailer.py     Gmail: save drafts or send
  actions.py    add a pasted job, add HR addresses, send a stored draft (shared by the CLI and the web page)
  contacts.py   check a found application address against the company's own page
  notifier.py   Telegram or email message about strong new matches
  web.py        local web app: JSON API, and a runner that executes jsa commands as tasks
  static/       the page: app.html, its stylesheet (app.css) and six scripts
                (base, chrome, lists, drawer, pages, actions)
  costs.py      what a run's AI calls cost, from token counts and a price list
  tailor.py     a CV for one job: checks what the model wrote against the resume, makes the PDF
  replies.py    a read-only look in Gmail for answers to the emails that were sent
  scheduler.py  macOS launchd job for `jsa daily`
  backup.py     pg_dump copy of the database, plus a git bundle of the code
  browser.py    Browserbase session (or local Chromium) behind one fetch() interface
  report.py     terminal tables, the Markdown digest, the HTML email preview
  resume.py     reads the resume file (PDF or text)
  config.py     .env secrets, config.yaml, and the settings changed on the page (config.overrides.yaml)
  llm.py        shared prompts + OpenAI provider: profile, match score, listing extraction, cover letter
  llm_anthropic.py  Claude provider for the same tasks
  filters.py    rule-based pre-filter
  db.py         Postgres queries and migration runner
  models.py     JobPosting and LLM output schemas
tools/
  take_screenshots.py   retakes every picture in screenshots/ on a demo copy with made-up data
```

## Documents

| File | For |
|---|---|
| `GUIDE.md` | every `jsa` command, and which button on the website does the same |
| `WEBSITE_GUIDE.md` | using the website, screen by screen |
| `screenshots/README.md` | the website in pictures: one for each screen and function, taken on a demo copy with made-up jobs. `tools/take_screenshots.py` retakes them all |
| `ARCHITECTURE.md` | how the parts fit together; `app-flow.html` and `architecture-live.html` are the same as pictures |
| `DESIGN.md` | how the website looks and reads: colours, type, spacing, wording |
