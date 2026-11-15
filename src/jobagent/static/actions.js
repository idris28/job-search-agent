// What every button does, the keyboard and click handling, and the start of the page.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

/* ---------- actions ---------- */
function setTheme(t, quiet) {
  document.documentElement.dataset.theme = t;
  $("#th-light").setAttribute("aria-pressed", String(t === "light")); $("#th-dark").setAttribute("aria-pressed", String(t === "dark"));
  if (!quiet) try { localStorage.setItem("jsa-theme", t); } catch {}
}
const ids = pred => S.state ? rowsFor("shortlist").filter(pred).map(r => r.job_id) : [];
const NOT_READY = "No email is ready yet. A job needs a draft and an address first.";
const A = {
  run: () => startTask({ action: "run" }),
  "run-noscore": () => startTask({ action: "run", no_score: true }),
  score: () => (S.state && S.state.counts && (S.state.counts.waiting || S.state.counts.batch)) ? startTask({ action: "score" }) : toast("No jobs are waiting to be scored"),
  delete: async () => { const id = S.sel;
    if (!await ask("Delete this entry?", "It is removed for good, with its draft and notes. This cannot be undone.", "Delete entry")) return;
    try { toast((await api("/api/delete", { job_id: id })).message); await closeDrawer(true); await refresh(); staleMatches(); } catch (e) { fail(e); } },
  daily: () => startTask({ action: "daily" }),
  migrate: () => startTask({ action: "migrate" }),
  backup: () => startTask({ action: "backup" }),
  stop: async () => { if (await ask("Stop this task?", "What it has already saved is kept. You can start it again later.", "Stop the task")) api("/api/task/stop", {}).catch(fail); },
  dismiss: () => { S.dismissed = S.state.task ? S.state.task.id : 0; renderLive(); },
  reload: async () => { await refresh(); await staleMatches(); toast("Up to date"); },
  "reload-page": () => location.reload(),
  clear: () => { S.q = ""; $("#tq").value = ""; S.f = { country: "", score: 0, posted: 0, extra: "" }; S.page = 0; renderFilters(); renderList(); },
  "run-menu": () => { $("#runmenu").hidden = !$("#runmenu").hidden; },
  menu: () => setMenu(!document.body.classList.contains("menu-open")),
  palette: () => openPalette(),
  add: () => { $("#adddlg").showModal(); $("#addtext").focus(); },
  "clip-drag": () => toast("Drag this button to your bookmarks bar, then click it on a job's page"),
  "close-add": () => $("#adddlg").close(),
  "add-go": () => { const text = $("#addtext").value.trim(); if (!text) return toast("Paste the post text first", true);
    $("#adddlg").close(); startTask({ action: "add", text, url: $("#addurl").value.trim() }); $("#addtext").value = ""; $("#addurl").value = ""; },
  resume: () => $("#resumefile").click(),
  "draft-all": () => { const l = ids(r => !r.has_draft && !isGeneral(r)).slice(0, 10).concat(ids(r => !r.has_draft && isGeneral(r))); l.length ? startTask({ action: "email", job_ids: l }) : toast("Every shortlisted job already has a draft"); },
  "contacts-all": () => { const l = ids(r => !r.contact_email).slice(0, 10); l.length ? startTask({ action: "contacts", job_ids: l }) : toast("Every shortlisted job already has an address"); },
  "gmail-all": () => { const l = ids(ready); l.length ? startTask({ action: "gmail-drafts", job_ids: l }) : toast(NOT_READY); },
  "send-all": async () => { const l = ids(ready), cap = S.state && S.state.sends;
    if (!l.length) return toast(NOT_READY);
    if (await ask(`Send ${plural(l.length, "email", "emails")} now?`, `Each goes from your Gmail to the address on the job, with your CV attached, and the job is marked applied.${cap && cap.cap ? ` Today's limit is ${cap.cap}; ${cap.today} already sent.` : ""}`, `Send ${plural(l.length, "email", "emails")}`)) startTask({ action: "send", job_ids: l }); },
  followups: async () => { if (!S.state || !S.state.due.length) return toast("No follow-ups are due");
    if (await ask(`Send ${plural(S.state.due.length, "follow-up", "follow-ups")} now?`, "The stored follow-up text goes to each recruiter who has not replied.", "Send follow-ups")) startTask({ action: "followups" }); },
  digest: async () => { try {
      const r = await fetch(`/api/digest?min_score=${S.view === "matches" && S.f.score ? S.f.score : 75}&token=${encodeURIComponent(TOKEN)}`);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "The digest could not be made. Reload the page and try again");
      const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = `job-matches-${new Date().toISOString().slice(0, 10)}.md`; a.click(); URL.revokeObjectURL(a.href);
      toast("Digest downloaded");
    } catch (e) { fail(e); } },
  replies: () => S.state.check_replies ? startTask({ action: "replies" })
    : toast("Looking in Gmail for replies is switched off. Switch it on under Settings, Search and limits", true),
  "draft-one": async () => { if (S.detail.application && S.detail.application.outreach_subject && !await ask("Write the email again?", "The current draft, including your edits, is replaced.", "Write it again")) return; startTask({ action: "email", job_ids: [S.sel] }); },
  "contacts-one": () => startTask({ action: "contacts", job_ids: [S.sel] }),
  cover: () => startTask({ action: "cover-letter", job_ids: [S.sel] }),
  "copy-cover": () => navigator.clipboard.writeText(S.detail.application.cover_letter).then(() => toast("Cover letter copied")),
  answers: () => startTask({ action: "answers", job_ids: [S.sel] }),
  cv: async () => { const c = S.detail.application && S.detail.application.cv;
    if (c && c.found && !await ask("Write the CV again?", "The file is replaced, and this job's email goes back to your usual CV until you switch the new one on.", "Write it again")) return;
    startTask({ action: "cv", job_ids: [S.sel] }); },
  "cv-open": async () => { const tab = window.open("", "_blank");  // opened at the click itself; a tab opened later would be blocked
    try { const r = await fetch(`/api/cv?id=${S.sel}`, { headers: { "X-Token": TOKEN } });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "The CV could not be opened. Reload the page and try again");
      const url = URL.createObjectURL(await r.blob());
      if (tab) tab.location = url;
      else { const a = document.createElement("a"); a.href = url; a.download = S.detail.application.cv.name; a.click(); toast("CV downloaded"); }
    } catch (e) { if (tab) tab.close(); fail(e); } },
  "cv-remove": async () => { if (await ask("Remove the CV written for this job?", "The file is deleted. This job's email carries your usual CV.", "Remove")) change("/api/cv", { job_id: S.sel, remove: true }); },
  prep: async () => { if (S.detail.application && S.detail.application.interview_prep && !await ask("Write the preparation again?", "The questions you have now are replaced.", "Write it again")) return;
    startTask({ action: "prep", job_ids: [S.sel] }); },
  "copy-answer": b => navigator.clipboard.writeText(S.detail.application.answers[b.dataset.to]).then(() => toast(`${ANSWERS.find(([k]) => k === b.dataset.to)[1]} copied`)),
  "copy-detail": b => { const [l, v] = S.detail.details[+b.dataset.to]; navigator.clipboard.writeText(v).then(() => toast(`${l} copied`)); },
  sheet: b => { S.preview = b.dataset.to === "preview";
    $("#sheet").classList.toggle("preview", S.preview);
    $$("[data-act=sheet]").forEach(x => x.setAttribute("aria-pressed", String((x.dataset.to === "preview") === S.preview)));
    $("#stale").hidden = !(S.preview && $("#body").value !== S.detail.application.outreach_body);
    fit(); },
  "save-draft": () => change("/api/draft", { job_id: S.sel, subject: $("#subj").value, body: $("#body").value }),
  "send-one": async () => { const a = S.detail.application;
    if (S.dirty && !await change("/api/draft", { job_id: S.sel, subject: $("#subj").value, body: $("#body").value }, false)) return;
    if (await ask("Send this email now?", `It goes from your Gmail to ${a.contact_email} with your CV attached.`, "Send email")) change("/api/send", { job_id: S.sel, general: a.contact_kind === "general" }); },
  "send-again": async () => { const a = S.detail.application;
    if (S.dirty && !await change("/api/draft", { job_id: S.sel, subject: $("#subj").value, body: $("#body").value }, false)) return;
    if (await ask("Send this email again?", `It already went on ${when(a.outreach_sent_at)}. This sends the letter as it is now a second time, to ${a.contact_email}, with your CV attached.`, "Send again")) change("/api/send", { job_id: S.sel, general: a.contact_kind === "general", again: true }); },
  "save-note": async () => { const note = $("#note").value; await keepDraft(); change("/api/note", { job_id: S.sel, note }); },
  "save-addr": async () => { const email = $("#addr").value.trim(); await keepDraft(); change("/api/contact", { job_id: S.sel, email }); },
  "followup-done": () => change("/api/followup-done", { job_id: S.sel }),
  status: b => change("/api/status", { job_id: S.sel, status: b.dataset.to }),
  "apply-first": () => { const l = ids(() => true); l.length ? openJob(l[0]) : toast("Your shortlist is empty"); },
  back: () => closeDrawer(),
  prev: () => step(-1),
  next: () => step(1),
  dedupe: async () => { if (await ask("Merge the duplicates?", "Each duplicate is folded into the copy marked Keep. This cannot be undone.", "Merge duplicates")) startTask({ action: "dedupe" }); },
  "notify-test": () => startTask({ action: "notify-test" }),
  "sched-on": async () => { try { toast((await api("/api/schedule", { action: "install", time: $("#schedtime").value })).message); loadPage(); } catch (e) { fail(e); } },
  "sched-off": async () => { try { toast((await api("/api/schedule", { action: "remove" })).message); loadPage(); } catch (e) { fail(e); } },
  "cfg-save": async () => { const values = {};
    $$("[data-cfg]").forEach(el => values[el.dataset.cfg] = el.type === "checkbox" ? el.checked : el.value);
    try { const r = await api("/api/config", { values }); toast(r.message); S.cfg = r; S.formDirty = false; renderPage(); refresh(); } catch (e) { fail(e); } },
  "cfg-reset": async () => { if (!await ask(`Go back to ${S.cfg.file}?`, "The settings changed on this page are dropped. Site switches stay as they are.", "Go back")) return;
    try { const r = await api("/api/config", { values: Object.fromEntries(S.cfg.fields.map(f => [f.key, null])) }); toast(r.message); S.cfg = r; S.formDirty = false; renderPage(); refresh(); } catch (e) { fail(e); } },
  "sites-ill": b => { const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(on));
    $("#illbar").hidden = !on; $("#sitefind").value = ""; $$(".sites .sw").forEach(l => l.hidden = on && !("ill" in l.dataset)); },
  "sites-ill-off": async () => { const names = ILL(S.cfg.sites).map(x => x.name);
    if (!names.length || !await ask(`Switch off ${plural(names.length, "site", "sites")}?`, `${names.join(", ")}. Searches will skip them. You can switch any of them on again here.`, `Switch off ${plural(names.length, "site", "sites")}`)) return;
    try { const r = await api("/api/config", { sites: Object.fromEntries(names.map(n => [n, false])) }); toast(`${plural(names.length, "site is", "sites are")} switched off`); S.cfg = r; renderPage(); refresh(); } catch (e) { fail(e); } },
  "tpl-show": b => { S.tpl = b.dataset.to;
    $$("[data-pane]").forEach(p => p.hidden = p.dataset.pane !== S.tpl);
    $$("[data-act=tpl-show]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.to === S.tpl))); },
  "save-tpl": async () => { try { toast((await api("/api/template", { text: $("#tpl").value })).message); } catch (e) { fail(e); } },
  "save-ctpl": async () => { try { toast((await api("/api/template", { kind: "cover", text: $("#ctpl").value })).message); } catch (e) { fail(e); } },
  "save-gtpl": async () => { try { toast((await api("/api/template", { kind: "general", text: $("#gtpl").value })).message); } catch (e) { fail(e); } },
  hr: () => { if ($("#adddlg").open) $("#adddlg").close(); $("#hrresult").innerHTML = ""; $("#hrdlg").showModal(); $("#hrtext").focus(); },
  "close-hr": () => $("#hrdlg").close(),
  "hr-go": async () => { const text = $("#hrtext").value.trim(), box = $("#hrresult");
    if (!text) { box.innerHTML = `<p><span class="tag c-red">Paste at least one email address</span></p>`; return; }
    try {
      const r = await api("/api/hr-contacts", { text, country: $("#hrcountry").value });
      box.innerHTML = `<p style="color:var(--t1)"><b>${esc(r.message)}</b> ${r.added.length ? "They are on your shortlist with no email drafted yet." : ""}</p>`
        + (r.skipped.length ? `<ul class="history" style="margin:0 0 12px;max-height:152px;overflow:auto">${r.skipped.map(([line, why]) => `<li><b>${esc(line)}</b>: ${esc(why)}</li>`).join("")}</ul>` : "");
      if (r.added.length) { $("#hrtext").value = r.skipped.map(x => x[0]).join("\n"); await refresh(); }
    } catch (e) { box.innerHTML = `<p><span class="tag c-red">${esc(tidy(e.message))}</span></p>`; } },
  "theme-light": () => setTheme("light"),
  "theme-dark": () => setTheme("dark"),
  quit: async () => { if (await ask("Stop Job Search?", "Any task that is running is stopped too. Nothing saved is lost.", "Stop Job Search")) { try { await api("/api/quit", {}); } catch {} clearInterval(S.timer);
    document.body.innerHTML = '<div style="min-height:100vh;display:grid;place-content:center"><div class="empty"><h3>Job Search has stopped</h3>Open Job Search again to start it</div></div>'; } },
};
const go = x => x.startsWith("v:") ? showView(x.slice(2)) : A[x]();
const PALETTE = [
  ["Find new jobs", "search every site and score", "run"], ["Collect jobs without scoring", "cheaper, scored next time", "run-noscore"],
  ["Score waiting jobs", "found earlier, no new search", "score"],
  ["Run the morning routine", "search, digest, summary email", "daily"], ["Add a job from a post", "LinkedIn, WhatsApp, email", "add"], ["Add HR addresses", "general applications, no specific job", "hr"],
  ["Draft emails", "shortlisted jobs with no draft yet", "draft-all"], ["Look for addresses", "on each company's own site", "contacts-all"],
  ["Save drafts to Gmail", "review and send from Gmail", "gmail-all"], ["Send ready emails", "from your Gmail, CV attached", "send-all"],
  ["Send follow-ups", "the ones that are due", "followups"], ["Check for replies", "looks in Gmail, when switched on", "replies"], ["Start applying", "opens the first shortlisted job", "apply-first"], ["Download digest", "top matches as a Markdown file", "digest"],
  ["Go to Shortlist", "", "v:shortlist"], ["Go to In progress", "applications and jobs set aside", "v:progress"],
  ["Go to Follow-ups", "", "v:followups"], ["Go to All matches", "every scored job", "v:matches"], ["Go to Insights", "missing skills, your week, sites", "v:insights"],
  ["Go to Activity", "past searches, task output", "v:activity"], ["Go to Settings", "limits, keywords, sites on or off", "v:settings"],
  ["Schedule the morning routine", "", "v:settings"], ["Edit the email template", "", "v:settings"], ["Edit the cover letter template", "", "v:settings"], ["Edit the general email template", "", "v:settings"],
  ["Back up now", "the database and the code", "backup"], ["Merge duplicate jobs", "", "v:settings"], ["Send a test notification", "", "notify-test"], ["Import your resume", "PDF or text", "resume"],
  ["Switch to the light look", "theme", "theme-light"], ["Switch to the dark look", "theme", "theme-dark"],
  ["Update the database", "", "migrate"], ["Stop the running task", "", "stop"],
];
function openPalette() { const d = $("#palette"), q = $("#pq"); q.value = ""; d.showModal(); drawPalette(); q.focus(); }
function drawPalette() {
  const q = $("#pq").value.toLowerCase().trim();
  const hits = PALETTE.filter(([l, h]) => !q || (l + " " + h).toLowerCase().includes(q));
  $("#plist").innerHTML = hits.map(([l, h, a], i) => `<li><button data-p="${a}" class="${i ? "" : "cur"}">${esc(l)}<span>${esc(h)}</span></button></li>`).join("") || `<li class="empty">No action matches that</li>`;
}
function runPalette(a) { $("#palette").close(); go(a); }

async function askApplied() {
  const p = S.applyPending;
  if (!p || document.hidden || document.querySelector("dialog[open]")) return;
  S.applyPending = null;
  if (await ask("Did you apply?", `${p.title}${named(p.company) ? " at " + p.company : ""}. Yes moves it to In progress and records today's date.`, "Yes, I applied", "Not yet"))
    change("/api/status", { job_id: p.id, status: "applied" });
}
document.addEventListener("visibilitychange", askApplied);
window.addEventListener("focus", askApplied);
window.addEventListener("resize", fit);
document.addEventListener("click", e => {
  const t = e.target;
  if (t.closest("[data-apply]") && S.detail) S.applyPending = { id: S.detail.job.id, title: S.detail.job.title, company: S.detail.job.company };
  const p = t.closest("[data-p]"); if (p) return runPalette(p.dataset.p);
  const act = t.closest("[data-act]");
  if (!act || act.dataset.act !== "run-menu") $("#runmenu").hidden = true;
  if (act && act.id === "clipper") e.preventDefault();  // here it is only shown; it does its work from the bookmarks bar
  if (act) { if (act.closest(".sidebar") && act.dataset.act !== "menu") setMenu(false); if (!act.disabled) A[act.dataset.act](act); return; }
  const g = t.closest("[data-go]"); if (g) return go(g.dataset.go);
  const pg = t.closest("[data-page]"); if (pg) { if (!pg.disabled) { S.page = +pg.dataset.page; renderList(); } return; }
  const th = t.closest("th[data-sort]"); if (th) return sortBy(th.dataset.sort);
  const job = t.closest("[data-job]"); if (job) return openJob(+job.dataset.job);
  const v = t.closest("[data-view]"); if (v) showView(v.dataset.view);
});
document.addEventListener("input", e => {
  const id = e.target.id;
  if (id === "subj" || id === "body" || id === "note" || id === "addr") S.dirty = true;
  if (id === "body") fit();
  if (id === "addr") fitAddr();
  if (id === "tq") { S.q = e.target.value; S.page = 0; renderList(); }
  if (id === "pq") drawPalette();
  if (e.target.closest("#page") && e.target.matches("textarea,[data-cfg]")) S.formDirty = true;  // do not redraw over what is being typed
  if (id === "sitefind") { const q = e.target.value.trim().toLowerCase(); $$(".sites .sw").forEach(l => l.hidden = !!q && !l.dataset.name.includes(q)); }
});
document.addEventListener("change", e => {
  const el = e.target, id = el.id;
  if (id === "cvattach") return change("/api/cv", { job_id: S.sel, attach: el.checked });
  if (id === "f-country") S.f.country = el.value;
  if (id === "f-score") S.f.score = +el.value;
  if (id === "f-posted") S.f.posted = +el.value;
  if (id === "f-extra") S.f.extra = el.value;
  if (id.startsWith("f-")) { S.page = 0; renderList(); }
  if (id === "onesite" && el.value) { startTask({ action: "run", source: el.value }); el.value = ""; $("#runmenu").hidden = true; }
  if (el.dataset.site) return api("/api/config", { sites: { [el.dataset.site]: el.checked } }).then(r => {
    toast(r.message); S.cfg = r; const now = r.sites.find(x => x.name === el.dataset.site);
    el.closest(".sw").toggleAttribute("data-ill", ill(now)); if ($("#illcount")) $("#illcount").textContent = ILL(r.sites).length;
    el.closest(".sw").classList.toggle("changed", now.changed); $("#sitecount").textContent = `${r.sites.filter(x => x.enabled).length} of ${r.sites.length} on`; refresh();
  }).catch(e => { el.checked = !el.checked; fail(e); });
  if (el.dataset.browser !== undefined) return api("/api/config", { browsers: { [el.dataset.browser]: el.value } }).then(r => {
    toast(r.message); S.cfg = r; el.closest(".brow").classList.toggle("changed", r.sites.find(x => x.name === el.dataset.browser).browser_changed);
    api("/api/settings").then(g => { S.settings = g; }).catch(() => {});  // the Setup line names the boards on Browserbase
  }).catch(e => { el.value = (S.cfg.sites.find(x => x.name === el.dataset.browser) || {}).browser || ""; fail(e); });
  if (el.dataset.cfg && el.type === "checkbox") S.formDirty = true;
  if (id === "setstatus" && el.value) change("/api/status", { job_id: S.sel, status: el.value });
  if (id === "resumefile" && el.files[0]) { const f = el.files[0];
    startTask({ action: "profile", raw: { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } } }); el.value = ""; }
});
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); return openPalette(); }
  if ($("#palette").open) {
    const items = $$("#plist button"), i = items.findIndex(b => b.classList.contains("cur"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (!items.length) return;
      items[i]?.classList.remove("cur"); const n = items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]; n.classList.add("cur"); n.scrollIntoView({ block: "nearest" }); }
    if (e.key === "Enter" && items[i]) { e.preventDefault(); runPalette(items[i].dataset.p); }
    return;
  }
  if (document.querySelector("dialog[open]")) return;
  // Without preventDefault the same key press would also dismiss the "close without saving?" question it opens.
  if (e.key === "Escape" && document.body.classList.contains("reading")) { e.preventDefault(); return closeDrawer(); }
  const at = e.target instanceof Element ? e.target : document.body;
  if (e.key === "Enter" || e.key === " ") {
    if (at.matches("tr.row")) { e.preventDefault(); return openJob(+at.dataset.job); }
    if (at.matches("th[data-sort]")) { e.preventDefault(); return sortBy(at.dataset.sort); }
  }
  if (at.matches("input,textarea,select") || !S.state || !LIST.includes(S.view)) return;
  if (e.key === "j") step(1);
  if (e.key === "k") step(-1);
});
$("#palette").addEventListener("click", e => { if (e.target.id === "palette") e.target.close(); });
if (!/Mac/.test(navigator.platform)) $("#kbd").textContent = "Ctrl";
setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark", true);

addEventListener("hashchange", takeClip);
(async () => {
  await refresh();
  connectFeed();
  takeClip();
  // With the feed open the page is told about changes; it still looks once a minute in case one was missed.
  S.timer = setInterval(() => { if (!document.hidden && !S.polling && !(S.live && Date.now() - S.refreshed < 60000)) refresh(); }, 6000);
})();
