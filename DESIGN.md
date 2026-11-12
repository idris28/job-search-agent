# Design direction

Every screen of the Job Search website follows this file. It was set with the unslop method by
Damir Sokolovsky ([@heydamir](https://x.com/heydamir), CC BY 4.0). Change the direction here first,
then the screens.

## Direction

- **Product.** One person's desk for a job hunt: it finds openings in India and the Gulf, scores
  them against his resume, and writes and tracks the letters to recruiters.
- **Character.** Steady, exact, quietly hopeful.
- **World.** A writing desk at night and the post: letters written, sent, and replies awaited.
- **Moments.** (1) The pipeline drawn as a tray of letters seen from the edge: one mark for each
  tracked job, each colour a stage. (2) The email draft shown as a real sheet of paper in the job
  panel.
- **Signature.** A small postmark with the date on anything that has been sent. Nowhere else.

The rule behind all of it: the chrome is quiet, and colour and craft go into the two moments.
Nothing glows. Light on the screen always means something.

## Colour

One neutral ramp, ink, tinted slightly toward night. Surfaces never read as blue.

| Role | Dark | Light | Token |
|---|---|---|---|
| Sidebar, deepest surface | `#07080d` | `#eceff4` | `--s0` |
| Page | `#0b0d14` | `#f5f7fa` | `--s1` |
| Card | `#11141c` | `#ffffff` | `--s2` |
| Raised: input, active row, hover | `#1a1e28` | `#eceff4` | `--s3` |
| Hairline | text at 8% | text at 8% | `--line` |
| Stronger hairline: inputs, buttons | text at 14% | text at 14% | `--line-2` |
| Primary text | `#eef0f5` | `#111827` | `--t1` |
| Secondary text | `#a3a9b8` | `#4b5565` | `--t2` |
| Muted text and icons | `#7a8296` | `#6b7487` | `--t3` |
| Accent, as ink | `#8aa6ff` | `#2f55d4` | `--accent` |
| Accent, as fill under white text | `#3b63e6` | `#3b63e6` | `--accent-fill` |

- **One accent, cobalt, used rarely:** the selected row or nav item, links, the focus ring, and the
  place a running task is working. Never on a surface.
- **The main button is not the accent.** It is the primary text colour as a fill (off-white on dark,
  near-black on light) with the page colour as its text.
- **Stage colours,** used in the pipeline tray and on status labels: shortlisted = primary text
  (paper on the desk), applied = accent (in the post), interviewing = amber (needs you), offer =
  green, set aside = `--aside` (`#363c4b` / `#c3c9d4`), rejected = red.
- **Status colours carry meaning only:** green `#4cc38a` / `#15803d` = ready or done, amber
  `#d9a23b` / `#a15c07` = needs you, red `#f0686c` / `#dc2626` = a problem. Everything else is
  neutral. No violet, no cyan, no colour chosen for variety.
- **Not allowed:** hue gradients, gradient text, coloured glows or shadows, colour washes behind
  content, blur on cards, neon borders.
- **Depth** on dark comes from the surface steps and hairlines. Only things that float (the job
  panel, dialogs, menus) get a soft neutral shadow.

## Type

- **Geist** for the interface, **Geist Mono** for figures, counts, dates and meta.
- Sizes: 12 (meta), 13 (secondary), 14 (body), 16 (section titles), 20 (panel titles), 28 (page
  title and card figures). Nothing else.
- Weights: 400 and 500. 600 only for the wordmark. Hierarchy comes from size and colour.
- Sentence case. No uppercase labels, no italics, no negative letter spacing under 16px.
- Numbers use tabular figures and one format: `3,209`.

## Spacing

- Everything sits on a 4px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
- Sidebar padding 16. Cards 20. Page edges 32 (16 on a phone).
- Rows: 32 in the sidebar, 36 for controls, 48 for table rows.
- Space inside a group is smaller than space between groups: 8 inside, 24 between.

## Corners

| Element | Radius | Token |
|---|---|---|
| Keycap, label, small button | 6 | `--r-s` |
| Row, input, button | 8 | `--r-m` |
| Card | 12 | `--r-l` |
| Panel, dialog | 16 | `--r-xl` |

Only round things (the profile circle, a status dot) are fully round. Not everything is a pill.

## Icons

One line-icon set at 16px with a 1.5 stroke, in the colour of the text beside it. No emoji. An icon
appears only where it helps find a row: in the sidebar and inside buttons that act. Never before
every card title. A category that needs colour gets a small status dot.

## Motion

One curve, `cubic-bezier(0.22, 1, 0.36, 1)`. 140ms for hover and press, 200ms for menus, 320ms for
the job panel. Only colour, background, border, opacity and transform move. Nothing loops unless a
task is really running. Nothing lifts or scales on hover.

## Shared parts

| Part | Rule |
|---|---|
| Sidebar | 248 wide on `--s0`. Wordmark, search with keycaps, the seven screens, then the actions, each a 32px row with an icon and a label. Counts are muted mono text at the right. The selected row is a raised surface with a hairline. |
| Page heading | Page title at 28, one line of secondary text, quiet meta on the right, one main button and at most one secondary button. |
| Button | 36 tall (32 small), radius 8, weight 500. Main = text-colour fill. Secondary = raised surface with a hairline. Quiet = no surface until hovered. Danger = red text. |
| Card | `--s2` with a hairline, radius 12, padding 20. No card inside a card: an inner group is a hairline-separated block or a raised row. |
| Input | 36 tall, `--s3`, stronger hairline, radius 8. Focus = accent hairline plus a 3px accent ring at 25%. |
| Label | Small status dot plus secondary text. Colour only from the status colours. |
| Keycap | 20px square, raised surface, hairline, mono 12. |
| Dialog and job panel | `--s2`, hairline, radius 16, soft neutral shadow. The backdrop is a plain dim, no blur. |
| Message | `--s3`, hairline, radius 8, one line. Short messages end without a full stop. |
| Stage numbers | One strip of six, hairlines between, no card per number. Label at 13, figure at 28 mono, one line of muted text. The current screen's number sits on the raised surface. |
| Pipeline tray | Marks 4 wide and 20 tall, 4 apart, wrapping in rows. One mark is one job, in stage order, and opens that job. Over 180 jobs, one mark stands for several and a line under the legend says how many. The legend gives count and share. |
| Postmark | A 36px ring holding the day over the month, with three wavy lines to its right, in accent ink, turned 6 degrees. It sits at the end of a row for a job that has been emailed (on a phone the wavy lines go) and, at 48px, in the top right corner of the sent email's sheet. |
| Email sheet | Paper (`#f4f2ec` on dark, `#fffdf9` on light) with a 2px corner and a soft neutral shadow, lying on a `--s0` well. Inside the sheet the tokens switch to the light values, so ink, lines and buttons read as on paper. To and Subject are lines with a hairline under each; the text has no box and the sheet grows with it. Edit and Preview switch the same sheet. Only the email gets a sheet: the follow-up and the cover letter stay quiet raised blocks. |
| Lead chart (Insights) | The missing-skills chart is the largest thing on the screen: 8px bars on a hairline grid with a mono percent axis, the top bar in accent and the rest muted. The scale is the share of scored jobs that ask for the skill. Everything else on the screen is smaller and different in kind: a quiet row of weekly figures at 20, and a ranked list of sites with 2px bars. |
| Run table (Activity) | Rows 48 tall. Numbers are mono, right-aligned, in the `3,209` format. The result is a status label. |
| Setup rows (Settings) | An 8px status dot, the name, then one line of text: green = ready, red = missing, dim = optional and not set. |
| Templates (Settings) | One card for the three templates with a switch at its top right. Template text is mono 13. |
| Email preview page | A single column 720 wide. Each job is a heading, a status label and one muted line, then its email on a sheet, then the copy buttons. The follow-up and the notes stay quiet raised blocks. It follows the computer's light or dark setting. No postmark: these are drafts. |
| Job panel heading | Title at 20, company under it, then location, posting age and pay as muted text with no icons. The score is a figure at 28 mono with the thin bar from the table. |

## Words

- **One name per action,** the same on its button, in All actions, on the progress strip and in the
  message when it ends: Find new jobs, Add a job from a post, Add HR addresses, Draft emails, Look
  for addresses, Save drafts to Gmail, Send ready emails, Send follow-ups, Run the morning routine,
  Download digest. A save button names what it saves: Save draft gives "Draft saved".
- **A confirm button repeats the action,** with the count when there is one: "Send 2 emails",
  "Merge duplicates", "Stop Job Search". Never "OK", "Yes" or "Send them".
- **Sentence case everywhere,** including status names: Shortlisted, Applied, Interviewing, Offer,
  Rejected, Skipped, Withdrawn. A search is Finished, Partly finished, Failed or Running.
- **A one-sentence message has no full stop:** labels, captions, sub-lines, empty states, short
  confirmations. Text of two or more sentences keeps its full stops. The page applies this to every
  message it shows, including ones the program sends.
- **Say the number, not "a few":** "Emails with no reply after 6 days".
- **An error says what to do next.** "The program could not do that. Reload the page and try again",
  not "That did not work".
- **Words in use:** search (not run), morning routine (not daily run), address (the recruiter's
  email address), draft (an email not yet sent), look (not theme).
- No exclamation marks, no greetings, no praise for the product.

## Layout

The app fills the window: sidebar on the left, content fluid up to 1480 wide. On a narrow window
the sidebar slides in from a menu button. The sections of each screen and their order stay as they
are.

## Still to do

Nothing. The global layer, every screen of the website, and the email preview page written by
`report.py` are done. The preview page carries its own copy of the tokens, because it is a
separate file that opens without the website: change them in both places.

## Checklist for any change

- Does every colour come from a token, and does each coloured thing mean something?
- Is every size on the type scale and every space on the 4px grid?
- Is there exactly one main button on the screen?
- Would this screen still fit another product if the name were swapped? If yes, it is not done.
