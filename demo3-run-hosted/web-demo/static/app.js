"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-US");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Panels re-render by replacing their markup; put keyboard focus back on the same control afterwards.
function keepFocus(render) {
  const el = document.activeElement;
  const key = el && el.dataset ? ["beat", "preset", "i", "cite"].map((k) => (el.dataset[k] !== undefined ? `[data-${k}="${el.dataset[k]}"]` : "")).join("") : "";
  const id = el && el.id ? `#${el.id}` : "";
  const field = el && el.dataset && el.dataset.f ? `[data-i="${el.dataset.i}"][data-f="${el.dataset.f}"]${el.dataset.r ? `[data-r="${el.dataset.r}"]` : ""}` : "";
  render();
  const next = (id && document.querySelector(id)) || (field && document.querySelector(field)) || (key && document.querySelector(key));
  if (next && next !== document.activeElement) next.focus({ preventScroll: true });
}

const caseId = () => app.data.default_case;
const PROMPTS = {
  sweep: () => `Plan the response to DISRUPT-001 and file it as ${caseId()}.`,
  status: () => `What is on file as ${caseId()} for DISRUPT-001, and what is waiting on whom?`,
  push: () => `Ship 700 a week on Cedar instead, and resubmit as ${caseId()}.`,
  northbank: () => `Can we use Northbank for weeks 3 and 4? Check it against ${caseId()}'s policy gate, but only submit it if it would pass.`,
};
const WRITE_TOOLS = new Set(["submit_recommendation"]);
const ROUTES = ["Cedar", "Birch", "Elm"];

const app = { data: null, session: 1, busy: false, beatsDone: new Set(), rows: [], cites: new Set(), verdict: null, lastOp: "", running: "", justDone: "", flash: false, finaleShown: false };

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const STATUS = { pending_human_approval: "Pending human approval", rejected_by_policy_gate: "Rejected by policy gate" };

// Count a number up from 0 so the audience sees it arrive.
function countUp(el, to, ms = 800) {
  if (reduced() || !to) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3))));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------------------------------------------------------------- pipeline: model -> gate -> case file
const pipeTimers = [];

function layoutPipe() {
  const pipe = $("#pipe"), box = pipe.getBoundingClientRect();
  for (const name of ["model", "gate", "store"]) {
    const r = $(`[data-node="${name}"]`).getBoundingClientRect();
    pipe.style.setProperty(`--x-${name}`, `${(r.left - box.left + r.width / 2) / (parseFloat(getComputedStyle(document.body).zoom) || 1)}px`);
  }
}

function caption(text, tone = "") {
  const el = $("#pipe-caption");
  el.textContent = text;
  el.className = `pipe-caption ${tone}`;
}

function lit(node, cls, at, hold) {
  const el = $(`[data-node="${node}"]`);
  pipeTimers.push(setTimeout(() => el.classList.add(cls), at));
  pipeTimers.push(setTimeout(() => el.classList.remove(cls), at + hold));
}

function pipeFlow(kind, text, tone) {
  const pipe = $("#pipe");
  pipeTimers.splice(0).forEach(clearTimeout);
  for (const n of pipe.querySelectorAll(".node")) n.classList.remove("lit-amber", "lit-red", "lit-blue", "shake");
  layoutPipe();
  pipe.classList.remove("go-accept", "go-reject", "go-check", "go-read");
  void pipe.offsetWidth;
  pipe.classList.add(`go-${kind}`);
  if (kind === "accept") { lit("gate", "lit-amber", 650, 2200); lit("store", "lit-blue", 1450, 2200); }
  if (kind === "check") lit("gate", "lit-amber", 700, 2200);
  if (kind === "reject") { lit("gate", "lit-red", 650, 2600); pipeTimers.push(setTimeout(() => $('[data-node="gate"]').classList.add("shake"), 650)); }
  if (kind === "read") lit("store", "lit-blue", 0, 1200);
  caption(text, tone);
}

function thinking(on) {
  $('[data-node="model"]').classList.toggle("think", on);
  if (on) caption("Model is working out a proposal…");
}

function firstViolation(result) {
  const v = (result.violations || [])[0];
  return v ? v.violation : "";
}

// Map a tool call to something the room can see in the pipeline strip.
function flowForStep(step) {
  const r = step.result && typeof step.result === "object" ? step.result : {};
  if (step.tool === "submit_recommendation" && r.status === "pending_human_approval") {
    pipeFlow("accept", "Accepted by the gate and recorded as pending human approval. Not approved.", "amber");
    return 1500;
  }
  if (step.tool === "submit_recommendation" && r.status === "rejected_by_policy_gate") {
    pipeFlow("reject", `Blocked by the gate: ${firstViolation(r) || "policy violation"}`, "red");
    return 1700;
  }
  if (step.tool === "get_case" || step.tool === "list_cases") { pipeFlow("read", "Agent reads the case file."); return 0; }
  if (step.tool === "plan_disruption_response") { pipeFlow("read", "Caldova's planning code computes the plan."); return 0; }
  if (String(step.tool).startsWith(TOOLBOX_PREFIX)) { pipeFlow("read", "Agent reads Caldova's evidence through the toolbox."); return 0; }
  return 0;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `Request failed (${res.status})`);
  return json;
}

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 3200);
}

// ---------------------------------------------------------------- header + beats

function renderHeader() {
  const d = app.data;
  $("#pill-agent").textContent = `${d.agent} · hosted agent`;
  $("#pill-store").textContent = d.storage;
  $("#case-id").textContent = d.default_case;
  $("#session-chip").textContent = `conversation ${app.session}`;
}

function beatList() {
  return [
    { id: "sweep", n: 1, title: "Plan and file the case", sub: "Agent plans, gate checks, case is filed", run: runSweep },
    { id: "new", n: 2, title: "Open a new conversation", sub: "Fresh session, empty chat", run: newConversation },
    { id: "status", n: 3, title: "Ask what was filed", sub: "The case is in the store, not the chat", run: () => send(PROMPTS.status(), "status") },
    { id: "push", n: 4, title: "Push Cedar 700", sub: "Over the 600 cap: code says no", run: () => send(PROMPTS.push(), "push") },
  ];
}

function renderBeats() {
  const beats = beatList();
  const next = beats.find((b) => !app.beatsDone.has(b.id));
  const justDone = app.justDone;
  app.justDone = "";
  keepFocus(() => { $("#beats").innerHTML = beats.map((b) => `
    <button class="beat ${app.beatsDone.has(b.id) ? "done" : ""} ${next === b ? "next" : ""} ${app.running === b.id ? "running" : ""} ${justDone === b.id ? "pop" : ""}" data-beat="${b.id}" title="Press ${b.n}" ${app.busy ? 'aria-disabled="true"' : ""}>
      <span class="n">${app.beatsDone.has(b.id) ? "✓" : b.n}</span><span><b>${esc(b.title)}</b><small>${esc(b.sub)}</small></span><kbd aria-hidden="true">${b.n}</kbd>
    </button>`).join(""); });
  $("#beats").querySelectorAll(".beat").forEach((el) => el.addEventListener("click", () => beats.find((b) => b.id === el.dataset.beat).run()));
}

function completeBeat(id) {
  app.beatsDone.add(id);
  app.justDone = id;
}

// ---------------------------------------------------------------- chat

function addMessage(html, cls) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  const chat = $("#chat");
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

const TOOLBOX_PREFIX = "caldova_ops___";

function stepHtml(step) {
  const toolbox = String(step.tool).startsWith(TOOLBOX_PREFIX);
  const name = toolbox ? String(step.tool).slice(TOOLBOX_PREFIX.length) : step.tool;
  const kind = WRITE_TOOLS.has(step.tool) ? `<span class="kind write">write · gated</span>` : `<span class="kind">${toolbox ? "toolbox · read" : "read"}</span>`;
  const ms = step.ms == null ? "" : `<span class="ms">${step.ms} ms</span>`;
  const body = JSON.stringify({ arguments: step.args, result: step.result }, null, 2);
  return `<details class="step ${WRITE_TOOLS.has(step.tool) ? "write" : ""}"><summary><span class="tick" aria-hidden="true">✓</span><span class="tool">${esc(name)}</span>${kind}${ms}</summary><pre>${esc(body)}</pre></details>`;
}

// Small markdown subset (headings, bold, bullets, tables) for live replies. Escapes first, so model text can't inject HTML.
function inline(text) {
  return linkSources(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

function markdown(text) {
  const lines = String(text).split("\n");
  let out = "", i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    const h = line.match(/^#{1,4}\s+(.*)/);
    if (h) { out += `<h4>${inline(h[1])}</h4>`; i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(r));
      out += `<table class="md">${body.map((r, k) => `<tr>${cells(r).map((c) => `<${k ? "td" : "th"}>${inline(c)}</${k ? "td" : "th"}>`).join("")}</tr>`).join("")}</table>`;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      out += `<ul>${items.map((t) => `<li>${inline(t)}</li>`).join("")}</ul>`;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*[-*]\s)/.test(lines[i])) para.push(lines[i++]);
    out += `<p>${inline(para.join("\n"))}</p>`;
  }
  return out;
}

function replyHtml(reply) {
  if (reply.text !== undefined) {
    const secs = reply.total_ms ? `<div class="foot">Hosted agent responded in ${(reply.total_ms / 1000).toFixed(1)} s</div>` : "";
    return `<div class="md-body">${markdown(reply.text || "(no text returned)")}</div>${secs}`;
  }
  if (reply.sections) {
    const body = reply.sections.map((s) => `<h4>${esc(s.title)}</h4><p>${linkSources(s.body)}</p>`).join("");
    return body + (reply.footer ? `<div class="foot">${esc(reply.footer)}</div>` : "");
  }
  return "";
}

function linkSources(text) {
  return esc(text).replace(/\[([A-Z]+(?:-[A-Z0-9]+)+(?:,\s*[A-Z]+(?:-[A-Z0-9]+)+)*)\]/g,
    (_, ids) => ids.split(/,\s*/).map((id) => `<span class="src">${id}</span>`).join(""));
}

async function showAgentTurn(result) {
  const bubble = addMessage(`<div class="steps"></div><div class="working"><span class="dots"><i></i><i></i><i></i></span>Calling tools…</div>`, "agent");
  const steps = bubble.querySelector(".steps");
  for (const step of result.steps) {
    steps.insertAdjacentHTML("beforeend", stepHtml(step));
    $("#chat").scrollTop = $("#chat").scrollHeight;
    const hold = flowForStep(step);
    await sleep(reduced() ? 0 : 420 + hold);
  }
  bubble.querySelector(".working").remove();
  bubble.insertAdjacentHTML("beforeend", replyHtml(result.reply));
  bubble.querySelectorAll(".md-body > *").forEach((el, i) => el.style.setProperty("--i", i));
  $("#chat").scrollTop = $("#chat").scrollHeight;
}

function setBusy(busy) {
  app.busy = busy;
  // aria-disabled, not disabled: a disabled control drops keyboard focus mid-turn.
  for (const b of [$("#send"), ...$("#suggest").querySelectorAll("button")]) b.setAttribute("aria-disabled", String(busy));
  renderBeats();
}

async function turn(label, call, beat) {
  if (app.busy) return;
  app.running = beat || "";
  setBusy(true);
  thinking(true);
  if (label) addMessage(esc(label), "user");
  const wait = addMessage(`<div class="working"><span class="dots"><i></i><i></i><i></i></span>Agent is working… <span class="secs">0 s</span><span class="bar"></span></div>`, "agent");
  const t0 = Date.now();
  const timer = setInterval(() => { wait.querySelector(".secs").textContent = `${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
  try {
    const result = await call();
    wait.remove();
    thinking(false);
    await showAgentTurn(result);
    if (beat) completeBeat(beat);
    await refresh();
    maybeFinale();
  } catch (err) {
    wait.remove();
    thinking(false);
    caption("The agent call failed. Try again, or switch to the backup video.", "red");
    const failure = addMessage(esc(err.message), "error");
    failure.setAttribute("role", "alert");
  } finally {
    clearInterval(timer);
    app.running = "";
    thinking(false);
    setBusy(false);
  }
}

const send = (text, beat) => turn(text, () => api("/api/chat", { message: text, session: String(app.session) }), beat);

const runSweep = () => send(PROMPTS.sweep(), "sweep");

async function newConversation() {
  if (app.busy) return;
  await api("/api/new-conversation", { session: String(app.session) });
  app.session += 1;
  const chat = $("#chat");
  chat.classList.add("sweep-out");
  chat.innerHTML = "";
  completeBeat("new");
  renderHeader();
  renderBeats();
  // The point of this beat is that the case is still there: light up the case file and its node.
  const panel = $("#col-case");
  panel.classList.remove("glow");
  void panel.offsetWidth;
  panel.classList.add("glow");
  pipeFlow("read", "New conversation. The case file didn't go anywhere.", "");
  maybeFinale();
}

// ---------------------------------------------------------------- case file

const srcs = (list) => (list || []).map((s) => `<span class="src">${esc(s)}</span>`).join("");
const time = (iso) => { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };

function renderCase() {
  const d = app.data;
  const box = $("#case");
  const c = d.cases.find((x) => x.case_id === d.default_case);
  if (!c) {
    box.innerHTML = `<div class="empty"><b>Waiting for the agent.</b><br>This panel shows what the hosted agent's own tools return from the Foundry state store. Run beat 1 and the agent files <span class="src">${esc(d.default_case)}</span>; it appears here.</div>`;
    return;
  }
  const hist = c.history || [];
  const last = hist[hist.length - 1];
  const standing = [...hist].reverse().find((h) => h.status === "pending_human_approval");
  const lastRejected = last && last.status === "rejected_by_policy_gate";
  const fresh = app.lastOp !== last.operation_id;
  app.lastOp = last.operation_id;

  const weeks = d.plan.weeks;
  const open = standing ? standing.open_gap_by_week : {};
  const bars = standing ? weeks.map((w, i) => {
    const o = Math.min(Number(open[w.week] || 0), w.gap);
    const cov = w.gap - o;
    return `<span class="lbl">wk ${w.week}</span>
      <div class="track" title="gap ${w.gap}"><div class="cov" style="--i:${i};width:${(cov / w.gap) * 100}%"></div><div class="open" style="--i:${i};width:${(o / w.gap) * 100}%"></div></div>
      <span class="val"><span data-count="${cov}">${fmt(cov)}</span> / ${fmt(w.gap)}</span>`;
  }).join("") : "";
  const totalGap = weeks.reduce((a, w) => a + w.gap, 0);
  const totalOpen = Object.values(open).reduce((a, v) => a + Number(v), 0);
  const v0 = lastRejected ? last.violations[0] : null;
  const updated = c.updated_at ? ` · updated ${esc(time(c.updated_at))}` : "";

  box.innerHTML = `<div class="case-inner ${fresh ? "fresh" : ""}">
    ${lastRejected ? `<div class="blocked">
      <div class="blocked-head"><b>BLOCKED BY CODE</b><span class="stamp rejected big ${fresh ? "slam" : ""}">REJECTED</span></div>
      <p class="blocked-why">${esc(v0 ? v0.violation : "Policy violation")}</p>
      <div>${srcs(v0 ? v0.sources : [])}${last.violations.length > 1 ? ` <span class="who">+${last.violations.length - 1} more in the history</span>` : ""}</div>
      <p class="blocked-note">${standing ? `Standing recommendation unchanged: submission #${hist.indexOf(standing) + 1} is still waiting on its approvers.` : "Nothing is waiting on approvers."}</p>
    </div>` : ""}
    <div class="status ${standing ? "pending" : "rejected"}">
      <div><b>${standing ? "PENDING HUMAN APPROVAL" : "NO ACCEPTED RECOMMENDATION"}</b>
        <small>${standing ? `Standing recommendation: submission #${hist.indexOf(standing) + 1}` : "Every submission was rejected by the gate"} · ${hist.length} submission${hist.length === 1 ? "" : "s"}${updated}</small></div>
      <span class="stamp ${standing ? "pending" : "rejected"}">${standing ? "NOT APPROVED" : "REJECTED"}</span>
    </div>
    ${standing ? `
    <div class="card"><h3>Standing recommendation <span>covered / weekly gap, units</span></h3>
      <div class="bars">${bars}</div>
      <div class="legend"><span><i style="background:var(--indigo)"></i>covered</span><span><i style="background:#f08b7c"></i>open gap <span data-count="${totalOpen}">${fmt(totalOpen)}</span> of ${fmt(totalGap)}</span></div>
    </div>
    <div class="card approvals"><h3>Waiting on</h3>${(standing.required_approvals || []).map((a) =>
      `<div><b>${esc(a.decision)}</b><br>${a.approvers.map((p) => `<span class="who">${esc(p)}</span>`).join("")} ${srcs(a.sources)}</div>`).join("")}
      <div class="foot" style="font-size:14px;color:var(--muted)">The gate never approves. These people do.</div>
    </div>` : `<div class="card"><h3>Standing recommendation</h3>None accepted yet.</div>`}
    <div class="card"><h3>Submission history <span>append-only</span></h3>
      <ul class="hist">${[...hist].reverse().map((h, i) => {
        const n = hist.length - i;
        const bad = h.status === "rejected_by_policy_gate";
        return `<li class="${bad ? "rejected" : ""}"><b class="${bad ? "bad" : "ok"}">#${n} ${esc(STATUS[h.status] || h.status)}</b>
          <div class="t">${esc(time(h.submitted_at))} · op ${esc(h.operation_id)}</div>
          ${bad ? `<ul>${h.violations.map((v) => `<li>${esc(v.violation)} ${srcs(v.sources)}</li>`).join("")}</ul>` : ""}</li>`;
      }).join("")}</ul>
    </div></div>`;
  if (fresh) {
    box.querySelectorAll("[data-count]").forEach((el) => countUp(el, Number(el.dataset.count)));
    box.scrollTop = 0;
    if (lastRejected) {
      const panel = $("#col-case");
      panel.classList.remove("quake");
      void panel.offsetWidth;
      panel.classList.add("quake");
    }
  }
}

// ---------------------------------------------------------------- gate console

const PRESETS = [
  { label: "Compliant plan", fn: () => resetRows() },
  { label: "Cedar 700 in week 1", bad: true, fn: () => { resetRows(); setRoutes(0, { Cedar: 700, Birch: 400 }); } },
  { label: "Use Northbank in week 3", bad: true, fn: () => { resetRows(); app.rows[2].supplier = "Northbank"; setRoutes(2, { Cedar: 600, Birch: 800 }); } },
  { label: "Route via Elm", bad: true, fn: () => { resetRows(); setRoutes(1, { Cedar: 600, Birch: 400, Elm: 200 }); } },
  { label: "Over-commit week 1", bad: true, fn: () => { resetRows(); setRoutes(0, { Cedar: 600, Birch: 700 }); } },
  { label: "Drop DIST-POLICY citation", bad: true, fn: () => { resetRows(); app.cites.delete("DIST-POLICY"); } },
];

function resetRows() {
  const t = app.data.plan.template;
  app.rows = t.weeks.map((w) => ({ week: w.week, supplier: w.supplier, units: w.units, routes: { Cedar: w.routes.Cedar || 0, Birch: w.routes.Birch || 0, Elm: w.routes.Elm || 0 } }));
  app.cites = new Set(t.cited_sources);
  app.verdict = null;
}

function setRoutes(i, routes) {
  const row = app.rows[i];
  row.routes = { Cedar: routes.Cedar || 0, Birch: routes.Birch || 0, Elm: routes.Elm || 0 };
  row.units = ROUTES.reduce((a, r) => a + row.routes[r], 0);
}

// Which cells caused the gate's violations, so the failing number itself lights up.
function hotCells() {
  const hot = new Set(), miss = new Set();
  for (const v of app.verdict?.result?.violations || []) {
    if (v.week == null) { (v.sources || []).forEach((s) => miss.add(s)); continue; }
    const i = app.rows.findIndex((r) => r.week === v.week);
    if (i < 0) continue;
    const t = v.violation;
    ROUTES.filter((r) => t.includes(r)).forEach((r) => hot.add(`${i}:route:${r}`));
    if (/Aster Ridge|Northbank|exceeds available/.test(t)) hot.add(`${i}:supplier`);
    if (/commits|routed|exceeds available|gap is/.test(t)) hot.add(`${i}:units`);
  }
  return { hot, miss };
}

function renderGate(keepVerdict = true) {
  const d = app.data;
  if (!app.rows.length) resetRows();
  const maxFor = Object.fromEntries(d.scenario.routes.map((r) => [r.name, r.max_units_per_week]));
  const suppliers = d.scenario.suppliers.map((s) => s.name);
  const cites = [...new Set([...d.scenario.required_citations, "RISK-001", "RISK-POLICY"])];
  const { hot, miss } = keepVerdict ? hotCells() : { hot: new Set(), miss: new Set() };
  const cls = (key) => (hot.has(key) ? ' class="hot"' : "");

  keepFocus(() => { $("#gate").innerHTML = `
    <p class="lead">Pick a plan. <b>Caldova's own code</b> (<code>validate_proposal</code>) checks it, whatever any model says. Dry run: nothing is written to the case file.</p>
    <div class="presets">${PRESETS.map((p, i) => `<button type="button" class="${p.bad ? "bad" : ""}" data-preset="${i}">${esc(p.label)}</button>`).join("")}</div>
    <button class="primary submit" id="submit-gate" type="button">Check this plan with the gate</button>
    <div id="verdict" role="status">${keepVerdict ? verdictHtml() : ""}</div>
    <div class="tablewrap"><table class="alloc" aria-label="Weekly allocation"><colgroup><col style="width:8%"><col style="width:29%"><col style="width:15%"><col style="width:16%"><col style="width:16%"><col style="width:16%"></colgroup>
    <thead><tr><th scope="col">Wk</th><th scope="col">Supplier</th><th scope="col">Units</th><th scope="col">Cedar<br><small>cap ${maxFor.Cedar ?? "?"}</small></th><th scope="col">Birch<br><small>cap ${maxFor.Birch ?? "?"}</small></th><th scope="col">Elm<br><small>no data</small></th></tr></thead>
    <tbody>${app.rows.map((r, i) => `<tr><th scope="row" class="wk">${r.week}</th>
      <td><select${cls(`${i}:supplier`)} aria-label="Week ${r.week} supplier" data-i="${i}" data-f="supplier">${suppliers.map((s) => `<option ${s === r.supplier ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></td>
      <td><input${cls(`${i}:units`)} type="number" inputmode="numeric" aria-label="Week ${r.week} total units" min="0" step="50" value="${r.units}" data-i="${i}" data-f="units"></td>
      ${ROUTES.map((rt) => `<td><input${cls(`${i}:route:${rt}`)} type="number" inputmode="numeric" aria-label="Week ${r.week} ${rt} units" min="0" step="50" value="${r.routes[rt]}" data-i="${i}" data-f="route" data-r="${rt}"></td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="cites">${cites.map((c) => `<label class="${app.cites.has(c) ? "on" : ""} ${miss.has(c) ? "miss" : ""}"><input type="checkbox" data-cite="${c}" ${app.cites.has(c) ? "checked" : ""}>${c}</label>`).join("")}</div>`; });

  if (app.flash) {
    if (keepVerdict) app.flash = false; // the render that shows the verdict is the last one for this preset
    const base = d.plan.template.weeks;
    app.rows.forEach((r, i) => {
      const t = base[i];
      if (r.supplier !== t.supplier) $(`[data-i="${i}"][data-f="supplier"]`).classList.add("flash");
      if (r.units !== t.units) $(`[data-i="${i}"][data-f="units"]`).classList.add("flash");
      for (const rt of ROUTES) if (r.routes[rt] !== (t.routes[rt] || 0)) $(`[data-i="${i}"][data-f="route"][data-r="${rt}"]`).classList.add("flash");
    });
    $("#gate").querySelectorAll(".cites label").forEach((l) => { if (!app.cites.has(l.textContent.trim())) l.classList.add("flash"); });
  }

  // A preset applies the plan and checks it in one click, so the rejection lands immediately.
  $("#gate").querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    PRESETS[b.dataset.preset].fn();
    app.flash = true;
    renderGate(false);
    submitGate();
  }));
  $("#gate").querySelectorAll(".alloc td input, .alloc td select").forEach((el) => el.addEventListener("focus", () => el.select && el.select()));
  $("#gate").querySelectorAll("input[data-f],select[data-f]").forEach((el) => el.addEventListener("change", () => {
    const row = app.rows[el.dataset.i];
    if (el.dataset.f === "supplier") row.supplier = el.value;
    else if (el.dataset.f === "units") row.units = Math.max(0, parseInt(el.value, 10) || 0);
    else { row.routes[el.dataset.r] = Math.max(0, parseInt(el.value, 10) || 0); row.units = ROUTES.reduce((a, r) => a + row.routes[r], 0); }
    // Update in place: re-rendering here would drop keyboard focus mid-table.
    if (el.dataset.f === "route") $(`[data-i="${el.dataset.i}"][data-f="units"]`).value = row.units;
    app.verdict = null;
    $("#verdict").innerHTML = "";
    $("#gate").querySelectorAll(".hot,.miss").forEach((x) => x.classList.remove("hot", "miss"));
  }));
  $("#gate").querySelectorAll("[data-cite]").forEach((el) => el.addEventListener("change", () => {
    el.checked ? app.cites.add(el.dataset.cite) : app.cites.delete(el.dataset.cite);
    el.parentElement.classList.toggle("on", el.checked);
  }));
  $("#submit-gate").addEventListener("click", submitGate);
  $("#submit-gate").setAttribute("aria-disabled", String(app.busy));
}

function verdictHtml() {
  const v = app.verdict;
  if (!v) return "";
  const r = v.result;
  const dry = r.dry_run ? " (dry run, not recorded)" : "";
  if (r.error && r.recorded === false) return `<div class="verdict rejected"><h3>Not recorded</h3><p>${esc(r.error)}</p></div>`;
  if (r.status === "pending_human_approval") {
    return `<div class="verdict pending"><h3>Accepted by the gate: pending human approval${dry}${r.duplicate ? " (duplicate, nothing new written)" : ""}</h3>
      <ul>${(r.required_approvals || []).map((a) => `<li>${esc(a.decision)}: ${a.approvers.map((p) => `<span class="who">${esc(p)}</span>`).join("")} ${srcs(a.sources)}</li>`).join("")}</ul>
      <div class="note">${esc(r.note || "")}</div></div>`;
  }
  return `<div class="verdict rejected"><h3>Rejected by the policy gate${dry}: ${r.violations.length} violation${r.violations.length === 1 ? "" : "s"}</h3>
    <ul>${r.violations.map((x) => `<li>${x.week != null ? `<b>Week ${x.week}.</b> ` : ""}${esc(x.violation)} ${srcs(x.sources)}</li>`).join("")}</ul>
    <div class="note">${r.dry_run ? "Nothing was written." : "Recorded in the case history."} Rejection isn't an error, it's the system working.</div></div>`;
}

async function submitGate() {
  const btn = $("#submit-gate");
  if (app.busy || btn.getAttribute("aria-disabled") === "true") return;
  btn.setAttribute("aria-disabled", "true");
  try {
    const weeks = app.rows.map((r) => ({
      week: r.week, supplier: r.supplier, units: r.units,
      routes: Object.fromEntries(ROUTES.filter((rt) => r.routes[rt] > 0).map((rt) => [rt, r.routes[rt]])),
    }));
    const res = await api("/api/propose", { case_id: app.data.default_case, weeks, cited_sources: [...app.cites], rationale: "Submitted from the policy gate console." });
    app.verdict = res;
    renderGate(true);
    $("#gate").scrollTop = 0;
    const r = res.result;
    if (r.status === "pending_human_approval") pipeFlow("check", "Gate check (dry run): this plan passes. Nothing was recorded.", "amber");
    else pipeFlow("reject", `Gate check (dry run), blocked: ${firstViolation(r) || "policy violation"}`, "red");
    await refresh();
  } catch (err) {
    toast(err.message);
  } finally {
    $("#submit-gate").setAttribute("aria-disabled", "false");
  }
}

// ---------------------------------------------------------------- boot

function renderSuggest() {
  const chips = [["Plan and file it", PROMPTS.sweep], ["What was filed?", PROMPTS.status], ["Push Cedar 700", PROMPTS.push], ["Can we use Northbank?", PROMPTS.northbank]];
  $("#suggest").innerHTML = chips.map(([l], i) => `<button type="button" data-i="${i}">${esc(l)}</button>`).join("");
  $("#suggest").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => send(chips[b.dataset.i][1]())));
}

let confirmTimer;
async function newCase() {
  if (app.busy) return;
  const btn = $("#new-case");
  if (app.beatsDone.size && !btn.classList.contains("confirm")) {
    btn.classList.add("confirm");
    btn.textContent = "Start over? Click again";
    confirmTimer = setTimeout(resetNewCaseButton, 3000);
    return;
  }
  resetNewCaseButton();
  await api("/api/new-case", {});
  app.session = 1; app.beatsDone.clear(); app.verdict = null; app.lastOp = ""; app.finaleShown = false;
  $("#chat").innerHTML = "";
  addMessage("New demo case. Start again with beat 1.", "divider");
  caption("Model proposes. Code decides. The case file records.");
  resetRows();
  renderGate(false);
  await refresh();
}

function resetNewCaseButton() {
  clearTimeout(confirmTimer);
  const btn = $("#new-case");
  btn.classList.remove("confirm");
  btn.textContent = "New demo case";
}

// ---------------------------------------------------------------- finale

function maybeFinale() {
  if (app.finaleShown || !beatList().every((b) => app.beatsDone.has(b.id))) return;
  app.finaleShown = true;
  setTimeout(showFinale, reduced() ? 0 : 1600);
}

function showFinale() {
  const c = app.data.cases.find((x) => x.case_id === app.data.default_case);
  const hist = c ? c.history || [] : [];
  const stats = [
    ["Submissions", hist.length, ""],
    ["Accepted by the gate", hist.filter((h) => h.status === "pending_human_approval").length, "good"],
    ["Rejected in code", hist.filter((h) => h.status === "rejected_by_policy_gate").length, "bad"],
    ["Approved by the agent", 0, "zero"],
  ];
  $("#finale-stats").innerHTML = stats.map(([label, n, tone], i) => `<div class="stat ${tone}" style="--i:${i}"><b data-count="${n}">${n}</b><span>${label}</span></div>`).join("");
  const el = $("#finale");
  el.hidden = false;
  el.querySelectorAll("[data-count]").forEach((b) => countUp(b, Number(b.dataset.count), 1000));
  $("#finale-close").focus();
}

function closeFinale() {
  $("#finale").hidden = true;
}

async function refresh() {
  app.data = await api("/api/state");
  renderHeader();
  renderBeats();
  renderCase();
  const c = app.data.cases.find((x) => x.case_id === app.data.default_case);
  if (c && c.history.length && !app.beatsDone.has("sweep") && !app.busy && !app.running) { app.beatsDone.add("sweep"); renderBeats(); }
}

async function boot() {
  try {
    app.data = await api("/api/state");
  } catch (err) {
    document.body.innerHTML = `<p style="padding:2rem">Couldn't reach the demo server: ${esc(err.message)}</p>`;
    return;
  }
  resetRows();
  renderSuggest();
  $("#new-case").addEventListener("click", newCase);
  $("#finale-close").addEventListener("click", closeFinale);
  $("#finale-again").addEventListener("click", async () => { closeFinale(); $("#new-case").classList.add("confirm"); await newCase(); });
  $("#finale").addEventListener("click", (e) => { if (e.target.id === "finale") closeFinale(); });
  // Presenter shortcuts: 1 to 4 run the beats, Escape closes the finale.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#finale").hidden) return closeFinale();
    if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const beat = beatList()[Number(e.key) - 1];
    if (beat) { e.preventDefault(); beat.run(); }
  });
  window.addEventListener("resize", layoutPipe);
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#msg").value.trim();
    if (text && !app.busy) { $("#msg").value = ""; send(text); }
  });
  addMessage("Connected to the hosted agent <b>caldova-ops-runtime</b> through its stable endpoint. Ask it anything, or follow the beats above. Replies take 10 to 15 seconds.", "divider");
  renderGate(true);
  await refresh();
  layoutPipe();
}

boot();
