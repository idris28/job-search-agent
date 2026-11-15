// The job table and the widgets beside it.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

/* ---------- table ---------- */
function rowsFor(view) {
  const jobs = S.state.jobs, due = new Set(S.state.due);
  if (view === "shortlist") return jobs.filter(r => r.status === "shortlisted");
  if (view === "progress") return jobs.filter(r => r.status !== "shortlisted");
  if (view === "followups") return jobs.filter(r => due.has(r.job_id));
  return S.matches || [];
}
const isGeneral = r => String(r.url || "").startsWith("general:");
// What a row is called: a job by its title and company; a general application by the employer
// and the address written to, since its title is the same on every one.
const rowName = r => !isGeneral(r) ? [r.title, r.company]
  : named(r.company) ? [r.company, r.contact_email || r.title] : [r.contact_email || r.company, r.title];
const ready = r => r.status === "shortlisted" && r.has_draft && r.contact_email && r.contact_kind !== "general" && !r.outreach_sent_at;
function passes(r) {
  const f = S.f, s = statusOf(r), x = f.extra;
  if (f.country && countryOf(r.location) !== f.country) return false;
  if (f.score && (r.score ?? 0) < f.score) return false;
  if (f.posted && !(r.posted_at && Date.now() - new Date(r.posted_at) <= f.posted * 864e5)) return false;
  if (S.view === "shortlist") return !(x === "ready" && !ready(r)) && !(x === "nodraft" && r.has_draft) && !(x === "noaddr" && r.contact_email) && !(x === "general" && !isGeneral(r)) && !(x === "posted" && isGeneral(r));
  if (S.view === "progress") return x === "aside" ? ASIDE.includes(s) : x === "general" ? isGeneral(r) : x === "posted" ? ACTIVE.includes(s) && !isGeneral(r) : x ? s === x : ACTIVE.includes(s);
  if (S.view === "matches") return !(x === "new" && s) && !(x === "shortlisted" && s !== "shortlisted") && !(x === "applied" && !ACTIVE.includes(s)) && !(x === "aside" && !ASIDE.includes(s));
  return true;
}
function shown() {
  let rows = rowsFor(S.view).filter(passes);
  const q = S.q.trim().toLowerCase();
  if (q) rows = rows.filter(r => `${r.title} ${r.company} ${r.location || ""} ${r.contact_email || ""}`.toLowerCase().includes(q));
  const { key, dir } = S.sort;
  if (key) rows = [...rows].sort((a, b) => { const x = a[key] ?? "", y = b[key] ?? ""; return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir; });
  return rows;
}
const EXTRA = {
  shortlist: ["Next step", [["", "Any next step"], ["ready", "Ready to send"], ["nodraft", "No draft yet"], ["noaddr", "No address yet"], ["general", "General applications"], ["posted", "Job postings only"]]],
  progress: ["Stage", [["", "In progress"], ["applied", "Applied"], ["interviewing", "Interviewing"], ["offer", "Offer"], ["aside", "Set aside"], ["general", "General applications"], ["posted", "Job postings only"]]],
  matches: ["Status", [["", "Any status"], ["new", "Not listed yet"], ["shortlisted", "Shortlisted"], ["applied", "Applied or later"], ["aside", "Set aside"]]],
};
function renderFilters() {
  const f = S.f, ex = EXTRA[S.view];
  const sel = (id, icon, label, opts, val) => `<label class="fseg">${ic(icon)}<select id="${id}" aria-label="${label}">${opts.map(([v, l]) => `<option value="${v}"${String(v) === String(val) ? " selected" : ""}>${l}</option>`).join("")}</select>${ic("down", "caret")}</label>`;
  $("#fbar").innerHTML =
    sel("f-country", "globe", "Country", [["", "All countries"], ["India", "India"], ["UAE", "UAE"], ["Saudi Arabia", "Saudi Arabia"], ["Qatar", "Qatar"], ["Remote", "Remote or other"]], f.country) +
    sel("f-score", "target", "Score", [[0, "Any score"], [60, "Score 60+"], [70, "Score 70+"], [80, "Score 80+"], [90, "Score 90+"]], f.score) +
    sel("f-posted", "calendar", "Posted", [[0, "Any date"], [1, "Last 24 hours"], [3, "Last 3 days"], [7, "Last 7 days"], [30, "Last 30 days"]], f.posted) +
    (ex ? sel("f-extra", "filter", ex[0], ex[1], f.extra) : `<span class="fseg off">${ic("clock")}Oldest first</span>`);
}
function tagFor(r, due) {
  const s = statusOf(r);
  if (S.view !== "matches" && r.status === "applied" && r.reply_kind === "reply") return `<span class="tag c-green">${ic("inbox")}Replied</span>`;
  if (S.view !== "matches" && r.status === "applied" && r.reply_kind === "bounced") return `<span class="tag c-red">Not delivered</span>`;
  if (S.view === "followups" || (S.view !== "matches" && due.has(r.job_id))) return `<span class="tag c-amber">${ic("clock")}Follow up now</span>`;
  if (S.view === "shortlist") {
    if (ready(r)) return `<span class="tag c-green">${ic("send")}Ready to send</span>`;
    if (r.has_draft && r.contact_kind === "general") return `<span class="tag c-amber">General inbox only</span>`;
    if (r.has_draft && !r.contact_email) return `<span class="tag c-amber">No address yet</span>`;
    return `<span class="tag c-violet">${ic("edit")}No draft yet</span>`;
  }
  if (!s) return `<span class="tag c-slate">Not listed yet</span>`;
  return `<span class="tag ${STATUS_C[s] || "c-slate"}">${esc(STATUS_L[s] || cap(s))}</span>`;
}
function emptyText(total) {
  if (!S.state.setup.profile) return "<h3>Nothing here yet</h3>Finish the setup step at the top first";
  if (total) return `<h3>No job matches these filters</h3>Change a filter or the search text<br><button class="btn sm" data-act="clear">Clear the filters</button>`;
  if (S.view === "shortlist") return `<h3>Your shortlist is empty</h3>Jobs scoring ${S.state.shortlist_min_score} or more land here after a search<br><button class="btn primary" data-act="run">${ic("zap")}Find new jobs</button>`;
  if (S.view === "progress") return "<h3>No applications yet</h3>A job moves here when you email the recruiter or mark it applied";
  if (S.view === "followups") return `<h3>No follow-ups due</h3>They appear here when an email has had no reply for ${S.state.follow_up_days} days`;
  return `<h3>No scored jobs yet</h3>Run a search to collect and score jobs<br><button class="btn primary" data-act="run">${ic("zap")}Find new jobs</button>`;
}
function renderList(force) {
  const st = S.state, all = rowsFor(S.view), rows = shown(), due = new Set(st.due);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE)); S.page = Math.max(0, Math.min(S.page, pages - 1));
  const slice = rows.slice(S.page * PAGE, (S.page + 1) * PAGE);
  const sl = S.view === "shortlist" ? all : [], n = sl.filter(ready).length, nd = sl.filter(r => !r.has_draft).length, na = sl.filter(r => !r.contact_email).length;
  const sig = JSON.stringify([S.view, S.page, S.q, S.f, S.sort, S.sel, S.matches === null, all.length, rows.length, n, nd, na, st.sends, st.due,
    slice.map(r => [r.job_id, statusOf(r), r.score, r.has_draft, r.contact_email, r.contact_kind, r.outreach_sent_at, r.reply_kind, ago(r.posted_at)]), st.check_replies]);
  if (!force && sig === S.lsig) return;
  S.lsig = sig;
  $("#ttitle").textContent = { shortlist: "Shortlisted jobs", progress: S.f.extra === "aside" ? "Set aside" : S.f.extra === "general" ? "General applications" : "Applications", followups: "Follow-ups due", matches: "All scored jobs" }[S.view];
  $("#tcount").textContent = rows.length === all.length ? all.length : `${rows.length} of ${all.length}`;
  $("#thlast").textContent = S.view === "shortlist" ? "Next step" : "Status";
  $("table.jobs").classList.toggle("sent", S.view !== "shortlist");
  $("table.jobs").classList.toggle("hr", S.f.extra === "general" && S.view !== "matches");  // an HR address has no score or posting date
  let tb = "", hint = "";
  if (S.view === "shortlist") {
    tb = `<button class="btn sm" data-act="draft-all">${ic("edit")}Draft emails (${nd})</button><button class="btn sm" data-act="contacts-all">${ic("at")}Look for addresses (${na})</button>
      <button class="btn sm" data-act="gmail-all">${ic("inbox")}Save drafts to Gmail</button><button class="btn sm primary" data-act="send-all">${ic("send")}Send ready emails (${n})</button>`;
    hint = `${n} of ${all.length} can be emailed now${st.sends && st.sends.cap ? `, ${st.sends.today} of ${st.sends.cap} sent today` : ""}`;
  } else if (S.view === "followups") {
    tb = `${st.check_replies ? `<button class="btn sm" data-act="replies">${ic("inbox")}Check for replies</button>` : ""}<button class="btn sm primary" data-act="followups">${ic("send")}Send follow-ups (${all.length})</button>`;
    hint = `Due ${st.follow_up_days} days after an email with no reply`;
  } else if (S.view === "matches") {
    tb = `<button class="btn sm" data-act="digest">${ic("download")}Download digest</button>`;
    hint = "Newest postings first";
  } else { tb = st.check_replies ? `<button class="btn sm" data-act="replies">${ic("inbox")}Check for replies</button>` : "";
    hint = "Open a job to record an interview, an offer or a rejection"; }
  $("#toolbar").innerHTML = tb; $("#thint").textContent = hint;
  $$(".tcard th[data-sort]").forEach(th => th.setAttribute("aria-sort", S.sort.key === th.dataset.sort ? (S.sort.dir > 0 ? "ascending" : "descending") : "none"));
  const body = $("#tbody");
  if (S.view === "matches" && S.matches === null) body.innerHTML = `<tr><td colspan="5"><div class="empty">Loading matches</div></td></tr>`;
  else body.innerHTML = slice.map(r => `<tr class="row" data-job="${r.job_id}" tabindex="0" aria-selected="${r.job_id === S.sel}">
      <td><span class="jt" title="${esc(rowName(r).join(", "))}"><b>${esc(rowName(r)[0])}</b><small>${esc(rowName(r)[1])}</small></span></td>
      <td class="loc">${esc(r.location || "Not given")}</td>
      <td>${r.score == null ? '<span class="faint">None</span>' : `<span class="sc ${tier(r.score)}"><b>${r.score}</b><span class="bar"><u style="width:${r.score}%"></u></span></span>`}</td>
      <td class="nw">${esc(ago(r.posted_at)) || '<span class="faint">Not shown</span>'}</td>
      <td><div class="stc">${tagFor(r, due)}${r.outreach_sent_at ? postmark(r.outreach_sent_at) : ""}</div></td></tr>`).join("") || `<tr><td colspan="5"><div class="empty">${emptyText(all.length)}</div></td></tr>`;
  const from = rows.length ? S.page * PAGE + 1 : 0, to = Math.min(rows.length, (S.page + 1) * PAGE);
  let pg = "";
  if (pages > 1) {
    const start = Math.max(0, Math.min(S.page - 2, pages - 5)), end = Math.min(pages, start + 5);
    pg = `<button data-page="${S.page - 1}" aria-label="Previous page"${S.page ? "" : " disabled"}>${ic("left")}</button>`;
    for (let i = start; i < end; i++) pg += `<button data-page="${i}"${i === S.page ? ' aria-current="page"' : ""}>${i + 1}</button>`;
    pg += `<button data-page="${S.page + 1}" aria-label="Next page"${S.page < pages - 1 ? "" : " disabled"}>${ic("right")}</button>`;
  }
  $("#tfoot").innerHTML = `<span>Showing ${from} to ${to} of ${plural(rows.length, "job", "jobs")}</span><span class="pager">${pg}</span>`;
}
function sortBy(key) {
  const first = key === "score" || key === "posted_at" ? -1 : 1, s = S.sort;
  S.sort = s.key !== key ? { key, dir: first } : s.dir === first ? { key, dir: -first } : { key: "", dir: 1 };
  S.page = 0; renderList();
}
const staleMatches = () => S.view === "matches" ? loadMatches() : (S.matches = null);
async function loadMatches() {
  try { S.matches = (await api("/api/matches?min_score=0")).jobs; } catch (e) { S.matches = []; fail(e); }
  if (S.view === "matches") renderList(true);
}

/* ---------- side widgets ---------- */
function nextSteps() {
  const st = S.state, sl = rowsFor("shortlist"), t = st.task, out = [];
  if (st.setup.database === "behind") return [["amber", "refresh", "Update the database", "New features need it; your jobs stay as they are", "Update the database", "migrate"]];
  if (st.setup.database !== "ok") return [["red", "alert", "The database is not answering", "Start PostgreSQL, then reload this page", "Reload", "reload-page"]];
  if (!st.setup.profile) return [["amber", "upload", "Import your resume", "Jobs are scored against it", "Choose your resume", "resume"]];
  const n = sl.filter(ready).length, nd = sl.filter(r => !r.has_draft).length, na = sl.filter(r => !r.contact_email).length, due = st.due.length;
  if (t && t.running) out.push(["blue", "refresh", `${t.label} is running`, "Its progress shows under the numbers above", "Show output", "v:activity"]);
  if (due) out.push(["amber", "clock", `${plural(due, "follow-up is", "follow-ups are")} due`, "No reply yet to an email you sent", "Open follow-ups", "v:followups"]);
  const answered = k => st.jobs.filter(r => r.status === "applied" && r.reply_kind === k).length;
  if (answered("reply")) out.push(["green", "inbox", `${plural(answered("reply"), "recruiter has", "recruiters have")} replied`, "Read the reply in Gmail, then record what happened on the job", "Open In progress", "v:progress"]);
  if (answered("bounced")) out.push(["red", "alert", `${plural(answered("bounced"), "email was", "emails were")} not delivered`, "The address refused it. Look for another one and send again", "Open In progress", "v:progress"]);
  if (n) out.push(["green", "send", `${plural(n, "email is", "emails are")} ready to send`, "Draft and address are both in place", "Send ready emails", "send-all"]);
  const sent = (st.counts || {}).batch || 0;
  if (sent && !(t && t.running)) out.push(["blue", "clock", `${sent.toLocaleString()} ${sent === 1 ? "job is" : "jobs are"} being scored as a batch`, "At half price; the answers usually arrive within the hour", "Collect the scores", "score"]);
  const w = (st.counts || {}).waiting || 0, cap = (st.search || {}).score_cap;
  if (w && !(t && t.running)) out.push(["blue", "target", `${w.toLocaleString()} ${w === 1 ? "job is" : "jobs are"} waiting to be scored`, `Found by earlier searches${cap && w > cap ? `; up to ${cap} are scored at a time` : ""}`, "Score waiting jobs", "score"]);
  if (sl.length) out.push(["blue", "link", `${plural(sl.length, "shortlisted job", "shortlisted jobs")} to apply for`, "Open each posting, apply on its site, then say so", "Start applying", "apply-first"]);
  if (nd) out.push(["violet", "edit", `${plural(nd, "shortlisted job has", "shortlisted jobs have")} no email draft`, "Written from your template and resume", "Draft emails", "draft-all"]);
  if (na) out.push(["cyan", "at", `${plural(na, "job has", "jobs have")} no recruiter address`, "Looked up on each company's own site", "Look for addresses", "contacts-all"]);
  if (!sl.length) out.push(["blue", "zap", "Your shortlist is empty", "Search the job sites for new postings", "Find new jobs", "run"]);
  if (out.length < 5) out.push(["slate", "trending", "See which skills to learn next", "What postings ask for that your resume lacks", "Open insights", "v:insights"]);
  return out.slice(0, 5);
}
function renderWidgets() {
  const st = S.state, jobs = st.jobs, t = st.task;
  const sig = JSON.stringify([jobs.map(r => [r.job_id, r.status, r.score, r.has_draft, !!r.contact_email, !!r.outreach_sent_at, r.reply_kind]), st.countries, st.due, (st.counts || {}).waiting, t && [t.id, t.running], !!st.setup.profile]);
  if (sig === S.wsig) return;
  S.wsig = sig;
  const STAGES = [["Shortlisted", ["shortlisted"], "c-paper"], ["Applied", ["applied"], "c-blue"], ["Interviewing", ["interviewing"], "c-amber"], ["Offer", ["offer"], "c-green"], ["Set aside", ASIDE, "c-aside"]];
  const groups = STAGES.map(([name, keys, c]) => ({ name, c, rows: jobs.filter(r => keys.includes(r.status)).sort((x, y) => (y.score ?? -1) - (x.score ?? -1)) }));
  const total = jobs.length, unit = Math.max(1, Math.ceil(total / 180));
  let i = 0;
  const marks = groups.map(g => unit === 1
    ? g.rows.map(r => `<i class="${g.c}" style="--i:${i++}" data-job="${r.job_id}" title="${esc(r.title)}, ${esc(r.company)}"></i>`).join("")
    : Array.from({ length: g.rows.length ? Math.max(1, Math.round(g.rows.length / unit)) : 0 }, () => `<i class="${g.c}" style="--i:${i++}"></i>`).join("")).join("");
  const said = groups.filter(g => g.rows.length).map(g => `${g.rows.length} ${g.name.toLowerCase()}`).join(", ");
  $("#donut").innerHTML = `<div class="chead"><h2>Pipeline</h2><span class="count">${total.toLocaleString()} tracked</span><span class="grow"></span><button class="link" data-view="progress">In progress${ic("right")}</button></div>
    ${total ? `<div class="tray${S.dealt ? "" : " deal"}" role="img" aria-label="Tracked jobs by stage: ${esc(said)}">${marks}</div>
    <div class="legend">${groups.map(g => `<div><i class="${g.c}"></i><span>${g.name}</span><b>${g.rows.length.toLocaleString()}</b><small>${Math.round(100 * g.rows.length / total)}%</small></div>`).join("")}</div>
    ${unit > 1 ? `<p class="faint">One mark is ${unit} jobs</p>` : ""}` : '<div class="empty">No tracked jobs yet</div>'}`;
  if (total) S.dealt = true;

  const top = jobs.filter(r => r.score != null).sort((a, b) => b.score - a.score).slice(0, 9);
  $("#tops").innerHTML = `<div class="chead"><h2>Top matches</h2><span class="grow"></span><button class="link" data-view="matches">View all${ic("right")}</button></div>
    <div class="panel tlist">${top.map(r => `<button class="tm" data-job="${r.job_id}"><span class="n">${esc(r.title)}<small>${esc(r.company)}</small></span><span class="v">${r.score}</span><span class="bar"><u data-w="${r.score}"></u></span></button>`).join("") || '<div class="empty">No scored jobs on your lists yet</div>'}</div>`;

  const tally = {};
  jobs.forEach(r => { const c = countryOf(r.location); tally[c] = (tally[c] || 0) + 1; });
  const cs = (st.countries && st.countries.length ? st.countries : Object.entries(tally).map(([country, n]) => ({ country, jobs: n })).sort((a, b) => b.jobs - a.jobs)).slice(0, 5);
  const ct = cs.reduce((a, c) => a + c.jobs, 0), cmax = Math.max(1, ...cs.map(c => c.jobs));
  $("#geo").innerHTML = `<div class="chead"><h2>Where the jobs are</h2><span class="grow"></span><span class="faint nw">${plural(ct, "scored job", "scored jobs")}</span></div>
    <div class="geo">${cs.map(c => { const w = Math.max(3, 92 * c.jobs / cmax); return `<div class="gr"><span class="gl">${esc(countryName(c.country))}</span><span class="gb" style="--w:${w}%"><b>${Math.round(100 * c.jobs / ct)}%</b><span class="bar"><u data-w="${w}"></u></span></span></div>`; }).join("") || '<div class="empty">Nothing scored yet</div>'}</div>`;

  $("#next").innerHTML = `<div class="chead"><h2>Next steps</h2></div>
    <div class="steps">${nextSteps().map(([c, i, title, sub, label, go]) => `<div class="step"><span class="dot c-${c}">${ic(i)}</span><div><b>${esc(title)}</b><small>${esc(sub)}</small></div><button class="btn sm" data-go="${go}">${label}</button></div>`).join("")}</div>`;
  grow($("#work"));
}
