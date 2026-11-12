# Architecture

How the job search agent works from end to end. For what each command does, see
[GUIDE.md](GUIDE.md). For pictures you can open in a browser, see `app-flow.html` (flowchart) and
`architecture-live.html` (animated).

## Full application flow

The diagram follows one job from being found to being followed up. It has six parts, one per
command: `jsa run`, `jsa add`, `jsa email`, `jsa apply`, `jsa followups` and `jsa daily`. The parts
share only the database: each one reads what an earlier one stored.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as jsa (cli.py)
    participant Pipe as Pipeline (pipeline.py)
    participant Src as Sources (sources/)
    participant Web as Browserbase browser (browser.py)
    participant Feeds as Company career feeds
    participant AI as AI model (llm.py)
    participant Filt as Rule filters (filters.py)
    participant DB as PostgreSQL (db.py)
    participant Rep as Preview (report.py)
    participant Mail as Gmail (mailer.py)
    participant Own as User's own browser

    rect rgb(235, 244, 255)
    Note over User,DB: 1. jsa run - collect, filter, score, shortlist
    User->>CLI: jsa run
    CLI->>DB: pending_migrations() - stop if the database is behind
    CLI->>Pipe: run_agent(config, AI, browser)
    Pipe->>DB: active_profile(), start_run()
    loop each source in config.yaml
        Note over Pipe: Skipped if the token or browser-minute limit is reached
        Pipe->>Src: build_source().fetch()
        alt job board (Naukri, Naukrigulf, Bayt)
            Src->>Web: fetch(search page)
            Web-->>Src: page text and links
            Note over Web: If the session ends mid-run, a new one is opened and the page is retried
            Src->>AI: extract_listings(page)
            AI-->>Src: jobs with title, link, location, posted age
            Src->>Web: fetch(job page) for up to 15 jobs, newest first
            Web-->>Src: full description
        else company career feed (Greenhouse, Lever, Ashby)
            Src->>Feeds: HTTP GET the public feed
            Feeds-->>Src: every open job with its posting date
        end
        Src-->>Pipe: JobPosting list
        loop each JobPosting
            Pipe->>DB: upsert_job() - once per job, also across boards (match_key)
            Pipe->>Filt: reject_reason(job)
            Filt-->>Pipe: keep, or drop for location, title, bank, older than 7 days
        end
    end
    Pipe->>DB: existing_match_hash() - skip jobs already scored
    loop batches of 4 jobs, until done or the token limit is reached
        Pipe->>AI: score_job(cached profile, job)
        AI-->>Pipe: score 0-100, matched skills, gaps, red flags
        Pipe->>DB: save_match()
    end
    Pipe->>DB: shortlist_many(score 75 or more), finish_run(counts, tokens)
    Pipe-->>CLI: RunSummary
    CLI-->>User: top new matches, newest first
    end

    rect rgb(240, 250, 240)
    Note over User,DB: 2. jsa add - a job from a pasted post (optional)
    User->>CLI: jsa add, then paste a LinkedIn post
    CLI->>AI: read_pasted_job(text)
    AI-->>CLI: role, company, location, email address
    CLI->>DB: upsert_job()
    CLI->>AI: score_job()
    AI-->>CLI: score
    CLI->>DB: save_match(), shortlist it
    CLI-->>User: job number, score, next command
    end

    rect rgb(255, 247, 232)
    Note over User,Mail: 3. jsa email - draft, preview, deliver
    User->>CLI: jsa email [--gmail-drafts | --send]
    CLI->>DB: shortlisted_job_ids() - newest first
    loop each shortlisted job
        CLI->>DB: get_job()
        CLI->>Web: fetch(live posting)
        Web-->>CLI: page text - is the job still open?
        CLI->>AI: recruiter_email(cached template and resume, job)
        AI-->>CLI: template filled in for this job
        Note over CLI: unfilled_placeholders() flags any blank left in the draft
        CLI->>DB: save_outreach(draft)
    end
    CLI->>Rep: emails_html()
    Rep-->>User: digests/emails-date.html preview
    opt --gmail-drafts or --send
        Note over CLI: Ready = address on the posting, posting open, no blank left, not already applied
        Note over CLI: resume_for() picks the CV: a variant if the job mentions its keywords
        CLI->>Mail: build_message() with that CV attached
        alt --gmail-drafts
            CLI->>Mail: save_drafts()
            Mail-->>User: drafts in Gmail to review and send
        else --send
            CLI->>DB: sends_today() - stop at max_sends_per_day
            CLI->>Mail: send_messages(), pausing between emails
            Mail-->>User: email sent to the recruiter
            CLI->>DB: status = applied, mark_outreach_sent()
        end
    end
    end

    rect rgb(250, 240, 250)
    Note over User,Own: 4. jsa apply - apply on the job site
    User->>CLI: jsa apply
    CLI->>DB: shortlisted_job_ids()
    loop each job
        CLI->>Own: open the posting
        User->>Own: applies on the site
        CLI->>User: Applied? y / n / s / q
        User-->>CLI: answer
        CLI->>DB: set_application_status(applied or skipped)
    end
    end

    rect rgb(255, 240, 240)
    Note over User,Mail: 5. jsa followups - chase emails with no reply
    User->>CLI: jsa followups [--send]
    CLI->>DB: followups_due(follow_up_days)
    DB-->>CLI: emails sent 6+ days ago with no follow-up
    CLI-->>User: list of follow-ups due today
    opt --send
        CLI->>DB: sends_today() - same daily cap
        CLI->>Mail: send_messages(stored follow-up text)
        Mail-->>User: follow-up sent to the recruiter
        CLI->>DB: mark_follow_up_sent()
    end
    end

    rect rgb(238, 238, 250)
    Note over User,Mail: 6. jsa daily - the scheduled morning run
    Note over CLI: Started by macOS launchd at the time set with jsa schedule install
    CLI->>Pipe: run_agent() - part 1 above
    Pipe-->>CLI: RunSummary
    CLI->>DB: top_matches(this run), followups_due()
    CLI->>Rep: digest_markdown() to digests/date.md
    CLI->>Mail: send_messages(summary to your own address)
    Mail-->>User: one summary email
    end
```

Not in the diagram:

- `jsa web` is a separate, long-running page: `web.py` serves `http://127.0.0.1:8765`, reads
  `dashboard_rows()` for each view, and its forms post back to change status, save a note or an
  edited draft, send a stored draft, or add a pasted post.
- `jsa contacts` runs between parts 1 and 3: the AI web-searches for a published application
  address, `contacts.py` verifies it on the company's page, and `save_contact()` stores it for
  `jsa email` to use.
- `jsa gaps`, `jsa progress` and `jsa dedupe` only read (or tidy) the database.
- After `jsa run` and `jsa daily`, `notifier.py` sends jobs scoring 85 or more to Telegram or email.

## Reading the diagram

| Part | Command | What it leaves behind |
|---|---|---|
| 1 | `jsa run` | Jobs, scores and a shortlist in the database |
| 2 | `jsa add` | One more shortlisted job, from text you pasted |
| 3 | `jsa email` | A draft per job, an HTML preview, and optionally Gmail drafts or sent emails |
| 4 | `jsa apply` | The status of each job you applied to on its site |
| 5 | `jsa followups` | A follow-up sent, and recorded, for each email that got no reply |
| 6 | `jsa daily` | Part 1, plus a digest file and one summary email to you |

## The pieces

| Piece | File | Role |
|---|---|---|
| `jsa` commands | `src/jobagent/cli.py` | Reads the command and drives everything else |
| Pipeline | `src/jobagent/pipeline.py` | One run: collect, store, filter, score, shortlist, within the spending limits |
| Sources | `src/jobagent/sources/` | Job boards through the browser (`generic.py`); company career feeds over plain HTTP (`ats.py`) |
| Browser | `src/jobagent/browser.py` | A Browserbase session, or local Chromium, behind one `fetch()`; counts the minutes used |
| AI model | `src/jobagent/llm.py`, `llm_anthropic.py` | Every AI task: read pages, score jobs, read pasted posts, draft emails, with the resume and template sent as a cached prefix |
| Rule filters | `src/jobagent/filters.py` | Free checks before any AI call |
| Database | `src/jobagent/db.py`, `migrations/` | PostgreSQL: jobs, scores, applications, send times, runs |
| Preview | `src/jobagent/report.py` | Terminal tables, the Markdown digest, the HTML email preview |
| Gmail | `src/jobagent/mailer.py` | Builds the message; saves it to Drafts or sends it |
| Web page | `src/jobagent/web.py` | A local page of the shortlist: edit and send drafts, add pasted posts, notes, status |
| Shared actions | `src/jobagent/actions.py` | Add a pasted job and send a stored draft, used by both the commands and the web page |
| Contact check | `src/jobagent/contacts.py` | Confirms a found application address is printed on the company's own page |
| Notifications | `src/jobagent/notifier.py` | Sends strong new matches to Telegram, or to your own email |
| Schedule | `src/jobagent/scheduler.py` | The macOS launchd job that runs `jsa daily` each morning |
| Data shapes | `src/jobagent/models.py` | `JobPosting`, the keys for matching a job across boards, and the AI's structured answers |
| Settings | `src/jobagent/config.py` | `.env` secrets and `config.yaml`, including limits and CV variants |

## Design points

- **`JobPosting` is the one shape a job takes.** Sources create it, filters read it, the database
  stores it, and the AI scores it.
- **Every AI task lives in `BaseLLM`.** The Claude and OpenAI classes only supply how to call each
  provider, so one line in `.env` switches between them.
- **The parts meet only in the database.** That is why a job added with `jsa add` can be emailed
  without a run, and why re-running never scores or emails a job twice.
- **One job, one row.** A job is identified by its company (without "Pvt Ltd" and similar), the
  meaningful words of its title, and its country, so the same job on two boards is stored once.
- **Spending is bounded.** A run stops collecting at the browser-minute limit and stops scoring at
  the token limit; what is left waits for the next run.
- **Nothing reaches a recruiter by accident.** A draft is saved before delivery is attempted,
  delivery happens only with `--gmail-drafts` or `--send`, and sending stops at the daily cap.
- **Addresses are found, never guessed.** `jsa contacts` asks the AI to search, but an address is
  stored only after `contacts.py` fetches the page itself and finds the address printed there.
- **The database must be current.** Every command checks for pending updates first and says
  "Run: jsa migrate" instead of failing halfway.
- **The agent never logs in to job sites.** They block automated browsers, so applying on a site
  is done by you in your own browser.
