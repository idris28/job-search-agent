# Putting the project on GitHub

A step-by-step guide to keep this project in a GitHub repository, and to send later changes
there. Every command is run in the Terminal app.

## What goes to GitHub, and what never does

Only the files git tracks are sent: the code, the tests, the guides, the pictures and the
templates. These stay on your Mac, because `.gitignore` names them:

| Stays on your Mac | Why |
|---|---|
| `.env` | Your keys and your Gmail app password |
| `config.yaml.*` | Old copies of your settings |
| `config.yaml`, `config.overrides.yaml` | Your own settings |
| `backups/` | Copies of your database: every job, email and note |
| `resumes/` | The CVs written for single jobs |
| `digests/` | Your daily lists of matches |
| `.venv/` | The installed Python packages; anyone can install them again |

Your database itself is not a file in the project, so it is never sent either.

## Step 1. Make the repository private

Make it **private**: only you can see it. The files themselves hold no personal details: the
tests and examples use a made-up person, and old copies of your settings (`config.yaml.*`) are
ignored. The project's history, though, still holds a few from its early days (your name in old
tests, your Gmail address and LinkedIn link in an old copy of your settings). In a private
repository nobody else sees them. Before ever making it public, they must be taken out of the
history too; ask Claude Code to do that.

GitHub also shows the email address of each commit's author. In a private repository only you
see it.

## Step 2. Check that git is ready

Go to the project folder (put its path in place of `/path/to/job-search-agent`):

```bash
cd "/path/to/job-search-agent"
```

Make sure there is nothing half-finished:

```bash
git status
```

It should say `On branch main` and `nothing to commit` (a line about untracked files is fine).

Make sure the private files are ignored. Each name below should be printed back; one that is
missing would be sent:

```bash
git check-ignore .env config.yaml config.overrides.yaml backups resumes digests
```

Make sure the `gh` tool is signed in to your GitHub account:

```bash
gh auth status
```

It should say `Logged in to github.com`. If it does not, run `gh auth login` and follow its
questions (GitHub.com, HTTPS, sign in with a web browser).

## Step 3. Create the repository and send the code

One command creates a private repository named `job-search-agent` on your account, links this
folder to it, and sends the `main` branch:

```bash
gh repo create job-search-agent --private --source=. --remote=origin --push
```

It prints the address of the new repository. Only `main` is sent; the other branches (the one
Claude Code works on, and `unslop`) stay on your Mac.

## Step 4. Look at it on GitHub

```bash
gh repo view --web
```

This opens the repository in your browser. The README is shown on its front page. Check that
`.env` and `config.yaml` are not in the file list.

## Step 5. Send later changes

After new work is committed to `main` (for example after you answer "Yes, do both" or
"Yes, do all" to Claude Code), send it with:

```bash
cd "/path/to/job-search-agent" && git push
```

`git status` then says `Your branch is up to date with 'origin/main'`.

Each push to `main` also runs all the tests on GitHub (`.github/workflows/tests.yml`). The result
shows as a tick or a cross beside the latest commit, under the repository's **Actions** tab, and in
the badge at the top of the README. To see it from the Terminal:

```bash
gh run list --limit 3
```

## If you prefer the GitHub website to the gh tool

1. On github.com, click **New** (the plus at the top right, then **New repository**).
2. Name it `job-search-agent`, choose **Private**, and leave **Add a README**, **.gitignore** and
   **license** unticked: the project already has them.
3. Click **Create repository**, then run these two commands, with your GitHub user name in place
   of `YOUR-NAME`:

```bash
git remote add origin https://github.com/YOUR-NAME/job-search-agent.git
```

```bash
git push -u origin main
```

If git asks for a password, it wants a personal access token, not your GitHub password. Running
`gh auth login` once avoids that question altogether.

## If something goes wrong

| Message | What to do |
|---|---|
| `Name already exists on this account` | A repository with that name exists. Use another name in step 3, or delete the old one on GitHub. |
| `remote origin already exists` | The folder is already linked. `git remote -v` shows where; `git push` sends to it. |
| `rejected ... (fetch first)` | GitHub has a change your Mac does not, usually a README made on the website. Run `git pull --rebase origin main`, then `git push`. |
| `Permission denied` or `Authentication failed` | Run `gh auth login` again. |
| A file you did not want was sent | Tell Claude Code which one: it can be removed from the repository and its history. |
