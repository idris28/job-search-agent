// The panel that opens for one job.
// One of the page's scripts. They are plain scripts loaded in this order: base.js, chrome.js, lists.js, drawer.js, pages.js, actions.js.
// Top-level names are shared between them, as they were when all of this was one file.

/* ---------- job drawer ---------- */
async function openJob(id, keep) {
  if (S.dirty && id !== S.sel && !await ask("Leave without saving?", "Your changes to this job's draft or note are not saved yet.", "Leave")) return;
  S.sel = id; S.dirty = false; if (!keep) S.preview = false;
  if (LIST.includes(S.view)) renderList();
  document.body.classList.add("reading"); $("#detail").inert = false;
  try { S.detail = await api(`/api/job?id=${id}`); } catch (e) { fail(e); if (!keep) closeDrawer(true); return; }
  if (S.sel === id) renderDetail(keep);
}
async function closeDrawer(force) {
  if (!force && S.dirty && !await ask("Close without saving?", "Your changes to this job's draft or note are not saved yet.", "Close")) return false;
  S.dirty = false; S.sel = null; S.detail = null;
  document.body.classList.remove("reading"); $("#detail").inert = true;
  if (S.state && LIST.includes(S.view)) renderList();
  return true;
}
function step(delta) {
  const rows = shown(), i = rows.findIndex(r => r.job_id === S.sel), n = rows[i + delta];
  if (!n) return;
  S.page = Math.floor((i + delta) / PAGE); openJob(n.job_id);
}
function renderDetail(keep) {
  const d = S.detail, el = $("#detail");
  if (!d) return;
  const j = d.job, m = d.match, a = d.application, s = a ? a.status : "";
  const sc = m ? m.score : null;
  const chips = (xs, c) => xs && xs.length ? `<ul class="chipsl">${xs.map(x => `<li class="tag ${c}">${esc(x)}</li>`).join("")}</ul>` : "";
  const stBtn = (to, label, cls = "") => `<button class="btn ${cls}" data-act="status" data-to="${to}">${label}</button>`;
  const canApply = http(j.url) && (s === "" || s === "shortlisted"), pri = canApply ? "" : "primary";
  const moves = { "": stBtn("shortlisted", "Add to shortlist", pri) + stBtn("skipped", "Not for me"),
    shortlisted: stBtn("applied", "I applied", pri) + stBtn("skipped", "Skip"),
    applied: stBtn("interviewing", "Got an interview", "primary") + stBtn("rejected", "Rejected"),
    interviewing: stBtn("offer", "Got an offer", "primary") + stBtn("rejected", "Rejected") }[s] ?? stBtn("shortlisted", "Back to shortlist");
  const pay = j.salary_text || (m && m.salary_estimate);
  const rows = S.state && LIST.includes(S.view) ? shown() : [], at = rows.findIndex(r => r.job_id === j.id);

  let mail = "", hasDraft = !!(a && a.outreach_subject);
  const sentAt = a && a.outreach_sent_at;
  const info = !a ? "" : a.contact_email
    ? `${a.contact_kind ? `<span class="tag ${a.contact_kind === "general" ? "c-amber" : "c-slate"}">${esc(cap(a.contact_kind))} address</span>` : ""}${http(a.contact_source) ? `<a href="${esc(a.contact_source)}" target="_blank" rel="noopener noreferrer">Where it was found</a>` : ""}${sentAt ? `<span>Sent ${esc(when(sentAt))}</span>` : ""}`
    : "No address yet. Type one you found yourself, or let the agent look on the company's site.";
  const toLine = !a ? "" : `<div class="ln"><label for="addr">To</label><input class="field" id="addr" type="text" inputmode="email" autocapitalize="off" autocomplete="off" spellcheck="false" data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other" placeholder="recruiter@company.com" value="${esc(a.contact_email)}">
      <button class="btn sm" data-act="save-addr">Save address</button>${a.contact_email ? "" : `<button class="btn sm" data-act="contacts-one">${ic("at")}Look for one</button>`}
      ${info ? `<p class="toinfo">${info}</p>` : ""}</div>`;
  const stamp = sentAt ? postmark(sentAt) : "";
  if (hasDraft) {
    const canSend = s === "shortlisted" && a.contact_email && !a.outreach_sent_at;
    // Where the Send button would be, say why it is not there.
    const after = a.follow_up_sent_at ? "; its follow-up has gone too" : a.reply_kind === "reply" ? "; a reply came, so it gets no follow-up"
      : a.reply_kind === "bounced" ? "; it was not delivered, so it gets no follow-up" : d.due ? "; its follow-up is due now" : s === "applied" ? "; its follow-up goes out from the Follow-ups screen when it is due" : "";
    // A job is emailed once by itself. Writing to it a second time is possible, one job at a time, on purpose.
    const canResend = sentAt && a.contact_email;
    const whyNot = canSend ? "" : sentAt ? `Sent ${when(sentAt)}${after}. ${canResend ? "Send again writes to the same address once more." : "Add an address in the To line to send it again."}`
      : s !== "shortlisted" ? `${s ? "Marked " + (STATUS_L[s] || s).toLowerCase() : "Not on your shortlist"}, so this email is not sent. Set the status to Shortlisted to send it.`
      : "Add an address in the To line to send this email";
    const answer = a.reply_kind === "reply" ? `<p id="replyline"><span class="tag c-green">Replied ${esc(when(a.reply_at))}</span>${a.reply_subject ? ` with the subject "${esc(a.reply_subject)}"` : ""}. Read it in Gmail, then set the status at the top of this panel</p>`
      : a.reply_kind === "bounced" ? `<p id="replyline"><span class="tag c-red">Not delivered</span> ${esc(a.contact_email || "The address")} refused the email on ${esc(when(a.reply_at))}. Put another address in the To line and send again</p>`
      : a.reply_kind === "automatic" ? `<p id="replyline"><span class="tag c-slate">Automatic reply ${esc(when(a.reply_at))}</span>${a.reply_subject ? ` with the subject "${esc(a.reply_subject)}"` : ""}. Its follow-up still goes out when it is due</p>` : "";
    mail = `${answer}${a.unfilled.length ? `<p><span class="tag c-red">Fill in before sending: ${esc(a.unfilled.join(", "))}</span></p>` : ""}
      ${a.posting_open === false ? `<p><span class="tag c-red">The posting looked closed when this was drafted</span></p>` : ""}
      <div class="desk"><div class="sheet${S.preview ? " preview" : ""}" id="sheet">
        <div class="lines">${toLine}<div class="ln"><label for="subj">Subject</label><input class="field" id="subj" value="${esc(a.outreach_subject)}"></div>${stamp}</div>
        <textarea class="body" id="body" aria-label="Email text">${esc(a.outreach_body)}</textarea>
        <div class="rendered">${a.body_html}</div>
      </div></div>
      <p class="faint" id="stale" hidden>The preview shows the last saved draft. Save the draft to update it.</p>
      <div class="acts">
        <button class="btn" data-act="save-draft">Save draft</button>
        ${canSend ? `<button class="btn primary" data-act="send-one">${ic("send")}Send email</button>` : ""}
        ${canResend ? `<button class="btn" data-act="send-again">${ic("send")}Send again</button>` : ""}
        <button class="btn ghost" data-act="draft-one">Write it again</button>
      </div>
      ${whyNot ? `<p class="faint" id="nosend">${esc(whyNot)}</p>` : ""}
      ${a.follow_up_body ? `<details ${d.due ? "open" : ""}><summary>Follow-up ${a.follow_up_sent_at ? "sent " + esc(day(a.follow_up_sent_at)) : d.due ? "due now" : "for later"}</summary>
        <p><b>${esc(a.follow_up_subject)}</b></p><div class="mail desc">${esc(a.follow_up_body)}</div>
        ${d.due ? `<div class="acts"><button class="btn" data-act="followup-done">I followed up myself</button></div>` : ""}</details>`
      : d.due ? `<details open><summary>Follow-up due now</summary><p>No follow-up text is stored for this job. Write to them yourself, then record it here.</p>
        <div class="acts"><button class="btn" data-act="followup-done">I followed up myself</button></div></details>` : ""}`;
  } else if (s === "shortlisted") {
    mail = `<div class="desk"><div class="sheet"><div class="lines">${toLine}</div>
      <div class="blank"><span>Nothing written yet</span><button class="btn primary" data-act="draft-one">${ic("edit")}Draft the email</button></div></div></div>`;
  } else mail = `<p>Shortlist this job to write to its recruiter</p>`;
  const seg = hasDraft ? `<span class="seg" role="group" aria-label="Show the email"><button data-act="sheet" data-to="edit" aria-pressed="${!S.preview}">Edit</button><button data-act="sheet" data-to="preview" aria-pressed="${!!S.preview}">Preview</button></span>` : "";

  el.innerHTML = `<div class="d-bar">
      <button class="round sm" data-act="back" aria-label="Close">${ic("x")}</button>
      <span class="tag ${STATUS_C[s] || "c-slate"}">${esc(STATUS_L[s] || "Not listed yet")}</span><span class="faint">#${j.id}</span><span class="grow"></span>
      <button class="round sm" data-act="prev" aria-label="Previous job"${at > 0 ? "" : " disabled"}>${ic("left")}</button>
      <button class="round sm" data-act="next" aria-label="Next job"${at >= 0 && at < rows.length - 1 ? "" : " disabled"}>${ic("right")}</button>
    </div>
    <div class="d-head">
      <div><h2>${esc(j.title)}</h2><p class="co">${esc(j.company)}</p><div class="meta"><span>${esc(j.location || "Location not given")}</span>${j.posted_at ? `<span>posted ${esc(ago(j.posted_at))}</span>` : ""}${pay ? `<span>${esc(pay)}</span>` : ""}</div></div>
      ${sc == null ? "" : `<div class="d-score ${tier(sc)}" role="img" aria-label="Match score ${sc} out of 100"><b>${sc}</b><span class="bar"><u style="width:${sc}%"></u></span><span>score out of 100</span></div>`}
    </div>
    <div class="acts">
      ${http(j.url) ? `<a class="btn ${canApply ? "primary" : ""}" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer"${canApply ? " data-apply" : ""}>${ic("link")}${canApply ? "Apply on the job site" : "Open the posting"}</a>` : `<span class="tag c-slate">${isGeneral(j) ? "General application" : "From a pasted post"}: apply by email below</span>`}
      ${moves}
      <select id="setstatus" aria-label="Set another status"><option value="">Other status</option>${["shortlisted", "applied", "interviewing", "offer", "rejected", "withdrawn", "skipped"].filter(x => x !== s).map(x => `<option value="${x}">${STATUS_L[x]}</option>`).join("")}</select>
      ${d.can_delete ? `<button class="btn ghost danger" data-act="delete">Delete entry</button>` : ""}
    </div>
    ${m ? `<div class="block"><h3>Why it matches</h3><p>${esc(m.summary)}</p>${chips(m.matched_skills, "c-green")}
      ${m.missing_skills.length ? `<p class="lbl">Asked for, not on your resume</p>${chips(m.missing_skills, "c-slate")}` : ""}
      ${m.red_flags.length ? `<p class="lbl">Check before applying</p>${chips(m.red_flags, "c-red")}` : ""}</div>` : ""}
    <div class="block"><h3>Email to the recruiter${seg}</h3>${mail}</div>
    <div class="block" id="liblock"><h3>LinkedIn message</h3>${liBlock(a)}</div>
    <div class="block"><h3>Cover letter</h3>${a && a.cover_letter ? `<div class="mail desc">${esc(a.cover_letter)}</div><div class="acts"><button class="btn sm" data-act="copy-cover">${ic("copy")}Copy</button><button class="btn sm ghost" data-act="cover">Write it again</button></div>`
      : `<p>For sites that ask for one</p><button class="btn" data-act="cover">Write a cover letter</button>`}</div>
    <div class="block"><h3>Answers for the application form</h3>
      ${(d.details || []).length ? `<div class="facts">${d.details.map(([l, v], i) => `<button class="fact" data-act="copy-detail" data-to="${i}" aria-label="Copy ${esc(l)}"><span>${esc(l)}</span><b>${esc(v)}</b>${ic("copy")}</button>`).join("")}</div>` : ""}
      ${a && a.answers ? ANSWERS.filter(([k]) => a.answers[k]).map(([k, l]) => `<div class="qa"><div class="qh"><span>${l}</span><button class="btn sm ghost" data-act="copy-answer" data-to="${k}">${ic("copy")}Copy</button></div><p class="desc">${esc(a.answers[k])}</p></div>`).join("")
          + `<div class="acts"><button class="btn sm ghost" data-act="answers">Write them again</button></div>`
        : `<p>Short answers to what a site's form asks, written from your resume and this posting. You paste them in; nothing is submitted for you</p><button class="btn" data-act="answers">Write the answers</button>`}</div>
    <div class="block" id="cvblock"><h3>CV for this job</h3>${cvBlock(a)}</div>
    <div class="block" id="prepblock"><h3>Interview preparation</h3>${prepBlock(a)}</div>
    <div class="block"><h3>Notes</h3><textarea class="field short" id="note" aria-label="Notes" placeholder="Recruiter name, what was said, next step">${esc(a ? a.notes : "")}</textarea>
      <button class="btn" data-act="save-note">Save note</button></div>
    ${d.events.length ? `<div class="block"><h3>History</h3><ul class="history">${d.events.map(e => `<li>${esc(when(e.created_at))}: <b>${esc(STATUS_L[e.to_status] || cap(e.to_status))}</b>${e.note ? ", " + esc(e.note) : ""}</li>`).join("")}</ul></div>` : ""}
    ${j.description ? `<div class="block"><details><summary>Full job description</summary><div class="desc">${esc(j.description)}</div></details></div>` : ""}`;
  fit(); fitAddr();
  if (!keep) { el.scrollTop = 0; $("[data-act=back]", el).focus({ preventScroll: true }); }
}
function liBlock(a) {  // a connection note and a direct message for the recruiter, which the person sends on LinkedIn
  const li = a && a.linkedin;
  if (!li) return `<p>A short note to send with a connection request, and a message for a recruiter you are connected to, written from your resume and this posting. You send them yourself on LinkedIn</p><button class="btn" data-act="linkedin">Write LinkedIn messages</button>`;
  const words = t => t.trim().split(/\s+/).length;
  const part = (key, label, count) => `<div class="qa"><div class="qh"><span>${label} <em class="cnt${key === "note" && li.note.length > 300 ? " over" : ""}">${count}</em></span><button class="btn sm ghost" data-act="copy-li" data-to="${key}">${ic("copy")}Copy</button></div><p class="desc">${esc(li[key])}</p></div>`;
  return part("note", "Connection note", `${li.note.length} of 300 characters`) + part("message", "Message", `${words(li.message)} words`)
    + `<p class="faint">On LinkedIn, choose Connect, then Add a note, and paste the note. A free account can add a note to only a few requests a month, so keep it for the jobs you care most about. Send the message once you are connected, or as an InMail</p>`
    + `<div class="acts"><button class="btn sm ghost" data-act="linkedin">Write them again</button></div>`;
}
function cvBlock(a) {  // the CV written for this job: the resume's own facts, what the posting asks for first
  const cv = a && a.cv;
  if (!cv) return `<p>Your resume arranged for this posting: the same facts, with what this job asks for put first. Nothing is added that your resume does not say</p><button class="btn" data-act="cv">Write a CV for this job</button>`;
  if (!cv.found) return `<p>${esc(cv.name)} is no longer in the resumes folder</p><div class="acts"><button class="btn" data-act="cv">Write it again</button><button class="btn sm ghost" data-act="cv-remove">Remove</button></div>`;
  return `<p>${esc(cv.name)}, written ${esc(when(cv.written_at))}. Read it before you use it</p>
    ${cv.notes.length ? `<div class="cvnotes"><span>Checked against your resume. Taken out, or worth a look</span><ul>${cv.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
    <label class="sw wrap"><input type="checkbox" id="cvattach"${cv.attach ? " checked" : ""}><span>Attach it to this job's email in place of your usual CV</span></label>
    <div class="acts"><button class="btn" data-act="cv-open">${ic("link")}Open the PDF</button><button class="btn sm ghost" data-act="cv">Write it again</button><button class="btn sm ghost" data-act="cv-remove">Remove</button></div>`;
}
function prepBlock(a) {  // what to get ready before an interview for this job
  const p = a && a.interview_prep;
  if (!p) return `<p>Questions this job is likely to bring, with points for each answer from your resume, and what to revise first</p><button class="btn" data-act="prep">Prepare for the interview</button>`;
  const asked = (title, list) => list.length ? `<h4>${title}</h4>${list.map(q => `<details class="pq"><summary>${esc(q.question)}</summary><ul>${q.points.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>`).join("")}` : "";
  const listed = (title, list) => list.length ? `<h4>${title}</h4><ul class="plist">${list.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  return listed("Revise first", p.revise) + asked("Technical questions", p.technical) + asked("About your work", p.experience) + listed("Questions to ask them", p.ask_them)
    + `<div class="acts"><button class="btn sm ghost" data-act="prep">Write it again</button></div>`;
}
function fitAddr() {  // the To box is as wide as its address, so a long one is not cut short; the buttons move down when there is no room
  const a = $("#addr");
  if (!a || !a.offsetParent) return;
  const s = document.createElement("span"), cs = getComputedStyle(a);
  s.style.cssText = `font:${cs.font};letter-spacing:${cs.letterSpacing};position:absolute;visibility:hidden;white-space:pre`;
  s.textContent = a.value || a.placeholder; document.body.append(s);
  a.style.flexBasis = Math.ceil(s.getBoundingClientRect().width) + 36 + "px"; s.remove();  // 28 kept clear at the end, 8 to spare
}
function fit() {  // the sheet grows with the letter, so the whole text is on the page
  const b = $("#body");
  if (b && b.offsetParent) { b.style.height = "auto"; b.style.height = b.scrollHeight + "px"; }
}
async function keepDraft() {  // saving a note or an address must not throw away edits to the draft
  const subj = $("#subj"), body = $("#body");
  if (S.dirty && subj && body && subj.value.trim() && body.value.trim())
    try { await api("/api/draft", { job_id: S.sel, subject: subj.value, body: body.value }); } catch {}
}
async function change(path, body, after = true) {
  try {
    const r = await api(path, body);
    if (r.message) toast(r.message);
    S.dirty = false;
    if (after) { await refresh(); await staleMatches(); if (S.sel) openJob(S.sel, true); }
    else staleMatches();
    return true;
  } catch (e) { fail(e); return false; }
}
