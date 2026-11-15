// The screens that are not lists: Insights, Activity and Settings.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

/* ---------- views and pages ---------- */
async function showView(v, init) {
  if (document.body.classList.contains("reading") && !await closeDrawer()) return;
  const changed = init || v !== S.view;
  S.view = v; S.inited = true; setMenu(false);
  if (changed) { S.q = ""; $("#tq").value = ""; S.page = 0; S.sort = { key: "", dir: 1 }; S.f = { country: "", score: v === "matches" ? 70 : 0, posted: 0, extra: "" }; }
  const list = LIST.includes(v);
  $("#work").hidden = !list; $("#page").hidden = list;
  if (!S.state) return;
  renderChrome();
  if (list) {
    if (v === "matches" && S.matches === null) loadMatches();
    if (changed) renderFilters();
    renderList(true); renderWidgets();
  } else loadPage();
}
async function loadPage() {
  const v = S.view;
  renderPage();
  try {
    if (v === "insights" || v === "activity") S.insights = await api("/api/insights?days=30");
    if (v === "settings") { S.settings = await api("/api/settings"); S.cfg = await api("/api/config").catch(e => ({ unavailable: tidy(e.message) })); S.formDirty = false; }
  } catch (e) {
    if (v !== "activity") { $("#page").innerHTML = `<div class="card pad"><div class="empty"><h3>Not available yet</h3>${esc(tidy(e.message))}</div></div>`; return; }
    S.insights = { runs: [], unread: tidy(e.message) };  // a task's output must still be readable, for example the first resume import
  }
  if (S.view === v) renderPage();
}
const cardHead = (title, extra = "") => `<div class="chead"><h2>${title}</h2>${extra}</div>`;
function renderPage() {
  const el = $("#page");
  if (S.view === "activity") {
    const t = S.state && S.state.task, runs = S.insights ? S.insights.runs : null;
    el.innerHTML = `<div class="pgrid"><section class="card pad span2">${cardHead(t ? esc(t.label) : "Nothing has run yet")}
        <p class="sub">${t ? (t.running ? "Running now. " : `Finished ${esc(when(t.ended_at))}. `) + "This is what the program reported." : "When you start a search or draft emails, its progress shows here"}</p>
        ${t ? `<pre class="out" id="taskout">${esc(S.lines.join("\n") || "No output yet")}</pre>` : ""}</section>
      <section class="card pad span2">${cardHead("Past searches")}${runs === null ? '<p class="sub">Loading</p>' : S.insights.unread ? `<p class="sub" style="margin:0">${esc(S.insights.unread)}</p>` : runsTable(runs)}</section></div>`;
    const out = $("#taskout"); if (out) out.scrollTop = out.scrollHeight;
    if (t && !S.polling && S.lines.length < t.total) api("/api/task?since=0").then(r => { if (r.task && r.task.id === S.taskId && !S.polling) { S.lines = r.task.lines; const o = $("#taskout"); if (o) { o.textContent = S.lines.join("\n"); o.scrollTop = o.scrollHeight; } } }).catch(() => {});
    return;
  }
  if (S.view === "insights") {
    const i = S.insights;
    if (!i) { el.innerHTML = `<div class="card pad"><p class="sub" style="margin:0">Loading</p></div>`; return; }
    const m = i.progress.moves, mail = i.progress.mail, src = i.progress.sources, smax = Math.max(1, ...src.map(x => x.found));
    const rate = mail.emailed_ever ? `${mail.answered_ever} of ${mail.emailed_ever} emailed jobs got an answer (${Math.round(100 * mail.answered_ever / mail.emailed_ever)}%).` : "No emails sent yet, so there is no reply rate.";
    const week = [["Shortlisted", m.shortlisted], ["Applied", m.applied], ["Emails sent", mail.sent], ["Follow-ups sent", mail.followed_up], ["Interviews", m.interviewing], ["Offers", m.offer], ["Rejected", m.rejected]];
    const top = 100 * Math.max(0, ...i.gaps.map(x => x.jobs)) / Math.max(1, i.gap_jobs), tick = top > 50 ? 20 : top > 20 ? 10 : 5, axis = Math.max(tick, Math.ceil(top / tick) * tick);
    const ticks = Array.from({ length: axis / tick + 1 }, (_, k) => k * tick);
    const gap = x => { const pc = 100 * x.jobs / Math.max(1, i.gap_jobs); return `<div class="gp"><span class="gs">${esc(x.skill)}</span><span class="gt"><u data-w="${100 * pc / axis}"></u></span><span class="gn"><b>${x.jobs.toLocaleString()}</b>${Math.round(pc)}%</span></div>`; };
    const site = x => `<div class="srow"><span class="n">${esc(x.source)}</span><span class="v">${x.found.toLocaleString()} found, ${x.shortlisted + x.applied} kept</span><span class="bar"><u data-w="${100 * x.found / smax}"></u></span></div>`;
    el.innerHTML = `<div class="pgrid lead">
      <section class="card pad span2">${cardHead("Your last 7 days")}<p class="sub">${esc(rate)} ${i.waiting} still on your shortlist.</p>
        <div class="week">${week.map(([l, n]) => `<div><b>${(n || 0).toLocaleString()}</b><span>${l}</span></div>`).join("")}</div></section>
      <section class="card pad">${cardHead("Skills you are missing most")}<p class="sub">${i.gaps.length ? `The share of the ${i.gap_jobs.toLocaleString()} jobs scored 50 or more in the last ${i.days} days that ask for each skill. Learning the top few, or adding ones you already know to your resume, raises your scores.` : "Nothing to show until some jobs are scored"}</p>
        ${i.gaps.length ? `<div class="gaps" style="--n:${ticks.length - 1}" role="img" aria-label="Skills asked for that are not on your resume, by share of jobs">${i.gaps.map(gap).join("")}
          <div class="gp axis"><span></span><span class="gticks">${ticks.map(t => `<i>${t}%</i>`).join("")}</span><span></span></div></div>` : ""}</section>
      <section class="card pad">${cardHead("Which sites deliver")}<p class="sub">Jobs first seen in the last 7 days, by where they came from. Kept means shortlisted or applied.</p>
        ${src.slice(0, 10).map(site).join("") || '<p class="sub" style="margin:0">No jobs found this week</p>'}
        ${src.length > 10 ? `<details><summary>${plural(src.length - 10, "more site", "more sites")}</summary>${src.slice(10).map(site).join("")}</details>` : ""}</section>
    </div>`;
    grow(el);
    return;
  }
  const g = S.settings;
  if (!g) { el.innerHTML = `<div class="card pad"><p class="sub" style="margin:0">Loading</p></div>`; return; }
  const p = S.state.setup.profile, sch = g.schedule, C = S.cfg || { unavailable: "Loading" };
  const changedFields = C.fields ? C.fields.filter(f => f.changed).length : 0;
  const cfgField = f => {
    const id = "cfg-" + f.key.replace(".", "-"), was = Array.isArray(f.file_value) ? f.file_value.join(", ") : f.file_value;
    const mark = f.changed ? `<em class="chg" title="${esc(C.file)} has: ${esc(was === null || was === "" ? "nothing" : was)}">changed</em>` : "";
    if (f.kind === "bool") return `<div class="fld swf"><label class="sw"><input type="checkbox" id="${id}" data-cfg="${f.key}"${f.value ? " checked" : ""}><span>${esc(f.label)}</span>${mark}</label>${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</div>`;
    const val = f.kind === "list" ? (f.value || []).join(", ") : f.value ?? "";
    const box = f.kind === "list" ? `<textarea class="field short" id="${id}" data-cfg="${f.key}" spellcheck="false">${esc(val)}</textarea>`
      : `<input class="field" id="${id}" data-cfg="${f.key}"${f.kind === "text" ? "" : ' inputmode="decimal"'} autocomplete="off" value="${esc(val)}">`;
    return `<div class="fld${f.kind === "list" ? " wide" : ""}"><label for="${id}">${esc(f.label)}${mark}</label>${box}${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</div>`;
  };
  const row = (ok, name, text, extra = "") => `<div class="check"><i class="sdot ${ok === true ? "c-green" : ok === null ? "c-aside" : "c-red"}"></i><b>${name}</b><span>${text} ${extra}</span></div>`;
  const dupes = g.duplicates.reduce((n, x) => n + x.drop.length, 0);
  const tpls = [["tpl", "save-tpl", "Email", g.template, "Used for every recruiter email. Text in [square brackets] is filled in for each job; everything else is sent as you wrote it.", "Switched off in config.yaml, so the built-in format is used"],
    ["ctpl", "save-ctpl", "Cover letter", g.cover_template, "Used by \"Write a cover letter\" in a job's panel. Text in [square brackets] is filled in for each job; everything else is kept as you wrote it.", "Switched off in config.yaml, so a short built-in cover letter is written"],
    ["gtpl", "save-gtpl", "General email", g.general_template, "Used for HR addresses you add without a job posting. Text in [square brackets] is filled in from your resume.", "Switched off in config.yaml"]];
  el.innerHTML = `<div class="pgrid">
    <section class="card pad span2">${cardHead("Setup")}<p class="sub">Keys and passwords live in the <b>.env</b> file in ${esc(g.folder)}. This page never shows or changes them.</p>
      ${row(S.state.setup.database === "ok", "Database", S.state.setup.database === "ok" ? "Up to date" : "Needs attention, see the top of the page")}
      ${S.state.setup.database !== "ok" ? row(null, "Resume", "Shown once the database is working")
        : row(!!p, "Resume", p ? `${esc(p.name)}, imported ${esc(day(p.imported))}` : "Not imported yet", `<button class="btn sm" data-act="resume">${ic("upload")}${p ? "Import a newer one" : "Choose your resume"}</button>`)}
      ${row(g.ai.ready, "AI model", g.ai.ready ? `${esc(g.ai.model || "Default model")} (${esc(g.ai.provider)})` : "No API key in .env")}
      ${row(g.browser.ready, "Browser for job sites", !g.browser.ready ? `BROWSERBASE_API_KEY is missing in .env; ${plural(g.browser.hosted.length, "job board needs", "job boards need")} it`
        : !g.browser.boards ? "Not needed by the sites that are switched on"
        : !g.browser.hosted.length ? "This Mac"
        : g.browser.hosted.length === g.browser.boards ? "Browserbase"
        : `Browserbase for ${esc(g.browser.hosted.join(", "))}; this Mac for the rest`)}
      ${row(g.gmail.ready, "Gmail", g.gmail.ready ? `Sends from ${esc(g.gmail.address)}` : "Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env to send from this page")}
      ${row(g.cv.found, "CV to attach", g.cv.found ? esc(g.cv.path) : g.cv.path ? `Not found: ${esc(g.cv.path)}` : "Set outreach.resume_path in config.yaml")}
      ${row(g.telegram ? true : null, "Phone notifications", g.telegram ? "Telegram is set up" : g.gmail.ready ? "Strong matches are emailed to you. Add Telegram keys to .env for phone alerts." : "Not set up", `<button class="btn sm" data-act="notify-test">${ic("bell")}Send a test</button>`)}
    </section>
    <section class="card pad">${cardHead("Every morning")}<p class="sub">${sch.installed ? `The morning routine runs daily at <b>${esc(sch.time)}</b> while this Mac is awake${sch.loaded ? "" : " (it is installed but not loaded; set it again)"}` : "Let the search run by itself each morning: it searches, writes a digest and emails you one summary"}</p>
      <div class="inline"><input type="time" id="schedtime" value="${esc(sch.time || "08:00")}" aria-label="Time of day">
        <button class="btn primary" data-act="sched-on">${sch.installed ? "Change the time" : "Run every morning"}</button>
        ${sch.installed ? `<button class="btn" data-act="sched-off">Switch it off</button>` : ""}
        <button class="btn ghost" data-act="daily">Run it now</button></div></section>
    <section class="card pad">${cardHead("Duplicate jobs")}<p class="sub">${dupes ? `${plural(dupes, "job is", "jobs are")} stored twice. Merging keeps your scores and status on one copy.` : "None. The same job on two sites is stored once."}</p>
      ${dupes ? `<div class="scroll-x"><table><tr><th>Keep</th><th>Merge into it</th></tr>${g.duplicates.map(x => `<tr><td>#${x.keep.id} ${esc(x.keep.title)}, ${esc(x.keep.company)}</td><td>${x.drop.map(d => `#${d.id} ${esc(d.title)}`).join("<br>")}</td></tr>`).join("")}</table></div>
      <p style="margin:16px 0 0"><button class="btn" data-act="dedupe">Merge ${plural(dupes, "duplicate", "duplicates")}</button></p>` : ""}</section>
    <section class="card pad span2">${cardHead("Your templates", `<span class="seg" role="group" aria-label="Which template">${tpls.map(([id, , label]) => `<button data-act="tpl-show" data-to="${id}" aria-pressed="${S.tpl === id}">${label}</button>`).join("")}</span>`)}
      ${tpls.map(([id, act, label, t, on, off]) => `<div data-pane="${id}"${S.tpl === id ? "" : " hidden"}><p class="sub" style="margin-top:0">${t && t.file ? `${on} Saved to ${esc(t.file)}.` : off}</p>
        ${t && t.file ? `<textarea class="field tplbox" id="${id}" aria-label="${label} template" spellcheck="false">${esc(t.text)}</textarea><button class="btn" data-act="${act}">Save template</button>` : ""}</div>`).join("")}</section>
    <section class="card pad span2">${cardHead("Search and limits")}${C.unavailable ? `<p class="sub" style="margin:0">${esc(C.unavailable)}</p>` : `
      <p class="sub">What you change here is kept in <b>${esc(C.overrides_file)}</b>; <b>${esc(C.file)}</b> itself is never rewritten. ${changedFields ? `${plural(changedFields, "setting differs", "settings differ")} from it.` : ""}</p>
      ${[...new Set(C.fields.map(f => f.group))].map(name => `<h3 class="grp">${esc(name)}</h3><div class="form">${C.fields.filter(f => f.group === name).map(cfgField).join("")}</div>`).join("")}
      <div class="acts" style="margin-top:20px"><button class="btn" data-act="cfg-save">Save settings</button>${changedFields ? `<button class="btn ghost" data-act="cfg-reset">Go back to ${esc(C.file)}</button>` : ""}</div>`}</section>
    ${C.unavailable ? "" : `<section class="card pad span2">${cardHead("Sites", `<span class="count" id="sitecount">${C.sites.filter(x => x.enabled).length} of ${C.sites.length} on</span><span class="grow"></span>${ILL(C.sites).length ? `<button class="btn sm" data-act="sites-ill" aria-pressed="false"><span>Sites with a problem (<span id="illcount">${ILL(C.sites).length}</span>)</span></button>` : ""}<label class="find">${ic("search")}<input id="sitefind" placeholder="Find a site" aria-label="Find a site" autocomplete="off"></label>`)}
      <p class="sub">A site that is off is skipped by every search. A switch takes effect at once.</p>
      ${C.sites.some(x => x.uses_browser) ? `<h3 class="grp">Job boards, read with a browser</h3>
      <p class="sub">Some job boards refuse the browser on this Mac and accept Browserbase. Choose Browserbase only for those, so its browser time is not spent on the rest. The company sites below need no browser.</p>
      <div class="boards">${C.sites.filter(x => x.uses_browser).map(x => `<label class="brow${x.browser_changed ? " changed" : ""}"><span>${esc(x.name)}</span><em class="chg">changed</em>
        <select data-browser="${esc(x.name)}" aria-label="Browser for ${esc(x.name)}">${[["", `Usual: ${g.browser.kind === "local" ? "this Mac" : "Browserbase"}`], ["local", "This Mac"], ["browserbase", "Browserbase"]].map(([v, l]) => `<option value="${v}"${x.browser === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>`).join("")}</div>
      <h3 class="grp">On or off</h3>` : ""}
      <div id="illbar" hidden><p class="sub">These sites are on but have failed, or have listed no job in their last three searches or more. Hover over a mark to see why.</p>
        <button class="btn sm" data-act="sites-ill-off">Switch these off</button></div>
      <div class="sites">${C.sites.map(x => `<label class="sw${x.changed ? " changed" : ""}" data-name="${esc(x.name.toLowerCase())}"${ill(x) ? " data-ill" : ""}><input type="checkbox" data-site="${esc(x.name)}"${x.enabled ? " checked" : ""}><span>${esc(x.name)}</span>${healthMark(x)}<em class="chg">changed</em></label>`).join("")}</div></section>`}
    <section class="card pad span2">${cardHead("Save a job from your browser")}<p class="sub">For a job you find yourself, on LinkedIn or any job site, in your own browser where you are signed in. Job Search has to be running.</p>
      <ol class="steps"><li>Drag this button to your browser's bookmarks bar <a class="btn sm" id="clipper" data-act="clip-drag" href="${esc(clipper())}">Save to Job Search</a></li>
        <li>On the job's page, select the text of the post, or select nothing to take the whole page, then click the bookmark</li>
        <li>Job Search opens with the post filled in. Check it and choose Add the job. Nothing is added before that</li></ol></section>
    <section class="card pad">${cardHead("Backups")}<p class="sub">${g.backup.latest ? `Last backup ${esc(when(g.backup.latest.at))} (${size(g.backup.latest.size)}); ${plural(g.backup.latest.count, "copy is", "copies are")} kept in the <b>${esc(g.backup.folder)}</b> folder.` : "No backup yet."} ${g.backup.daily ? "The morning routine makes one each day." : ""} A backup holds every job, score, draft and application.</p>
      ${g.backup.tool ? `<button class="btn" data-act="backup">Back up now</button>` : `<p class="sub" style="margin:0">pg_dump, which comes with PostgreSQL, was not found, so no backup can be made from here</p>`}</section>
    <section class="card pad">${cardHead("Close the program")}<p class="sub">The page keeps working in the background after you close this tab. Stop it here; open Job Search again to bring it back.</p>
      <button class="btn danger" data-act="quit">${ic("power")}Stop Job Search</button></section>
  </div>`;
}
function runsTable(runs) {
  if (!runs.length) return `<p class="sub" style="margin:0">None yet</p>`;
  const num = v => `<td class="num">${v == null ? "" : Number(v).toLocaleString()}</td>`;
  return `<div class="scroll-x"><table class="runs"><tr><th>Search</th><th>Started</th><th>Result</th><th class="num">Found</th><th class="num">New</th><th class="num">Scored</th><th class="num">AI tokens</th><th class="num">Cost</th><th>Problem</th></tr>
    ${runs.map(r => `<tr><td class="nw">#${r.id}</td><td class="nw">${esc(when(r.started_at))}</td><td><span class="tag ${r.status === "succeeded" ? "c-green" : r.status === "running" ? "c-blue" : r.status === "failed" ? "c-red" : "c-amber"}">${esc(RUN_L[r.status] || cap(r.status))}</span></td>${num(r.jobs_found)}${num(r.jobs_new)}${num(r.jobs_scored)}${num(r.tokens_used || 0)}<td class="num"${r.usage ? ` title="${esc(Object.entries(r.usage).map(([m, u]) => `${m}: ${u.cost == null ? "price not known" : "$" + Number(u.cost).toFixed(2)}`).join(", "))}"` : ""}>${r.cost_usd == null ? "" : "$" + Number(r.cost_usd).toFixed(2)}</td><td>${esc((r.error || "").slice(0, 120))}</td></tr>`).join("")}</table></div>`;
}
