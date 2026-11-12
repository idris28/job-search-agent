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
(Browserbase)   title, age       job to resume     is shortlisted    track status
```

1. **Collect.** `jsa run` reads every source listed in `config.yaml`. Job boards (Naukri,
   Naukrigulf, Bayt) are opened in a cloud browser called Browserbase, and an AI model reads each
   page and picks out the jobs, including how long ago each was posted. Company career pages
   (Okta, Databricks and others) are read from their public feeds, with no browser. The same job
   found on two boards is stored once.
2. **Filter.** Jobs are dropped for free, before any scoring, if the location is not on your list,
   the title has an excluded word, the company is a bank, or the job is older than 7 days.
3. **Score.** The AI model (Claude) compares each remaining job with your resume and gives a score
   from 0 to 100, with matched skills, gaps and red flags.
4. **Shortlist.** Jobs scoring 75 or more are shortlisted automatically.
5. **Act.** You draft or send recruiter emails, open jobs to apply on the site, send follow-ups
   when they are due, and record what happened.

A run stops early if it reaches the spending limits in `config.yaml` (AI tokens and browser
minutes); whatever is left waits for the next run.

Everything is stored in a PostgreSQL database on your Mac, so nothing is lost between runs and a
job is never scored or emailed twice.

### The parts

| Part | What it does |
|---|---|
| `.env` | Your secret keys (AI model, Browserbase, database, Gmail). Never shared. |
| `config.yaml` | Your search: roles, locations, keywords, job boards, email settings. |
| `email_template.txt` | The wording of your recruiter email. Text in `[brackets]` is filled in per job. |
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
| `jsa run` | Collects jobs from every job board in `config.yaml`, filters and scores them, and prints the best new ones. Uses paid Browserbase time and AI calls. |
| `jsa run --source "Bayt - Java"` | Runs only the one source with that name. |
| `jsa run --no-score` | Collects jobs but skips scoring, so no scoring calls are made. |
| `jsa add` | Adds a job from text you paste, such as a LinkedIn post asking for CVs by email. Paste the text, press Enter, then Ctrl-D. It reads the role, company and email address, scores the job and shortlists it. |
| `jsa add post.txt --url <link>` | The same, from a saved text file, keeping the post's link. |

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
| `jsa runs` | Shows past runs: when, how many jobs found and scored, tokens used, and errors. |

### Emailing recruiters

| Command | What it does |
|---|---|
| `jsa email` | Drafts emails for your shortlisted jobs (up to 10, newest first) using `email_template.txt`. It checks each posting is still open, then writes a preview to `digests/emails-<date>.html`. Nothing is sent. |
| `jsa email 343` | Drafts for one job. You can list several numbers. |
| `jsa email --gmail-drafts` | Also saves each ready email into your Gmail Drafts with your CV attached, for you to review and send. |
| `jsa email --send` | Sends each ready email from your Gmail with your CV attached, then marks the job as applied so it is never emailed again. |
| `jsa email --no-browse` | Skips the live check of the posting (no Browserbase use). |
| `jsa email --limit 5` | Changes how many shortlisted jobs are drafted. |
| `jsa cover-letter 343` | Writes a cover letter for one job and saves it with the application. |
| `jsa followups` | Lists emails sent 6 or more days ago that have had no follow-up. |
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
| `jsa web` | Opens a web page on this Mac with your shortlist, scores, email drafts and status, and buttons to mark a job applied or skipped. Press Ctrl-C in the terminal to stop it. |

The statuses are: `shortlisted`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`,
`skipped`.

### Running it every day

| Command | What it does |
|---|---|
| `jsa daily` | Runs the search, writes `digests/<date>.md`, lists follow-ups due, and emails you one summary if Gmail is set up. |
| `jsa schedule install --time 08:00` | Tells macOS to run `jsa daily` at that time every day. Run it from the project folder. |
| `jsa schedule status` | Shows whether the schedule is installed and when it runs. |
| `jsa schedule remove` | Removes the schedule. |

### Help

| Command | What it does |
|---|---|
| `jsa -h` | Lists all commands. |
| `jsa email -h` | Shows the options for one command. |
| `jsa -v run` | Runs a command with detailed log output, useful when something goes wrong. |

### Less common options

| Option | On | What it does |
|---|---|---|
| `--config <file>` | `run`, `email`, `add`, `followups`, `daily`, `web` | Use a settings file other than `config.yaml`. |
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
7. `jsa web` (or `jsa applications`) to see where everything stands.

Once `jsa schedule install` is set up, step 1 happens by itself each morning and a summary arrives
by email.

## Settings you are most likely to change

All in `config.yaml`:

| Setting | Meaning |
|---|---|
| `search.roles`, `search.locations` | What you are looking for and where. |
| `search.max_age_days` | Only jobs posted within this many days (7). |
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
| `sources` | Job boards and company career pages to search. |

## What costs money

- **AI model calls** (Claude): `jsa daily`, `jsa run` (reading pages and scoring), `jsa email`, `jsa add`,
  `jsa cover-letter` and `jsa profile import`.
- **Browserbase time**: `jsa daily`, `jsa run`, and the live posting check in `jsa email`.

Everything else (`jobs`, `show`, `apply`, `status`, `applications`, `digest`, `runs`, `migrate`)
is free.

## Limits to know about

- Job sites block automated browsers, so the agent cannot log in or click Apply for you. That is
  why `jsa apply` opens the page in your own browser.
- Most job board postings show no email address, so `--send` only covers the ones that do, plus
  posts you add with `jsa add`.
- Only the first 15 job pages per site are opened in full each run; the newest postings go first.
- `--send` stops at 10 emails a day and waits 20 seconds between them; both are settings.
- The daily schedule only runs while the Mac is awake.
- After any update to the agent, run `jsa migrate` once; until then every command stops and says so.
- A job whose posting age the site does not show is kept and listed last.
