# Job Search Agent: User Guide

## What `jsa` is

`jsa` stands for **job search agent**. It is the command you type in the Terminal to use this
project. Every action is `jsa` followed by a word, for example `jsa run` or `jsa email`.

The agent finds jobs for you, scores each one against your resume, writes recruiter emails in your
own format, reminds you when to follow up, and keeps track of what you applied to. It never applies
or emails without you asking it to.

## How it works

```
1. Collect      2. Filter        3. Score          4. Shortlist      5. Act
job boards  ->  location,    ->  AI compares   ->  score 75+     ->  email, apply,
and feeds       title, age       job to resume     is shortlisted    track status
```

1. **Collect.** `jsa run` reads every source listed in `config.yaml`. Job boards (Naukri,
   Naukrigulf, Bayt) are opened in a browser: Browserbase in the cloud, or Chromium on this Mac
   when `.env` has `JOBAGENT_BROWSER=local`. An AI model reads each page and picks out the jobs,
   including how long ago each was posted. Company career pages (Okta, Databricks, Amazon,
   Microsoft, the Workday companies and others) are read from their public feeds, with no browser.
   The same job found on two boards is stored once.
2. **Filter.** Jobs are dropped for free, before any scoring, if the location is not on your list,
   the title has an excluded word, the company is a bank, or the job is older than
   `search.max_age_days`.
3. **Score.** The AI model (Claude) compares each remaining job with your resume and gives a score
   from 0 to 100, with matched skills, gaps and red flags.
4. **Shortlist.** Jobs scoring 75 or more are shortlisted automatically.
5. **Act.** You draft or send recruiter emails, open jobs to apply on the site, send follow-ups
   when they are due, and record what happened.

A run stops early if it reaches the spending limits in `config.yaml` (AI tokens and browser
minutes); whatever is left waits for the next run. A run you stop is recorded the same way, and
the jobs it had already scored well enough are shortlisted.

Everything is stored in a PostgreSQL database on your Mac, so nothing is lost between runs and a
job is never scored or emailed twice.

### The parts

| Part | What it does |
|---|---|
| `.env` | Your secret keys (AI model, Browserbase, database, Gmail). Never shared. |
| `config.yaml` | Your search: roles, locations, keywords, job boards, email settings. |
| `email_template.txt` | The wording of your recruiter email. Text in `[brackets]` is filled in per job. |
| `cover_letter_template.txt` | Your cover letter, filled in the same way. |
| `general_email_template.txt` | The email for HR addresses that have no job posting. |
| `digests/` | Where email previews, daily digests and the daily log are written. |
| PostgreSQL database `jobagent` | Every job, score, application and draft. |

## Before you start

Run every command from the project folder. You can do that in one line:

```bash
cd "/path/to/job-search-agent" && .venv/bin/jsa <command>
```

In the rest of this guide the commands are written as `jsa <command>` for short.

Each job has a **number** (for example 343). Use it wherever a command takes a job, such as
`jsa show 343`.

## Using it without the terminal

Double-click **Job Search** (the app in the project folder; drag it to the Dock if you like). It
starts the program if it is not running and opens the page at http://127.0.0.1:8765 in your browser.
Everything `jsa` does is a button there. [WEBSITE_GUIDE.md](WEBSITE_GUIDE.md) is the full guide to
the website; this table maps its buttons to commands:

| On the page | What it does | Same as |
|---|---|---|
| **Find new jobs** (and the arrow next to it) | Searches every site, or one site, or collects without scoring; also runs the morning routine | `jsa run`, `jsa run --source`, `--no-score`, `jsa daily` |
| The six numbers across the top | How many jobs are at each stage; click one to see those jobs. While a task runs, a blue line moves under the numbers it is working on and a strip under them shows its latest message, with a Stop button | |
| **Actions**, in the menu on the left | One-click actions from any screen: add a post, add HR addresses, draft, look for addresses, save drafts to Gmail, send, follow up, morning routine, digest. **Light** and **Dark** at the bottom switch the look | `jsa add`, `jsa add-contacts`, `jsa email`, `jsa contacts`, `jsa send`, `jsa followups`, `jsa daily`, `jsa digest` |
| The filter bar and table | Filter by country, score, posting age and next step; search by name; click a column heading to sort; click a job to open it in a panel on the right | `jsa jobs` |
| **Shortlist** | Draft emails, look for addresses, save drafts to Gmail, send the ready emails | `jsa email`, `jsa contacts`, `jsa send --gmail-drafts`, `jsa send` |
| A job, once opened | Score, matched skills and gaps, the email draft to edit and send, cover letter, notes, history; an **Apply on the job site** button that opens the posting and asks afterwards whether you applied; buttons for applied, skipped, interview, offer, rejected | `jsa show`, `jsa status`, `jsa cover-letter`, `jsa apply` |
| **In progress**, **Follow-ups** | Applications under way (choose "Set aside" in the Stage filter for skipped and rejected jobs); follow-ups that are due, with a button to send them | `jsa applications`, `jsa followups` |
| **All matches** | Every scored job, with the score filter and a digest download | `jsa jobs`, `jsa digest` |
| **Add from a post** | Paste a LinkedIn post; it is read, scored and shortlisted | `jsa add` |
| The panels beside and below the table | One mark for each job on your lists, coloured by stage; your top matches; where the jobs are by country; and the next steps worth taking, each with a button | |
| **Insights** | Your week, the skills you miss most, which sites deliver | `jsa progress`, `jsa gaps` |
| **Activity** | The full output of the running or last task, and past searches with the reason any was only partly finished | `jsa runs` |
| **Settings** | Setup checklist, resume import, the morning routine, your three templates, duplicate jobs, a test notification, and **Stop Job Search** | `jsa profile import`, `jsa schedule`, `jsa dedupe`, `jsa notify-test`, `jsa migrate` |
| **All actions** (Cmd-K) | A searchable list of every action | |

Good to know:

- One task runs at a time. **Stop** ends it; what it already saved is kept, and a stopped search is
  listed in Activity as Partly finished.
- Sending always asks first. "Send ready emails" sends the drafts as they are saved, including your
  edits; it does not write them again.
- If the database needs an update after new features arrive, the page says so and offers one button.
- The page answers only on this Mac. Keys and passwords stay in `.env`; the page never shows them.
- The program keeps running after you close the tab. Stop it in Settings, or leave it.
- If Job Search does not open, the reason is at the end of `digests/web.log`.

## Commands

### Setup (used rarely)

| Command | What it does |
|---|---|
| `jsa migrate` | Creates or updates the database tables. Run it once after any update to the agent. Safe to run again: it says "Database is up to date." |
| `jsa profile import <resume.pdf>` | Reads your resume (PDF or text) and saves it as your profile. Run it again whenever your resume changes. Uses one AI call. |
| `jsa profile show` | Shows the profile the agent has for you. |

### Finding jobs

| Command | What it does |
|---|---|
| `jsa run` | Collects jobs from every job board in `config.yaml`, filters and scores them, and prints the best new ones. Uses AI calls, and Browserbase time unless the browser is local. |
| `jsa run --source "Bayt - Java"` | Runs only the one source with that name. |
| `jsa run --no-score` | Collects jobs but skips scoring, so no scoring calls are made. |
| `jsa score` | Scores stored jobs that were never scored, without reading any site again. A run scores at most `matching.max_jobs_to_score` jobs, so the rest wait; this picks them up, newest first. On the website: **Score waiting jobs**. |
| `jsa score --batch` | The same, sent as one batch: half the price, with the answers coming later, usually within the hour. Claude only. If they are not back within `matching.batch_wait_minutes` (120), the next search picks them up; the jobs are not scored twice. |
| `jsa add` | Adds a job from text you paste, such as a LinkedIn post asking for CVs by email. Paste the text, press Enter, then Ctrl-D. It reads the role, company and email address, scores the job and shortlists it. |
| `jsa add post.txt --url <link>` | The same, from a saved text file, keeping the post's link. |
| `jsa add-contacts hr.txt --country "Saudi Arabia"` | Adds HR addresses as general applications: one address per line, optionally with the employer's name (`Acme Gulf, hr@acme.sa`). Nothing is scored or sent. Each lands on the shortlist; `jsa email` then drafts it from `general_email_template.txt`. On the website: **Add HR addresses**. |

### Looking at jobs

| Command | What it does |
|---|---|
| `jsa jobs` | Lists scored jobs (score 70 or more), newest postings first. The "Posted" column shows age, such as `3h` or `2d`. |
| `jsa jobs --min-score 75 --limit 50` | Changes the minimum score and how many are listed. |
| `jsa jobs --untracked` | Hides jobs you have already acted on. |
| `jsa show 343` | Shows one job: score, summary, matched skills, gaps and red flags. |
| `jsa show 343 --full` | Also prints the full job description. |
| `jsa digest --out digests/today.md` | Writes a readable summary of the top matches to a file. Without `--out` it prints to the screen. |
| `jsa digest --run-id 3` | Only jobs first seen in run number 3. |
| `jsa runs` | Shows past runs: when, how many jobs found and scored, tokens used, and the reason a run failed or was only partly finished. |
| `jsa gaps` | Lists the skills job postings ask for most often that your resume doesn't show. `--days`, `--min-score` and `--limit` adjust it. |
| `jsa progress` | A summary of the last 7 days: shortlisted, applied, emails and follow-ups sent, interviews, your reply rate, and results per site. `--days 30` widens it. |
| `jsa dedupe` | Shows jobs that are stored more than once. Changes nothing. |
| `jsa dedupe --apply` | Merges those duplicates, keeping the score and status. |

### Emailing recruiters

| Command | What it does |
|---|---|
| `jsa email` | Drafts emails for your shortlisted jobs (up to 10, newest first) using `email_template.txt`. It checks each posting is still open, then writes a preview to `digests/emails-<date>.html`. Nothing is sent. |
| `jsa email 343` | Drafts for one job. You can list several numbers. |
| `jsa email --gmail-drafts` | Also saves each ready email into your Gmail Drafts with your CV attached, for you to review and send. |
| `jsa email --send` | Sends each ready email from your Gmail with your CV attached, then marks the job as applied so it is never emailed again. |
| `jsa email --no-browse` | Skips the live check of the posting (no browser use). |
| `jsa email --limit 5` | Changes how many shortlisted jobs are drafted. |
| `jsa contacts` | For shortlisted jobs with no address, searches each company's own website for a published application address. Uses AI web search. An address is kept only if it is really printed on that page. |
| `jsa contacts 343` | The same for specific jobs. |
| `jsa email --general` | Also uses a general inbox (such as `info@`) found by `jsa contacts`. Without it, general inboxes are never emailed. |
| `jsa cover-letter 343` | Writes a cover letter for one job and saves it with the application. It fills in your own letter from `cover_letter_template.txt` (text in [square brackets] is replaced for the job); without that file it writes a short built-in letter. |
| `jsa followups` | Lists emails sent `outreach.follow_up_days` or more days ago that have had no follow-up. |
| `jsa followups --send` | Sends the stored follow-up email for each one that is due. |
| `jsa followups --done 343` | Records a follow-up you sent yourself, so it stops being listed. |

An email is **ready** only when the posting shows an email address, the posting is still open, and
no blank in the template was left unfilled. Other jobs are listed with their link so you can apply
on the site.

`--gmail-drafts` and `--send` need three settings first: `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`
in `.env` (an app password from myaccount.google.com/apppasswords), and `outreach.resume_path` in
`config.yaml` pointing at your CV file.

### Applying and tracking

| Command | What it does |
|---|---|
| `jsa apply` | Opens each shortlisted job in your normal browser, one at a time, and asks whether you applied. Answer `y` (yes), `n` (not now), `s` (skip this job) or `q` (quit). |
| `jsa apply 94 96` | The same for specific jobs. |
| `jsa apply --dry-run` | Lists the jobs and links without opening anything. |
| `jsa status 343 applied --note "via referral"` | Sets a job's status yourself, with an optional note. |
| `jsa applications` | Lists every job you are tracking and its status. |
| `jsa delete 343` | Removes a pasted post or a general application you added yourself, for good. It asks first (`--yes` skips the question). It refuses a job that came from a job site, or one already emailed: set those aside with `jsa status 343 skipped`. On the website: **Delete entry**. |
| `jsa web` | Starts the page described in "Using it without the terminal" from a terminal instead of the Job Search app. Ctrl-C stops it. |
| `jsa send` | Sends the saved drafts as they are, edits included, without writing them again. `--gmail-drafts` saves them to Gmail Drafts instead; `--general` also uses a general inbox. |

The statuses are: `shortlisted`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`,
`skipped`.

### Running it every day

| Command | What it does |
|---|---|
| `jsa daily` | Runs the search, writes `digests/<date>.md`, lists follow-ups due, and emails you one summary if Gmail is set up. |
| `jsa backup` | Copies the whole database into the `backups` folder, and the code's history beside it. The newest 7 are kept. `jsa daily` does this by itself at its end. It prints the command that brings a backup back. On the website: Settings, **Back up now**. |
| `jsa schedule install --time 08:00` | Tells macOS to run `jsa daily` at that time every day. Run it from the project folder. |
| `jsa schedule status` | Shows whether the schedule is installed and when it runs. |
| `jsa schedule remove` | Removes the schedule. |

### Help

| Command | What it does |
|---|---|
| `jsa notify-test` | Sends you a test notification, to check Telegram or email is set up. |
| `jsa -h` | Lists all commands. |
| `jsa email -h` | Shows the options for one command. |
| `jsa -v run` | Runs a command with detailed log output, useful when something goes wrong. |

### Less common options

| Option | On | What it does |
|---|---|---|
| `--config <file>` | `run`, `score`, `email`, `add`, `followups`, `daily`, `backup`, `web` | Use a settings file other than `config.yaml`. |
| `--no-research`, `--no-review` | `email` | Skip the web research and the recruiter review. These only apply to the built-in email format; with your template they are already skipped. |
| `--port <number>` | `web` | Serve the page on another port (default 8765). |
| `--no-open` | `web` | Start the page without opening the browser. |

## A typical session

1. `jsa run` to collect and score fresh jobs.
2. `jsa jobs --min-score 75` to see the shortlist.
3. `jsa add` for any LinkedIn post you found yourself.
4. `jsa email --gmail-drafts` to draft the emails, then review and send them in Gmail.
5. `jsa apply` for the jobs that have no email address.
6. `jsa followups` to see which emails need chasing.
7. `jsa web` (or `jsa applications`) to see where everything stands. Or do all of this from the Job Search app, with no terminal.

Once `jsa schedule install` is set up, step 1 happens by itself each morning and a summary arrives
by email.

## Settings you are most likely to change

All in `config.yaml`. A number in brackets is what applies until you set your own. Most of them can
also be changed on the website, under Settings, **Search and limits**. What you change there is kept
in `config.overrides.yaml` beside `config.yaml`, which is never rewritten, and it applies to the
commands here too.

| Setting | Meaning |
|---|---|
| `search.roles`, `search.locations` | What you are looking for and where. |
| `search.max_age_days` | Only jobs posted within this many days (30; the example file uses 7). |
| `search.min_salary_lpa` | Lowest salary you accept, in lakhs a year (none). Jobs stating less are dropped; jobs that don't state pay are kept. |
| `search.exclude_company_keywords`, `exclude_industries` | Companies and industries to leave out (banking). |
| `matching.shortlist_min_score` | Score at which a job is shortlisted (75). |
| `outreach.notice_period` | When you can join; shown in emails. |
| `outreach.email`, `outreach.linkedin_url` | Contact details in the email sign-off. |
| `outreach.resume_path` | The CV file attached to emails. |
| `outreach.template_file` | The email wording file (`email_template.txt`). |
| `outreach.resume_variants` | Other CVs, each with keywords; attached when a job mentions one. |
| `outreach.follow_up_days` | Days after an email before a follow-up is due (6). |
| `outreach.max_sends_per_day`, `send_pause_seconds` | Sending limits: emails per day (10) and the wait between them (20 seconds). |
| `matching.max_tokens_per_run`, `max_browser_minutes_per_run` | Spending limits for one run. |
| `matching.notify_min_score` | You get a message when a new job scores this or more (85). |
| `matching.prescreen_model` | A cheaper AI model for a quick first check of each job (none, so off). Jobs it rules out skip the full scoring. For Claude: `claude-haiku-5-5`. |
| `matching.reader_model` | A cheaper AI model for reading job-site pages into lists of jobs (none, so off). Scoring and emails keep the main model. For Claude: `claude-haiku-5-5`. |
| `matching.batch_scoring`, `batch_wait_minutes` | Score the morning routine as one batch at half price (off), and how long a search waits for the answers (120 minutes). |
| `backup.daily`, `backup.keep`, `backup.folder` | Back up after the morning routine (on), how many backups are kept (7), and the folder they go to (`backups`). |
| `sources` | Job boards and company career pages to search. On the website each one has a switch under Settings, **Sites**. |

## Notifications

After each run, new jobs scoring `matching.notify_min_score` or more (85) are sent to you in one message. It goes to Telegram if
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are in `.env`; otherwise to your own Gmail address if
Gmail is set up; otherwise nothing is sent. To use Telegram, create a bot with @BotFather, send it
a message, and put its token and your chat id in `.env`. Check it with `jsa notify-test`.

## Estimated pay

Most postings don't state a salary, so the AI adds one line per job: the stated pay if there is
one, or its own estimate marked "(estimate)". It appears in `jsa show`, the digest and the web
page. Treat an estimate as a rough guide, not a fact; it never lowers a score on its own.

## What costs money

- **AI model calls** (Claude): `jsa contacts`, the "add a job" form on the web page, `jsa daily`, `jsa run` (reading pages and scoring), `jsa score`, `jsa email`, `jsa add`,
  `jsa cover-letter` and `jsa profile import`.
- **Browserbase time**: `jsa daily`, `jsa run`, and the live posting check in `jsa email`. None of it
  is used when `.env` has `JOBAGENT_BROWSER=local`: the pages open in Chromium on this Mac.

Three settings lower the AI cost of a search, and all are off until you switch them on. A cheaper
model can read the job-site pages (`matching.reader_model`) and can rule out the clear misses before
the full scoring (`matching.prescreen_model`), and the scoring can go as one batch at half price in
exchange for a wait (`jsa score --batch`, or `matching.batch_scoring` for the morning routine).

Everything else (`jobs`, `show`, `apply`, `status`, `applications`, `digest`, `runs`, `migrate`,
`backup`) is free.

## Which companies are searched

The agent searches only the sites listed under `sources:` in `config.yaml`. There are four kinds:

| Kind | What it covers | Needs a browser |
|---|---|---|
| `generic` | Job boards such as Naukri and Naukrigulf, by their search page | Yes |
| `greenhouse`, `lever`, `ashby` | Companies whose careers page runs on one of those three systems (Okta, Razorpay, CRED and others) | No |
| `amazon`, `microsoft` | Those two companies' own job feeds | No |
| `workday` | Any company whose careers address ends in `myworkdayjobs.com` (Salesforce, eBay, HP, Target and many others) | No |

To add a Workday company, open its careers page, copy the address, and add a line like the
existing ones:

```
  - {kind: workday, name: Adobe, urls: ["https://adobe.wd5.myworkdayjobs.com/external_experienced"]}
```

Amazon, Microsoft and Workday list thousands of jobs, so the agent asks them only for your
countries and reads the full description only for jobs that pass your title and age rules.
Google and Meta have no open job feed, so they are not covered.

Big companies name the same job differently. If a company's jobs are missing, check that
`include_title_keywords` has the words it uses: Amazon says "Software Development Engineer",
Adobe says "Computer Scientist", Salesforce says "Member of Technical Staff".

## Limits to know about

- When a posting does not name the company ("Unknown", "Confidential Company"), emails and cover
  letters leave the company out instead of writing that stand-in, and a draft that still contains
  it is flagged before sending.

- Job sites block automated browsers, so the agent cannot log in or click Apply for you. That is
  why `jsa apply` opens the page in your own browser.
- A site can also refuse to be read at all. Naukrigulf closes the connection to the browser on this
  Mac (it accepted Browserbase). The run then reports that site as not read and carries on with the
  rest; set `enabled: false` on it in `config.yaml` to stop the report.
- Most job board postings show no email address, so `--send` only covers the ones that do, plus
  posts you add with `jsa add`.
- Only the first few job pages per site are opened in full each run (`max_detail_pages` on each
  source); the newest postings go first.
- `--send` stops at the daily limit and waits between emails; both are settings
  (`outreach.max_sends_per_day`, `send_pause_seconds`).
- The daily schedule only runs while the Mac is awake.
- After an update that changes the database, run `jsa migrate` once, or click **Update the database**
  on the website; until then every command stops and says so.
- A job whose posting age the site does not show is kept and listed last.
