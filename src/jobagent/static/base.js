// Names, small helpers and the pieces every screen shares.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ic = (n, c = "") => `<svg class="ic ${c}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const PAGE = 8, LIST = ["shortlist", "progress", "followups", "matches"];
const ACTIVE = ["applied", "interviewing", "offer"], ASIDE = ["skipped", "rejected", "withdrawn"];
const calm = matchMedia("(prefers-reduced-motion:reduce)").matches;
const S = { state: null, inited: false, view: "shortlist", sel: null, detail: null, matches: null, q: "", page: 0,
            f: { country: "", score: 0, posted: 0, extra: "" }, sort: { key: "", dir: 1 }, lsig: "", wsig: "",
            lines: [], taskId: 0, wasRunning: false, polling: false, dirty: false, dealt: false, tpl: "tpl", preview: false, dismissed: 0, settings: null, insights: null };
const VIEWS = {
  shortlist: ["Shortlist", "Jobs that scored well against your resume. Draft the email, find the address, send."],
  progress: ["In progress", "Applications under way, and the jobs you set aside"],
  followups: ["Follow-ups", "Emails that have had no reply"],
  matches: ["All matches", "Every job scored against your resume, newest first"],
  insights: ["Insights", "Your week, the skills you are missing, and which sites deliver"],
  activity: ["Activity", "What the program is doing now, and past searches"],
  settings: ["Settings", "Setup, the morning routine, your templates and limits"],
};
const HOT = { score: ["scored", "shortlisted"], run: ["found", "scored"], daily: ["found", "scored", "shortlisted"], add: ["found", "scored", "shortlisted"], contacts: ["shortlisted"], email: ["shortlisted"],
              send: ["shortlisted", "emailed", "applied"], "gmail-drafts": ["shortlisted"], "cover-letter": ["shortlisted"], answers: ["shortlisted"], followups: ["due"] };
const STATUS_C = { shortlisted: "c-paper", applied: "c-blue", interviewing: "c-amber", offer: "c-green", rejected: "c-red", skipped: "c-aside", withdrawn: "c-aside" };
const COUNTRIES = [["UAE", /\b(uae|united arab emirates|dubai|abu dhabi|sharjah|ajman)\b/], ["Saudi Arabia", /\b(saudi|ksa|riyadh|jeddah|dammam|khobar)\b/], ["Qatar", /\b(qatar|doha)\b/],
  ["India", /\b(india|ahmedabad|gandhinagar|bengaluru|bangalore|pune|hyderabad|mumbai|chennai|gurugram|gurgaon|noida|delhi|kolkata)\b/]];
const countryOf = loc => { const l = (loc || "").toLowerCase(); return (COUNTRIES.find(c => c[1].test(l)) || ["Remote"])[0]; };
const countryName = c => c === "Remote" ? "Remote or other" : c;

async function api(path, body, raw) {
  const opt = { headers: { "X-Token": TOKEN } };
  if (raw) { opt.method = "POST"; opt.body = raw.body; Object.assign(opt.headers, raw.headers); }
  else if (body !== undefined) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, opt); }
  catch { throw new Error("The page lost contact with the job search program. Open Job Search again to restart it."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || (res.status === 403 ? "This page is older than the running program. Reload it" : "The program could not do that. Reload the page and try again"));
  return data;
}
function toast(msg, bad) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : ""); t.innerHTML = ic(bad ? "alert" : "check") + "<span></span>"; t.lastChild.textContent = tidy(msg);
  $("#toasts").append(t); setTimeout(() => t.remove(), bad ? 9000 : 4500);
}
const fail = e => toast(e.message, true);
function setMenu(open) {  // the menu slides only when it is opened or closed by hand, not when the window is resized
  const b = document.body;
  if (b.classList.contains("menu-open") === open) return;
  b.classList.add("menu-moving"); b.classList.toggle("menu-open", open);
  clearTimeout(setMenu.timer); setMenu.timer = setTimeout(() => b.classList.remove("menu-moving"), 400);
}
function ask(title, text, ok, no = "Cancel") {
  const d = $("#ask");
  $("h2", d).textContent = title; $("p", d).textContent = tidy(text); $(".primary", d).textContent = ok; $("[value=no]", d).textContent = no;
  d.showModal();
  return new Promise(res => {
    const done = v => { d.close(); d.onclick = null; d.oncancel = null; res(v); };
    d.onclick = e => { if (e.target.value) done(e.target.value === "yes"); };
    d.oncancel = () => done(false);
  });
}
function ago(iso) {
  if (!iso) return "";
  const h = Math.max(0, (Date.now() - new Date(iso)) / 36e5);
  return h < 1 ? "just now" : h < 24 ? `${Math.floor(h)}h ago` : `${Math.floor(h / 24)}d ago`;
}
const day = iso => iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
const when = iso => iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const tier = s => s == null ? "s0" : s >= 85 ? "s4" : s >= 75 ? "s3" : s >= 60 ? "s2" : "s1";
const statusOf = r => r.status || r.application_status || "";
const http = u => /^https?:\/\//.test(u || "");
const size = n => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const tidy = s => { s = String(s ?? "").trim(); return /[.!?]\s/.test(s) ? s : s.replace(/\.$/, ""); };  // a one-sentence message carries no full stop
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : "";
// A site that is on but has failed, or has brought no job in its last three searches or more.
const ill = x => !!(x.enabled && x.health && (x.health.last === "failed" || x.health.dry >= 3));
const ILL = sites => sites.filter(ill);
const healthMark = x => { const h = x.health;
  if (!h || !(h.last === "failed" || h.dry >= 3)) return "";
  const since = h.delivered_at ? ` It last listed jobs on ${day(h.delivered_at)}.` : " It has listed no job in the last 60 days.";
  return h.last === "failed" ? `<em class="ill bad" title="${esc("Its last search failed: " + h.reason + "." + since)}">failed</em>`
    : `<em class="ill" title="${esc(`No job in its last ${h.dry} searches.` + since)}">no jobs</em>`; };
// The bookmark for the person's own browser. On a job's page it takes the selected text (or the whole page's), the title and
// the link, and opens this page with them after the #, a part of the address that is never sent to any server.
const clipper = () => "javascript:" + `(()=>{var s=String(getSelection()).trim(),t=(s||document.body.innerText||'').slice(0,12000),`
  + `u='${location.origin}/#clip='+encodeURIComponent(JSON.stringify({u:location.href,h:document.title,t:t}));window.open(u,'_blank')||(location.href=u)})()`;
// A picture of a post. The model reads text best at full size, so a tall phone screenshot is cut into
// pieces with a small overlap instead of being shrunk; the model writes the overlapping line once.
const PIECE = { width: 1000, height: 1400, overlap: 60, most: 8 };
async function pieces(file) {
  let bmp;
  try { bmp = await createImageBitmap(file); } catch { throw new Error(`${file.name || "That picture"} could not be opened. Use a PNG, JPG, WebP or GIF file`); }
  const most = PIECE.most * (PIECE.height - PIECE.overlap) + PIECE.overlap;
  const scale = Math.min(1, PIECE.width / bmp.width, most / bmp.height), w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale), out = [];
  for (let y = 0; ; y += PIECE.height - PIECE.overlap) {
    const ph = Math.min(PIECE.height, h - y), c = document.createElement("canvas");
    c.width = w; c.height = ph;
    c.getContext("2d").drawImage(bmp, 0, y / scale, bmp.width, ph / scale, 0, 0, w, ph);
    out.push(await asBase64(c));
    if (y + ph >= h) break;
  }
  if (bmp.close) bmp.close();
  return out;
}
async function asBase64(canvas) {
  const blob = (type, q) => new Promise(r => canvas.toBlob(r, type, q));
  let b = await blob("image/png");
  if (b.size > 3.5e6) b = await blob("image/jpeg", 0.92);  // a photo rather than a screenshot
  const url = await new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = no; f.readAsDataURL(b); });
  return url.slice(url.indexOf(",") + 1);
}
async function readPictures(files) {  // fill the Add from a post box with the text of the pictures; the person checks it and adds the job
  const pics = [...files].filter(f => f.type.startsWith("image/"));
  if (!pics.length) return toast("That is not a picture. Use a PNG, JPG, WebP or GIF file", true);
  if (S.reading) return toast("A picture is being read. Wait for it to finish", true);
  const dlg = $("#adddlg"), go = $('[data-act="add-go"]', dlg), busy = $("#addpicbusy");
  S.reading = true; go.disabled = true; dlg.classList.add("reading"); $("#addpicask").hidden = true; busy.hidden = false;
  busy.textContent = `Reading ${pics.length === 1 ? "the picture" : pics.length + " pictures"}. This takes a few seconds`;
  try {
    const parts = [];
    for (const f of pics) parts.push(...await pieces(f));
    if (parts.length > 10) throw new Error("That is too much at once. Add the pictures a few at a time");
    const r = await api("/api/read-picture", { pictures: parts }), box = $("#addtext");
    box.value = (box.value.trim() ? box.value.trim() + "\n\n" : "") + r.text;
    toast("Text read from the picture. Check it, the email address above all, then add the job");
  } catch (e) { fail(e); }
  finally { S.reading = false; go.disabled = false; dlg.classList.remove("reading"); $("#addpicask").hidden = false; busy.hidden = true; }
}
function takeClip() {  // a post brought over by that bookmark: fill the Add from a post box and leave the adding to the person
  if (!location.hash.startsWith("#clip=")) return;
  const raw = location.hash.slice(6); let c = null;
  try { c = JSON.parse(decodeURIComponent(raw)); } catch (e) { try { c = JSON.parse(raw); } catch (e2) { c = null; } }
  history.replaceState(null, "", location.pathname);  // the post's text does not stay in the address bar or the history
  if (!c || typeof c.t !== "string" || !c.t.trim()) return toast("That page gave no text. Select the post's text and click the bookmark again", true);
  const title = typeof c.h === "string" && c.h.trim() ? `Page title: ${c.h.trim()}\n\n` : "";
  $("#addtext").value = (title + c.t.trim()).slice(0, 20000);
  $("#addurl").value = typeof c.u === "string" && /^https?:\/\//.test(c.u) ? c.u.slice(0, 2000) : "";
  if (!$("#adddlg").open) A.add();
  toast("Post brought over from your browser. Check it, then add the job");
}
const ANSWERS = [["why_this_role", "Why this role"], ["why_you", "Why you"], ["about_you", "About you"], ["key_skills", "Key skills"], ["experience", "Experience"]];
const STATUS_L = { shortlisted: "Shortlisted", applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected", skipped: "Skipped", withdrawn: "Withdrawn" };
const RUN_L = { succeeded: "Finished", partial: "Partly finished", failed: "Failed", running: "Running" };
// Mirrors company_named() in models.py: a posting that gives no real company name.
const named = c => !/^(unknown|undisclosed|anonymous|hidden|none|company|employer|n\/?a|-*|not (disclosed|specified|mentioned|given|available|named))$|confidential|stealth|\(name not given\)$/i.test((c || "").trim());
const initials = n => (n || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
function postmark(iso) {  // the one signature: a dated mark on anything that has been sent
  const d = new Date(iso), mon = d.toLocaleDateString(undefined, { month: "short" });
  return `<svg class="pm" viewBox="0 0 54 36" role="img" aria-label="Emailed ${d.getDate()} ${esc(mon)}"><title>Emailed ${esc(when(iso))}</title><circle cx="18" cy="18" r="17.5"/><text x="18" y="16">${d.getDate()}</text><text x="18" y="28">${esc(mon)}</text><path d="M38 11q2-2 4 0t4 0 4 0 4 0M38 18q2-2 4 0t4 0 4 0 4 0M38 25q2-2 4 0t4 0 4 0 4 0"/></svg>`;
}
const grow = root => requestAnimationFrame(() => requestAnimationFrame(() => $$("u[data-w]", root).forEach(u => u.style.width = u.dataset.w + "%")));
