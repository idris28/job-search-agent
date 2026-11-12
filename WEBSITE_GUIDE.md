# Using the Job Search website

The website is the job search agent with buttons instead of typed commands. It runs on your Mac
only; nobody else can open it. This guide explains every part of the screen and how to use it day
to day. For the typed commands behind each button, see [GUIDE.md](GUIDE.md).

## Opening and closing it

| To do this | Do this |
|---|---|
| Open it | Double-click **Job Search** in the project folder. Drag it to the Dock to keep it one click away. |
| Open it again later | Go to http://127.0.0.1:8765 in your browser, or double-click **Job Search** again. |
| Close it | Closing the browser tab is enough. The program keeps running quietly, so the page opens instantly next time. |
| Stop the program completely | **Settings**, then **Stop Job Search** at the bottom. Double-click **Job Search** to start it again. |

If the page says it lost contact with the program, double-click **Job Search** again.

## Before your first search

Open **Settings**. The **Setup** list shows what is ready (green tick) and what is missing (red
cross).

| Line | What it needs |
|---|---|
| Database | If it is out of date, a yellow bar appears at the top of the page with an **Update the database** button. Click it once. |
| Resume | Click **Choose your resume** and pick your CV (PDF or text). Jobs are scored against it and emails are written from it. |
| AI model, Browser for job sites | Keys in the `.env` file in the project folder. The page never shows or changes them. |
| Gmail | `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env`. Needed only to send emails or save Gmail drafts from the page. |
| CV to attach | `outreach.resume_path` in `config.yaml`. This file is attached to every email. |
| Phone notifications | Optional. **Send a test** checks that a message reaches you. |

## The screen at a glance

| Part | Where | What it is for |
|---|---|---|
| Menu | Down the left | Switches between the seven screens: Shortlist, In progress, Follow-ups, All matches, Insights, Activity, Settings. A number beside a name is how many jobs are waiting there. On a narrow window the menu opens from the button with three lines at the top left. |
| Search | Top of the menu | Opens **All actions**. |
| Actions | Under the screens, in the menu | One-click actions that work from any screen, each with its name. |
| Your name, Light and Dark | Bottom of the menu | Your name opens Settings. The two buttons switch the look. |
| Add from a post, Find new jobs | Top right | The two ways to bring jobs in. |
| Six numbers | Across the top | How many jobs are at each stage. Click a number to see those jobs. |
| Progress strip | Under the numbers | Appears while a task runs: what it is doing right now, **Show output** and **Stop**. |
| Filter bar and table | Middle | The jobs for the screen you are on. |
| Pipeline, Top matches | Right | One small mark for each job on your lists, coloured by stage, and your best-scoring jobs. Click a mark to open that job. |
| Postmark | End of a row | A round stamp with a date: the day you emailed that employer. |
| Where the jobs are, Next steps | Bottom | Scored jobs by country, and what is worth doing next, each with a button. |

## A normal day

1. **Find new jobs.** Click the **Find new jobs** button. A blue line moves under the Found and Scored
   numbers while it works, and the strip under them shows progress. A full search takes several minutes.
2. **Look at the shortlist.** Jobs scoring 75 or more land on **Shortlist**, newest first. Click a
   job to open it in a panel on the right and read why it matched.
3. **Draft the emails.** Click **Draft emails**. One email is written per job from your template and
   resume. Open a job to read and edit its draft.
4. **Find the addresses.** Click **Look for addresses**. The agent looks on each company's own site
   for a published application address. Large companies usually publish none; then either type an
   address you found yourself into the job's **To** box, or apply on the job site (step 6).
5. **Send.** Jobs that have both a draft and an address are marked **Ready to send**. Click
   **Send ready emails** to send them all, or open one job and click **Send email**. Each sent job moves to
   **In progress** as "applied".
6. **Apply on the site where there is no address.** Open the job and click **Apply on the job
   site**. The posting opens in a new tab; apply there. When you come back, the page asks "Did you
   apply?" Answer **Yes, I applied** and the job moves to In progress.
7. **Follow up.** When an email has had no reply for six days (the number is in `config.yaml`), the job appears under **Follow-ups**
   and the menu shows a number beside it. Click **Send follow-ups**.

The **Next steps** panel at the bottom of the page always shows which of these is waiting, with a
button for it.

## Applying for a job

There are two ways to apply, and the website supports both.

| Way | When | How |
|---|---|---|
| On the job site | Always possible. This is how most jobs are applied for. | Open the job, click **Apply on the job site**, apply in the tab that opens, come back and answer **Yes, I applied**. |
| By email to the recruiter | When the job has an email address (shown as **Ready to send**). | Open the job, check the draft, click **Send email**. The job is marked applied for you. |

The agent never fills in a job site's form for you. Job sites block automated browsers, so that step
is yours; the page opens the right posting and keeps the record. **Start applying** in the Next steps
panel opens the first job on your shortlist, and the arrows at the top of the panel move to the next.

## General applications: HR addresses with no job posting

Use this when you have an employer's HR or careers address but no specific vacancy.

1. In the menu on the left, click **Add HR addresses** (also in All actions, and at the bottom of
   the "Add from a post" box).
2. Paste one address per line. Put the employer's name before it if you know it:
   `Acme Gulf, hr@acme.sa`. Choose where the employers are, or leave it to be worked out from each
   address.
3. Click **Add to shortlist**. Each address becomes a "General application" on your shortlist.
   Nothing is sent. Addresses that are mistyped, repeated or already on your list are listed with
   the reason and left in the box for you to fix.
4. Draft and send them like any other job: **Draft emails**, read each one, then **Send email** or
   **Send ready emails**. The same daily limit applies, and follow-ups work the same way.

**Draft emails** writes all of them in one go. The email is written once for each country and reused
for every address there, with the employer's name swapped in, so many addresses cost only a few AI
calls.

The email comes from its own template: in Settings, under **Your templates**, choose **General email**. It asks about
openings instead of applying for a position. If you gave no employer name, the email leaves the name
out. To see only these, choose **General applications** in the Next step filter.

Send these to employers that could plausibly hire you. The same email to dozens of unrelated
inboxes is rarely read and can get your Gmail account marked as spam.

## Finding jobs

| Button | What it does |
|---|---|
| **Find new jobs** | Searches every site in `config.yaml`, drops jobs that do not fit your rules, scores the rest against your resume and shortlists the strong ones. |
| Arrow beside it, **Collect only, score later** | Gathers jobs without scoring them, which is the larger part of the AI cost. They are scored on the next full search. |
| Arrow beside it, **Morning routine** | Search, then a digest file and one summary email to yourself. |
| Arrow beside it, **Search one site** | Searches just the site you pick. |
| **Add from a post** | Paste a LinkedIn post, WhatsApp message or email that asks for CVs. The role, company and email address are read from it, and the job is scored and shortlisted. Click **Add the job** to start. |

## The table

Each screen shows its jobs in the same table.

| To do this | Do this |
|---|---|
| Open a job | Click its row. |
| Search by name | Type in **Search jobs**. It looks at the title, company and location. |
| Filter | Use the four boxes above the table: country, score, how recently it was posted, and next step (or stage, or status, depending on the screen). |
| Sort | Click a column heading. Click again to reverse, and a third time to go back to newest first. |
| See more | Use the page buttons under the table. Eight jobs show per page. |
| Clear filters | If nothing matches, click **Clear the filters**. |

The **Score** is out of 100. The bar under it turns blue at 85 or more.

## A job, opened

Clicking a job slides in a panel from the right. Close it with the X, the Esc key, or by clicking
outside it. The arrows at the top, or the J and K keys, move to the next and previous job.

| Section | What you can do |
|---|---|
| Top | Title, company, location, when it was posted, pay (stated or estimated) and the score. |
| Buttons | **Apply on the job site** opens the posting in a new tab so you can apply there; when you return, the page asks whether you applied. The next buttons record what happened: **I applied**, **Skip**, **Got an interview**, **Got an offer**, **Rejected**. **Other status** has the rest. Once a job is applied, the first button reads **Open the posting**. |
| Why it matches | A short explanation, the skills you have, the skills asked for that are not on your resume, and anything to check before applying. |
| Email to the recruiter | The email is shown as a sheet of paper. The **To** line holds the address it will go to. If the agent found none, type one you found yourself (on LinkedIn or in the posting) and click **Save address**; empty the line and save to remove it. Below it are the subject and the text. Edit either on the sheet, then **Save draft**. **Send email** sends it after asking you to confirm. **Write it again** replaces the draft with a fresh one. **Preview**, at the top right of the section, shows it as the recruiter will see it; **Edit** brings the text back. Once the email is sent, a round postmark with the date appears on the sheet. The follow-up text is underneath. |
| Cover letter | **Write a cover letter** for sites that ask for one, then **Copy**. It follows your own letter in `cover_letter_template.txt`, filled in for this job. |
| Notes | Anything you want to remember: the recruiter's name, what was said, the next step. Click **Save note**. |
| History | Every status change with its date. |
| Full job description | The original posting text. |

A red label in the email section means the draft is not ready: a blank in your template was left
unfilled, the posting looked closed, or the draft names a company the posting did not name.

When a posting does not name the company (a pasted post, or a "Confidential Company" listing), the
email and cover letter leave the name out: "applying for the Java Developer position", with no
"at ...".

## The seven screens

| Screen | What it shows | Buttons on it |
|---|---|---|
| **Shortlist** | Jobs worth acting on. The last column says what each one needs: no draft yet, no address yet, or ready to send. | Draft emails, Look for addresses, Save drafts to Gmail, Send ready emails |
| **In progress** | Jobs you applied to, interviews and offers. Choose **Set aside** in the Stage filter to see jobs you skipped and rejections. | |
| **Follow-ups** | Emails with no reply after six days. | Send follow-ups |
| **All matches** | Every job that was scored, not only the shortlist. Starts at score 70 or more; change the Score filter to see the rest. Open one and click **Add to shortlist** to act on it. | Download digest |
| **Insights** | Your last seven days, the skills job postings ask for most that your resume lacks, and which sites deliver. | |
| **Activity** | Everything the running or last task reported, and a list of past searches. When a search is only **Partly finished**, the Problem column says why: a spending limit was reached, some sites could not be read, or it was stopped. | |
| **Settings** | Setup, the morning routine, your templates, duplicate jobs, limits, and stopping the program. | |

## Sending emails

- **Save drafts to Gmail** puts the ready emails in your Gmail Drafts so you can read and send them from
  Gmail. Nothing is sent.
- **Send ready emails** and **Send email** send from your Gmail with your CV attached. Both ask you to
  confirm first.
- Emails are sent exactly as saved, including your edits.
- At most 10 emails go out per day, 20 seconds apart. Both numbers are in `config.yaml`.
- A job is never emailed twice: once sent, it is marked applied.
- If only a general inbox (such as info@) was found, **Send ready emails** leaves that job out. You can
  still open the job and send it yourself.

## Running tasks

Anything slow (searching, drafting, looking for addresses, writing a cover letter, reading a pasted
post) runs as a task.

- Only one task runs at a time. Starting a second one shows a message asking you to wait.
- The strip under the numbers shows the latest line of progress. **Show output** opens the full
  report on the Activity screen.
- **Stop** ends the task. Everything it had already saved is kept. A stopped search is listed under
  Past searches as **Partly finished**, with the reason in the Problem column, and the jobs it had
  already scored well enough are on your shortlist.
- When it finishes, a message appears at the bottom right and the lists refresh by themselves.
- You can keep reading and editing jobs while a task runs.

## What costs money or sends something

| Action | Uses paid AI or browser time | Sends something outside your Mac |
|---|---|---|
| Find new jobs, Run the morning routine, Search one site | Yes | The morning routine emails you a summary |
| Collect only, score later | Yes, but less: no scoring | No |
| Add from a post | Yes, a little | No |
| Draft emails, Write it again | Yes | No |
| Look for addresses | Yes | No |
| Write a cover letter | Yes, a little | No |
| Choose your resume | Yes, a little | No |
| Send ready emails, Send email, Send follow-ups | No | Yes, to recruiters |
| Save drafts to Gmail | No | Saves drafts in your Gmail |
| Send a test notification | No | Yes, to you |
| Everything else (status, notes, saving a draft, filters, Insights, digest, merging duplicates) | No | No |

Each search stops by itself at the AI and browser limits shown under **Settings**, **Limits in
force**.

## Settings

| Section | What you can do |
|---|---|
| Setup | See what is ready, import a newer resume, send a test notification. |
| Every morning | Pick a time and click **Run every morning**. The Mac then runs the morning routine daily at that time, as long as it is awake. **Switch it off** removes it. **Run it now** runs it once. |
| Duplicate jobs | If the same job is stored twice, **Merge** folds the copies together and keeps your score and status. This cannot be undone. |
| Your templates, **Email** | The three templates share one box; the buttons at its top right switch between them. **Email** is the wording used for every recruiter email. Text in [square brackets] is filled in for each job; everything else is sent as you wrote it. Click **Save template**. |
| Your templates, **General email** | Edit the email sent to HR addresses you added without a job posting. Click **Save template**. |
| Your templates, **Cover letter** | Edit the letter used by **Write a cover letter**. It works like the email template: text in [square brackets] is filled in for each job. Click **Save template**. |
| Limits in force | Read-only. Change them in `config.yaml`; the page picks up the change straight away. |
| Close the program | **Stop Job Search**. |

## Shortcuts

| Keys | What they do |
|---|---|
| Cmd-K (Ctrl-K on Windows) | Opens **All actions**: type a few letters, press Enter. |
| J and K | Next and previous job in the table. |
| Esc | Closes the job panel or a dialog. |
| Enter, on a row or column heading | Opens the job, or sorts by that column. |

## If something looks wrong

| What you see | What to do |
|---|---|
| "This page is out of date. Reload it." | Reload the page. This happens after the program restarts. |
| "The page lost contact with the job search program." | Double-click **Job Search** to start it again, then reload. |
| "The database is not answering." | PostgreSQL is not running. Start it, then reload. |
| A yellow bar asking to update the database | Click **Update the database**. It only adds what new features need. |
| Double-clicking Job Search does nothing | Open `digests/web.log` in the project folder; the reason is at the end. |
| "No email is ready yet." | A job needs both a draft and an address. Use **Draft emails** and **Look for addresses** first, or type an address into the job's **To** box. |
| "Found an address for 0 of 7 jobs" | Those companies publish no application address. Apply on the job sites, or add an address yourself. |
| A task says "did not finish" | Click **Show output** to read why. A site blocking the search is the usual cause, and the other sites still complete. |
| New buttons or panels look wrong after an update | Stop the program in Settings, open **Job Search** again, and reload the page. |
