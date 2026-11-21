# Using the Job Search website

The website is the job search agent with buttons instead of typed commands. It runs on your Mac
only; nobody else can open it. This guide explains every part of the screen and how to use it day
to day. For the typed commands behind each button, see [GUIDE.md](GUIDE.md). A picture of every
screen and function is in [screenshots/README.md](screenshots/README.md).

## Opening and closing it

| To do this | Do this |
|---|---|
| Open it | Double-click **Job Search** in the project folder. Drag it to the Dock to keep it one click away. |
| Open it again later | Go to http://127.0.0.1:8765 in your browser, or double-click **Job Search** again. |
| Close it | Closing the browser tab is enough. The program keeps running quietly, so the page opens instantly next time. |
| Stop the program completely | **Settings**, then **Stop Job Search** at the bottom. Double-click **Job Search** to start it again. |

If the page says it lost contact with the program, double-click **Job Search** again.

## Before your first search

Open **Settings**. The **Setup** list has a dot beside each line: green for what is ready, red for
what is missing, grey for something optional that is not set up.

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
   numbers while it works, and the strip under them shows progress. A full search takes a few minutes: the company sites are read side by side, the job boards one after another.
2. **Look at the shortlist.** Jobs scoring 75 or more land on **Shortlist**, newest first (75 is
   the shortlist score; change it under Settings, **Search and limits**). Click a
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
7. **Follow up.** When an email has had no reply for the number of days set under Settings, **Search and limits** (the Follow-ups screen says how many), the job appears under **Follow-ups**
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
out.

**Where the list is.** Before an address is emailed it is on **Shortlist**: choose **General
applications** in the Next step filter. Once emailed it moves to **In progress**: choose **General
applications** in the Stage filter there. Each row shows the employer and the address it was sent
to, with the postmark for the day. Typing part of an address in the search box finds its row.
**Job postings only** in the same filters shows everything else.

Send these to employers that could plausibly hire you. The same email to dozens of unrelated
inboxes is rarely read and can get your Gmail account marked as spam.

## Finding jobs

| Button | What it does |
|---|---|
| **Find new jobs** | Searches every site that is switched on (Settings, **Sites**), drops jobs that do not fit your rules, scores the rest against your resume and shortlists the strong ones. A job from a job board is scored only after its own page was read, and only so many pages are opened per search, so on a long list some jobs wait for the next search. |
| Arrow beside it, **Collect only, score later** | Gathers jobs without scoring them, which is the larger part of the AI cost. They are scored on the next full search. |
| Arrow beside it, **Score waiting jobs** | Scores jobs that earlier searches found but did not score, without searching the sites again. A search scores only so many jobs at a time, so some are left waiting; the number shows under **Scored** (when it says "waiting to be read" instead, those are job-board jobs whose own page the next search will open before scoring them) and in Next steps. |
| Arrow beside it, **Morning routine** | Search, then a digest file, one summary email to yourself, and a backup. |
| Arrow beside it, **Search one site** | Searches just the site you pick. |
| **Add from a post** | Paste a LinkedIn post, WhatsApp message or email that asks for CVs. The role, company and email address are read from it, and the job is scored and shortlisted. Click **Add the job** to start. |
| A picture of a post, in **Add from a post** | When the post is a picture (a screenshot, a photo, an image someone sent you), paste it into the box, drop it on the box, or click **choose a picture**. The AI model reads the text in it and writes it into the box, under anything already there, so a post split over two screenshots can be added one after the other. Check the text, the email address above all, because a misread letter would send the email to the wrong place. Then click **Add the job**; nothing is added before that. A tall phone screenshot is cut into pieces so the small print stays readable. PNG, JPG, WebP and GIF pictures work; reading one costs about a cent. |
| **Save to Job Search**, a bookmark in your own browser | Brings a job over from the page you are looking at, so you do not have to copy and paste. Set it up once: under **Settings**, **Save a job from your browser**, drag the **Save to Job Search** button to your browser's bookmarks bar. Then, on a job's page or a LinkedIn post, select the text of the post (or select nothing to take the whole page) and click the bookmark. Job Search opens in a new tab with the post and its link already in the **Add from a post** box. Check it and click **Add the job**; nothing is added before that. Job Search has to be running. |

With **Score ordinary searches as a batch too** switched on (Settings, **Search and limits**), Find
new jobs sends its scoring as a batch at half price and finishes without waiting. Next steps then
says how many jobs are being scored as a batch; their scores arrive with the next search, or
when you click **Collect the scores** there.

## The table

Each screen shows its jobs in the same table.

| To do this | Do this |
|---|---|
| Open a job | Click its row. |
| Search by name | Type in **Search jobs**. It looks at the title, company, location and email address. |
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
| Buttons | **Apply on the job site** opens the posting in a new tab so you can apply there; when you return, the page asks whether you applied. The next buttons record what happened: **I applied**, **Skip**, **Got an interview**, **Got an offer**, **Rejected**. **Other status** has the rest. Once a job is applied, the first button reads **Open the posting**. **Delete entry** appears only on something you added yourself (a pasted post or an HR address) that has not been emailed; it removes it for good, with its draft and notes. A job from a job site has no Delete, because the next search would bring it back: use **Skip**. |
| Why it matches | A short explanation, the skills you have, the skills asked for that are not on your resume, and anything to check before applying. |
| Email to the recruiter | The email is shown as a sheet of paper. The **To** line holds the address it will go to. If the agent found none, type one you found yourself (on LinkedIn or in the posting) and click **Save address**, or click **Look for one** to have the agent search the company's own site; empty the line and save to remove it. Below it are the subject and the text. Edit either on the sheet, then **Save draft**. **Send email** sends it after asking you to confirm. **Write it again** replaces the draft with a fresh one. **Preview**, at the top right of the section, shows it as the recruiter will see it; **Edit** brings the text back. Once the email is sent, a round postmark with the date appears on the sheet and **Send again** takes the place of **Send email**. When no email can be sent, the line under the buttons says why. The follow-up text is underneath. |
| Cover letter | **Write a cover letter** for sites that ask for one, then **Copy**. It follows your own letter in `cover_letter_template.txt`, filled in for this job. |
| Answers for the application form | For applying on a job site. At the top are your own details (name, email, phone, LinkedIn, when you can join, current and expected salary): click one to copy it. **Write the answers** then writes short answers for this job: why this role, why you, an introduction, key skills, and years per skill where your resume makes them clear. Each has a **Copy** button. Paste them into the site's form yourself and read each one first; nothing is filled in or submitted for you. Your details come from Settings, **Search and limits**, **Your details**. |
| CV for this job | **Write a CV for this job** arranges your resume for this posting: the same facts, with the experience and skills this job asks for put first. What comes back is checked against your resume, and anything your resume does not say (a skill, an employer, a line with a figure that is not yours) is taken out and listed under "Checked against your resume". **Open the PDF** shows it; read it before you use it. It is saved in the `resumes` folder. The switch **Attach it to this job's email in place of your usual CV** is off until you turn it on, so until then the email carries your usual CV. **Write it again** makes a new one and switches the attaching off again; **Remove** deletes the file. |
| Interview preparation | **Prepare for the interview** writes, for this job: what to revise first (what the posting asks for that your resume shows little of), likely technical questions, likely questions about your own work, and questions you can ask them. Click a question to see points for the answer, taken from your resume. |
| Notes | Anything you want to remember: the recruiter's name, what was said, the next step. Click **Save note**. Nothing else changes your notes. |
| History | Every status change and every email sent, with its date. |
| Full job description | The original posting text. |

A red label in the email section means the draft is not ready: a blank in your template was left
unfilled, the posting looked closed, or the draft names a company the posting did not name.

**Send email** shows only for a shortlisted job with a draft and an address that has not been
emailed yet. When it is not there, the line under the buttons says why: there is no address yet,
the job is marked applied or set aside, or the email already went. The round mark with a date at
the top right of the sheet is the day it was sent. What follows a sent email is its follow-up, on
the **Follow-ups** screen when it is due.

By itself a job is emailed once. To write to the same address a second time, for example because
the recruiter posted the role again, open the job and click **Send again**. It asks first, naming
the address and the day the first email went, then sends the letter as it is now and records the
new date; the follow-up is counted from that date. Use **Write it again** beforehand if the letter
should be redone from the new post.

Pasting a post you added before does not make a second job: it opens the one already stored. If
its email has gone, the task says so, with the date and the address, and nothing is sent by
itself; **Send again** in the job's panel is there if you want a second email.

When a posting does not name the company (a pasted post, or a "Confidential Company" listing), the
email and cover letter leave the name out: "applying for the Java Developer position", with no
"at ...".

## The seven screens

| Screen | What it shows | Buttons on it |
|---|---|---|
| **Shortlist** | Jobs worth acting on. The last column says what each one needs: no draft yet, no address yet, or ready to send. | Draft emails, Look for addresses, Save drafts to Gmail, Send ready emails |
| **In progress** | Jobs you applied to, interviews and offers. In the Stage filter, **Set aside** shows jobs you skipped and rejections, and **General applications** shows the HR addresses you wrote to. With replies switched on (see "Replies from recruiters"), a job a recruiter answered says **Replied** and one whose address refused the email says **Not delivered**. | Check for replies, when switched on |
| **Follow-ups** | Emails with no reply after the number of days you set. | Send follow-ups; Check for replies, when switched on |
| **All matches** | Every job that was scored, not only the shortlist. Starts at score 70 or more; change the Score filter to see the rest. Open one and click **Add to shortlist** to act on it. | Download digest |
| **Insights** | Your last seven days, the skills job postings ask for most that your resume lacks, and which sites deliver. | |
| **Activity** | Everything the running or last task reported, and a list of past searches. The **Cost** column is what the AI calls of that search cost, worked out from its token counts; point at it to see the amount for each model. It is an estimate, and your provider's bill is the real figure. When a search is only **Partly finished**, the Problem column says why: a spending limit was reached, some sites could not be read, or it was stopped. | |
| **Settings** | Setup, the morning routine, duplicate jobs, your templates, what is searched and the limits, the job sites, saving a job from your browser, backups, and stopping the program. | |

## Sending emails

- **Save drafts to Gmail** puts the ready emails in your Gmail Drafts so you can read and send them from
  Gmail. Nothing is sent.
- **Send ready emails** and **Send email** send from your Gmail with your CV attached. Both ask you to
  confirm first.
- Emails are sent exactly as saved, including your edits.
- Only so many emails go out per day, with a pause between them. Both numbers can be changed under
  **Settings**, **Search and limits**.
- **Send ready emails** never writes to the same job twice: once sent, a job is marked applied. Only
  **Send again**, inside one job's panel, sends a second time, and it asks first.
- If only a general inbox (such as info@) was found, **Send ready emails** leaves that job out. You can
  still open the job and send it yourself.
- An email carries your usual CV. It carries the CV written for that job instead only when you
  switched on **Attach it to this job's email** in the job's panel.

## Replies from recruiters

This is off until you switch on **Look in Gmail for replies** under **Settings**, **Search and
limits**. Once it is on:

- **Check for replies**, on the In progress and Follow-ups screens, looks in your Gmail inbox for
  answers to the emails you sent. The morning routine does the same each day.
- It reads only who wrote, when, and the subject line, and only of messages from an address you
  wrote to, messages that answer one of your subject lines, and delivery failures. It never reads
  the text of a message, never marks one as read, and changes nothing in Gmail.
- A job a person answered is marked **Replied**, and Next steps says so. Read the reply in Gmail,
  then record what happened on the job (interview, rejected). The status is yours to set.
- A job whose address refused the email is marked **Not delivered**. Put another address in the To
  line and use **Send again**.
- Neither of those gets a follow-up. An automatic reply (out of office, "we received your
  application") is shown in the job's panel but does not count as an answer, so its follow-up
  still goes out when due.

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
- Progress and changes arrive by themselves. The program sends each line to the page as it is
  printed, and tells every open tab the moment something changes, so two tabs do not disagree. If
  that connection drops, the page goes back to asking every few seconds.

## What costs money or sends something

| Action | Uses paid AI or browser time | Sends something outside your Mac |
|---|---|---|
| Find new jobs, Run the morning routine, Search one site | Yes | The morning routine emails you a summary |
| Collect only, score later | Yes, but less: no scoring | No |
| Score waiting jobs | Yes: AI only, no browser | No |
| Add from a post, and reading a picture of a post | Yes, a little | No |
| Draft emails, Write it again | Yes | No |
| Look for addresses | Yes | No |
| Write a cover letter, Write the answers, Write a CV for this job, Prepare for the interview | Yes, a little | No |
| Check for replies | No | No. It reads the sender, date and subject line of answers in your Gmail |
| Choose your resume | Yes, a little | No |
| Send ready emails, Send email, Send again, Send follow-ups | No | Yes, to recruiters |
| Save drafts to Gmail | No | Saves drafts in your Gmail |
| Send a test notification | No | Yes, to you |
| Everything else (status, notes, saving a draft, deleting an entry, filters, Insights, digest, merging duplicates, changing settings, switching a site, backing up) | No | No |

Each search stops by itself at the AI and browser limits set under **Settings**, **Search and
limits**. The AI limit can be set in tokens or, more usefully, in US dollars (**AI budget for one
search, in US dollars**): a cheap model's tokens cost a small fraction of a dear one's, so money is
the truer limit. What each search cost is in the **Cost** column of Past searches on the Activity
screen.

Four settings there make a search cheaper, and all are off until you switch them on: a cheaper
model for reading job-site pages, a cheaper model for a quick first check of each job, scoring the
morning routine as a batch at half price, and scoring ordinary searches as a batch too.

## Settings

| Section | What you can do |
|---|---|
| Setup | See what is ready, import a newer resume, send a test notification. |
| Every morning | Pick a time and click **Run every morning**. The Mac then runs the morning routine daily at that time, as long as it is awake. **Switch it off** removes it. **Run it now** runs it once. |
| Duplicate jobs | If the same job is stored twice, **Merge** folds the copies together and keeps your score and status. This cannot be undone. |
| Your templates, **Email** | The three templates share one box; the buttons at its top right switch between them. **Email** is the wording used for every recruiter email. Text in [square brackets] is filled in for each job; everything else is sent as you wrote it. Click **Save template**. |
| Your templates, **General email** | Edit the email sent to HR addresses you added without a job posting. Click **Save template**. |
| Your templates, **Cover letter** | Edit the letter used by **Write a cover letter**. It works like the email template: text in [square brackets] is filled in for each job. Click **Save template**. |
| Search and limits | Change what is searched for and the limits: title words, places, the oldest posting, the lowest salary, the shortlist score, the AI and browser budgets, emails a day, the follow-up wait. Click **Save settings**. Your changes are kept in `config.overrides.yaml`; `config.yaml` itself is never rewritten. A value that differs from the file is marked **changed**, and **Go back to config.yaml** drops your changes. Under **Your details** are your email, LinkedIn link, phone and salary figures, which a job's panel offers for copying into a site's application form. Under Scoring are the AI budget in tokens and in US dollars, and the ways to spend less: **Cheaper model for a quick first check** and **Cheaper model for reading job-site pages** (for example `claude-haiku-5-5` in each), **Score the morning routine as a batch** and **Score ordinary searches as a batch too**. Under Emails is **Look in Gmail for replies**, which is off until you switch it on. |
| Sites | One switch per job site. A site that is off is skipped by every search. A switch takes effect at once. Type in **Find a site** to narrow the list. At the top, **Job boards, read with a browser** lists the boards that need one, each with a choice: the usual browser, **This Mac**, or **Browserbase**. Some boards refuse the browser on this Mac and accept Browserbase; choosing Browserbase only for those keeps its browser time for them. The **Browser for job sites** line under Setup says which boards are on Browserbase. A site whose last search **failed**, or that has listed **no jobs** in its last three searches or more, carries that mark; point at it to see why and when it last listed jobs. **Sites with a problem** shows only those, and **Switch these off** turns them all off at once, after asking. |
| Save a job from your browser | The **Save to Job Search** button, to drag to your browser's bookmarks bar once. "Finding jobs" above says how it is used. |
| Backups | **Back up now** copies the whole database into the `backups` folder. The morning routine also makes one each day, and the newest 7 are kept. The card shows when the last one was made. Bringing a backup back is done from the terminal; `jsa backup` prints the command, and [GUIDE.md](GUIDE.md) has it. |
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
| "This page is older than the running program. Reload it" | Reload the page. This happens after the program restarts. |
| "The page lost contact with the job search program." | Double-click **Job Search** to start it again, then reload. |
| "The database is not answering." | PostgreSQL is not running. Start it, then reload. |
| A yellow bar asking to update the database | Click **Update the database**. It only adds what new features need. |
| Double-clicking Job Search does nothing | Open `digests/web.log` in the project folder; the reason is at the end. |
| A job's panel has no **Send email** button | Read the line under **Save draft**: it says what is missing, or that the email already went on the date in the round mark. |
| An icon sits inside the **To** box, over the address | That icon comes from an extension in your browser, such as a mail or password helper, not from Job Search. The box keeps room at its end for it. To remove it, switch that extension off for `127.0.0.1`. |
| "N waiting to be read" under **Scored** | Job-board jobs whose own page has not been opened yet. Each search reads some of them and scores them then; nothing needs doing. |
| A search is **Partly finished** and says the scoring batch was still running | With batch scoring on, the answers were not back in time. The next search of any kind collects them, and those jobs are not scored twice. |
| A warning that "the main model read it instead" | The cheaper model named under Settings could not read a job-site page, so the main model did. Check the model name under **Search and limits**; the search itself is complete. |
| "No email is ready yet." | A job needs both a draft and an address. Use **Draft emails** and **Look for addresses** first, or type an address into the job's **To** box. |
| "Found an address for 0 of 7 jobs" | Those companies publish no application address. Apply on the job sites, or add an address yourself. |
| A task says "did not finish" | Click **Show output** to read why. A site blocking the search is the usual cause, and the other sites still complete. |
| The same site "could not be read" in every search | Some job sites refuse an automated browser: they close the connection, answer "Access Denied", or show a "verify you are not a bot" check. The task's output says "the site refused this browser" with what it answered. The agent does not try to get around it. Switch that site off under **Settings**, **Sites**, so searches stop reporting it, or choose **Browserbase** for that board in the same place; those sites have accepted it. If the output says Browserbase would not start a browser, its browser time for the month is probably used up. |
| New buttons or panels look wrong after an update | Stop the program in Settings, open **Job Search** again, and reload the page. |
