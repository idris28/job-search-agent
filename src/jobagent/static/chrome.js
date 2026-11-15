// What the page knows (its state), the frame around every screen, and the task runner.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

/* ---------- state and chrome ---------- */
async function refresh() {
  try { S.state = await api("/api/state"); } catch (e) { $("#vsub").textContent = e.message; return; }
  S.refreshed = Date.now();
  renderChrome(); renderNotices();
  if (!S.inited) await showView(S.view, true);
  else if (LIST.includes(S.view)) { renderList(); renderWidgets(); }
  trackTask();
}
function renderChrome() {
  const st = S.state, c = st.counts || {}, p = st.setup.profile, t = st.task, [title, sub] = VIEWS[S.view];
  $("#me").textContent = p ? initials(p.name) : "?"; $("#mename").textContent = p ? p.name : "Settings";
  $$("#tabs [data-view]").forEach(b => b.dataset.view === S.view ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  $$("#tabs [data-c]").forEach(e => { const n = c[e.dataset.c] || 0; e.textContent = n.toLocaleString(); e.hidden = !n; });
  $("#vtitle").textContent = title; $("#vsub").textContent = S.view === "followups" ? `Emails with no reply after ${st.follow_up_days} days` : sub;
  const se = st.search || {};
  const chips = [["Sites", st.sources.length], ["Posted", se.max_age_days ? `last ${se.max_age_days} days` : "any time"], ["Pay", se.min_salary_lpa ? `${se.min_salary_lpa} LPA or more` : "any"]]
    .map(([l, v]) => `<button class="chip" data-view="settings"><span>${l}</span><b>${esc(v)}</b></button>`).join("");
  if ($("#chips").dataset.k !== chips) { $("#chips").innerHTML = chips; $("#chips").dataset.k = chips; }
  const subs = {
    found: c.found_week ? `<i class="up">+${c.found_week.toLocaleString()}</i> new this week` : `from ${st.sources.length} sites`,
    scored: c.batch ? `${c.batch.toLocaleString()} being scored as a batch` : c.waiting ? `${c.waiting.toLocaleString()} waiting to be scored` : c.unread ? `${c.unread.toLocaleString()} waiting to be read` : "against your resume", shortlisted: `scoring ${st.shortlist_min_score} or more`,
    emailed: st.sends ? `${st.sends.today} sent today${st.sends.cap ? ", limit " + st.sends.cap : ""}` : "none sent yet",
    applied: "in progress", due: c.due ? "due now" : `${st.follow_up_days} days after an email` };
  const hot = t && t.running ? HOT[t.action] || [] : [];
  $$("#stats .stat").forEach(b => {
    const k = b.dataset.n, n = c[k] ?? 0, num = $("b", b), sm = $("small", b);
    num.textContent = n.toLocaleString();
    if (sm.dataset.k !== subs[k]) { sm.innerHTML = subs[k]; sm.dataset.k = subs[k]; }
    b.classList.toggle("on", b.dataset.on === S.view);
    b.classList.toggle("hot", hot.includes(k));
    b.classList.toggle("alert", k === "due" && n > 0);
  });
  const sel = $("#onesite");
  if (sel.options.length !== st.sources.length + 1)
    sel.innerHTML = '<option value="">Choose a site</option>' + st.sources.map(s => `<option>${esc(s)}</option>`).join("");
  renderLive();
}
function renderLive() {
  const t = S.state.task, live = $("#live");
  if (!t || (!t.running && S.dismissed === t.id)) { live.hidden = true; live.dataset.k = ""; return; }
  const key = `${t.id}:${t.running}`;
  if (live.dataset.k === key) { $(".line", live).textContent = t.last || (t.running ? "Starting" : ""); return; }
  live.dataset.k = key; live.hidden = false; live.classList.toggle("running", t.running);
  if (t.running) {
    live.innerHTML = `<span class="spin"></span><b>${esc(t.label)}</b><span class="line">${esc(t.last || "Starting")}</span>
      <button class="btn sm" data-view="activity">Show output</button><button class="btn sm danger" data-act="stop">${ic("square")}Stop</button>`;
  } else {
    const ok = t.exit_code === 0 && !t.stopped;
    live.innerHTML = `<span class="dot ${ok ? "c-green" : "c-amber"}">${ic(ok ? "check" : "alert")}</span><b>${esc(t.label)}: ${t.stopped ? "stopped" : ok ? "done" : "did not finish"}</b>
      <span class="line">${esc(t.last)}</span><button class="btn sm" data-view="activity">Show output</button><button class="round sm" data-act="dismiss" aria-label="Hide this">${ic("x")}</button>`;
  }
}
function renderNotices() {
  const s = S.state.setup;
  let h = "";
  if (s.database === "unreachable") h = `<div class="notice bad"><p><b>The database is not answering.</b> Start PostgreSQL, then reload this page. ${esc(s.error)}</p></div>`;
  else if (s.database === "behind") h = `<div class="notice"><p><b>The database needs ${s.pending.length === 1 ? "one update" : s.pending.length + " updates"}</b> before anything else works. It only adds what the new features need; your jobs stay as they are.</p>
      <button class="btn primary" data-act="migrate">Update the database</button></div>`;
  else if (!s.profile) h = `<div class="notice"><p><b>Import your resume to begin.</b> Jobs are scored against it, and emails are written from it.</p>
      <button class="btn primary" data-act="resume">${ic("upload")}Choose your resume</button></div>`;
  if ($("#notices").dataset.k !== h) { $("#notices").innerHTML = h; $("#notices").dataset.k = h; }
}

/* ---------- task runner ---------- */
async function startTask(body) {
  try {
    const r = await api(body.action === "profile" ? "/api/profile" : "/api/task", body.raw ? undefined : body, body.raw);
    if (r.task.id !== S.taskId) { S.lines = []; S.taskId = r.task.id; }
    S.state.task = r.task; S.wasRunning = true;
    renderChrome(); if (S.view === "activity") renderPage(); if (LIST.includes(S.view)) renderWidgets(); if (!S.live) pollTask();
  } catch (e) { fail(e); }
}
function trackTask() {
  const t = S.state.task;
  if (t && t.id !== S.taskId) { S.taskId = t.id; S.lines = []; }
  if (t && t.running) { S.wasRunning = true; if (!S.polling && !S.live) pollTask(); }
}
function drawOutput() {
  const out = $("#taskout");
  if (out) { out.textContent = S.lines.join("\n") || "No output yet"; out.scrollTop = out.scrollHeight; }
}
// The program tells the page when the task prints a line or anything stored changes, so the page
// does not keep asking. If the line cannot be opened or drops, the page goes back to asking.
function connectFeed() {
  if (!window.EventSource) return;
  const es = new EventSource("/api/events?token=" + encodeURIComponent(TOKEN));
  es.onopen = () => { S.live = true; };
  es.onerror = () => {
    S.live = false;
    if (es.readyState === 2) setTimeout(connectFeed, 15000);  // refused outright: try again later
    if (S.state) trackTask();
  };
  es.addEventListener("task", e => {
    const { task, lines, from } = JSON.parse(e.data);
    if (!S.state) return;
    if (task.id !== S.taskId) { S.taskId = task.id; S.lines = []; }
    if (from === S.lines.length) S.lines.push(...lines);
    else if (from > S.lines.length) api("/api/task?since=0").then(r => { if (r.task && r.task.id === S.taskId) { S.lines = r.task.lines; drawOutput(); } }).catch(() => {});
    S.state.task = task;
    if (task.running) S.wasRunning = true;
    renderLive(); drawOutput();
    if (!task.running) finished(task);
  });
  es.addEventListener("changed", () => { clearTimeout(S.nudge); S.nudge = setTimeout(refresh, 250); });
}
async function pollTask() {
  if (S.polling) return;
  S.polling = true;
  try {
    for (;;) {
      const { task } = await api(`/api/task?since=${S.lines.length}`);
      if (!task) break;
      if (task.id !== S.taskId) { S.taskId = task.id; S.lines = []; continue; }
      S.lines.push(...task.lines); delete task.lines;
      S.state.task = task; renderLive();
      const out = $("#taskout"); if (out) { out.textContent = S.lines.join("\n") || "No output yet"; out.scrollTop = out.scrollHeight; }
      if (!task.running) { finished(task); break; }
      await new Promise(r => setTimeout(r, 900));
    }
  } catch (e) { fail(e); }
  S.polling = false;
}
async function finished(t) {
  if (!S.wasRunning) return;
  S.wasRunning = false;
  const ok = t.exit_code === 0 && !t.stopped;
  toast(`${t.label}: ${t.stopped ? "stopped" : ok ? "done" : "did not finish. " + (t.last || "")}`, !ok);
  S.settings = null; S.insights = null;
  await refresh(); staleMatches();
  if (S.sel && !S.dirty) openJob(S.sel, true);
  if (!LIST.includes(S.view) && !(S.view === "settings" && S.formDirty)) loadPage();
}
