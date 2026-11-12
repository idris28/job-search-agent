# Architecture

How the job search agent works from end to end. For what each command does, see
[GUIDE.md](GUIDE.md).

## Full application flow

The diagram follows one job from being found to being applied for. It has four parts, one per
command you run: `jsa run`, `jsa add`, `jsa email` and `jsa apply`. The parts share only the
database: each one reads what an earlier one stored.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as jsa (cli.py)
    participant Pipe as Pipeline (pipeline.py)
    participant Src as Sources (sources/)
    participant Web as Browserbase browser (browser.py)
    participant AI as AI model (llm.py)
    participant Filt as Rule filters (filters.py)
    participant DB as PostgreSQL (db.py)
    participant Rep as Preview (report.py)
    participant Mail as Gmail (mailer.py)
    participant Own as User's own browser

    rect rgb(235, 244, 255)
    Note over User,DB: 1. jsa run - collect, filter, score, shortlist
    User->>CLI: jsa run
    CLI->>Pipe: run_agent(config, AI, browser)
    Pipe->>DB: active_profile(), start_run()
    loop each job board in config.yaml
        Pipe->>Src: build_source().fetch()
        Src->>Web: fetch(search page)
        Web-->>Src: page text and links
        Note over Web: If the session ends mid-run, a new one is opened and the page is retried
        Src->>AI: extract_listings(page)
        AI-->>Src: jobs with title, link, location, posted age
        Note over Src: Links not on the page are dropped. Newest jobs are opened first.
        Src->>Web: fetch(job page) for up to 15 jobs
        Web-->>Src: full description
        Src-->>Pipe: JobPosting list
        loop each JobPosting
            Pipe->>DB: upsert_job() - stored once, by fingerprint
            Pipe->>Filt: reject_reason(job)
            Filt-->>Pipe: keep, or drop for location, title, bank, older than 7 days
        end
    end
    Pipe->>DB: existing_match_hash() - skip jobs already scored
    par up to 4 jobs at a time
        Pipe->>AI: score_job(profile, preferences, job)
        AI-->>Pipe: score 0-100, matched skills, gaps, red flags
    end
    Pipe->>DB: save_match(), shortlist_many(score 75 or more)
    Pipe->>DB: finish_run(counts, tokens)
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
        CLI->>AI: recruiter_email(resume, job, email_template.txt)
        AI-->>CLI: template filled in for this job
        Note over CLI: unfilled_placeholders() flags any blank left in the draft
        CLI->>DB: save_outreach(draft)
    end
    CLI->>Rep: emails_html()
    Rep-->>User: digests/emails-date.html preview
    opt --gmail-drafts or --send
        Note over CLI: Ready = address on the posting, posting open, no blank left, not already applied
        CLI->>Mail: build_message() with CV attached
        alt --gmail-drafts
            CLI->>Mail: save_drafts()
            Mail-->>User: drafts in Gmail to review and send
        else --send
            CLI->>Mail: send_messages()
            Mail-->>User: email sent to the recruiter
            CLI->>DB: set_application_status(applied)
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
```

## Reading the diagram

| Part | Command | What it leaves behind |
|---|---|---|
| 1 | `jsa run` | Jobs, scores and a shortlist in the database |
| 2 | `jsa add` | One more shortlisted job, from text you pasted |
| 3 | `jsa email` | A draft per job, an HTML preview, and optionally Gmail drafts or sent emails |
| 4 | `jsa apply` | The status of each job you applied to on its site |

## The pieces

| Piece | File | Role |
|---|---|---|
| `jsa` commands | `src/jobagent/cli.py` | Reads the command and drives everything else |
| Pipeline | `src/jobagent/pipeline.py` | One run: collect, store, filter, score, shortlist |
| Sources | `src/jobagent/sources/` | Job boards through the browser (`generic.py`); company boards through public feeds (`ats.py`) |
| Browser | `src/jobagent/browser.py` | A Browserbase session, or local Chromium, behind one `fetch()` |
| AI model | `src/jobagent/llm.py`, `llm_anthropic.py` | Every AI task: read pages, score jobs, read pasted posts, draft emails |
| Rule filters | `src/jobagent/filters.py` | Free checks before any AI call |
| Database | `src/jobagent/db.py`, `migrations/` | PostgreSQL: jobs, scores, applications, runs |
| Preview | `src/jobagent/report.py` | Terminal tables, the Markdown digest, the HTML email preview |
| Gmail | `src/jobagent/mailer.py` | Builds the message; saves it to Drafts or sends it |
| Data shapes | `src/jobagent/models.py` | `JobPosting` and the AI's structured answers |
| Settings | `src/jobagent/config.py` | `.env` secrets and `config.yaml` |

## Design points

- **`JobPosting` is the one shape a job takes.** Sources create it, filters read it, the database
  stores it, and the AI scores it.
- **Every AI task lives in `BaseLLM`.** The Claude and OpenAI classes only supply how to call each
  provider, so one line in `.env` switches between them.
- **The four parts meet only in the database.** That is why a job added with `jsa add` can be
  emailed without a run, and why re-running never scores or emails a job twice.
- **Nothing reaches a recruiter by accident.** A draft is saved before delivery is attempted, and
  delivery happens only with `--gmail-drafts` or `--send`.
- **The agent never logs in to job sites.** They block automated browsers, so applying on a site
  is done by you in your own browser.
