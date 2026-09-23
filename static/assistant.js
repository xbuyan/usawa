/**
 * DEI Assistant (grounded chat) + peer benchmarks (learning layer).
 *
 * Loaded by templates/index.html alongside app.js. Deliberately vanilla JS,
 * same conventions as app.js: fetch + CSRF header from the meta tag, safeJson
 * for error resilience, no build step. All rendering uses textContent /
 * element creation — user-provided strings are never interpolated into
 * innerHTML (chat content is user input, so this is an XSS boundary).
 */

const $a = (id) => document.getElementById(id);

let currentConversationId = null;
let sharePreference = false;
let lastBenchmarksFetched = null; // scorecard JSON string cache, avoids refetching identical state

function chatError(message) {
  const box = $a("chatError");
  if (!box) return;
  box.textContent = message || "";
  box.style.display = message ? "block" : "none";
}

function csrf() {
  return getCsrfToken(); // defined in app.js
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function addChatBubble(role, text, sources) {
  const win = $a("chatWindow");
  if (!win) return;

  const msg = document.createElement("div");
  msg.className = `chat-msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  // Paragraphs from newlines; textContent only — no HTML from server text.
  (text || "").split(/\n\n+/).forEach((para) => {
    const p = document.createElement("p");
    p.textContent = para.trim();
    bubble.appendChild(p);
  });

  if (sources && sources.length) {
    const src = document.createElement("div");
    src.className = "chat-sources";
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "SOURCES";
    src.appendChild(tag);
    sources.forEach((s) => {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = s.title || s.doc_id || "";
      src.appendChild(chip);
    });
    bubble.appendChild(src);
  }

  msg.appendChild(bubble);
  win.appendChild(msg);
  win.scrollTop = win.scrollHeight;
}

function renderConversationList(conversations) {
  const container = $a("conversationsItems");
  if (!container) return;
  container.innerHTML = "";
  conversations.forEach((c) => {
    const btn = document.createElement("button");
    btn.className = "convo-item" + (c.id === currentConversationId ? " active" : "");
    btn.textContent = c.title || "Conversation";
    btn.title = c.title || "";
    btn.addEventListener("click", () => loadConversation(c.id));
    container.appendChild(btn);
  });
}

async function refreshConversations() {
  try {
    const resp = await fetch("/api/conversations");
    if (!resp.ok) return;
    renderConversationList(await resp.json());
  } catch (err) { /* list is non-critical; window still works */ }
}

async function loadConversation(id) {
  try {
    const resp = await fetch(`/api/conversations/${id}`);
    const data = await resp.json();
    if (!resp.ok) { chatError(data.error || "Couldn't load that conversation."); return; }
    currentConversationId = id;
    const win = $a("chatWindow");
    win.innerHTML = "";
    (data.messages || []).forEach((m) => addChatBubble(m.role, m.content, m.sources));
    chatError(null);
    refreshConversations(); // re-render for active highlight
  } catch (err) {
    chatError("Couldn't load that conversation.");
  }
}

function newConversation() {
  currentConversationId = null;
  const win = $a("chatWindow");
  win.innerHTML = "";
  addChatBubble("assistant",
    "New conversation. Ask about inclusive hiring, pay equity, promotion practice, or anything else in the guidance library.");
  chatError(null);
  refreshConversations();
}

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

async function sendChat() {
  const input = $a("chatInput");
  const btn = $a("chatSendBtn");
  const question = (input.value || "").trim();
  if (!question) return;

  const payload = { question };
  if (currentConversationId) payload.conversation_id = currentConversationId;
  // Give the assistant the user's current results when we have them, so
  // questions like "why is my hiring score low" get specific answers.
  if (typeof currentScorecard !== "undefined" && currentScorecard) {
    payload.scorecard = currentScorecard;
  }

  input.value = "";
  btn.disabled = true;
  addChatBubble("user", question);
  chatError(null);

  const thinking = document.createElement("div");
  thinking.className = "chat-msg assistant";
  thinking.innerHTML = '<div class="chat-bubble chat-example">Thinking…</div>';
  $a("chatWindow").appendChild(thinking);
  const win = $a("chatWindow");
  win.scrollTop = win.scrollHeight;

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(payload),
    });
    thinking.remove();
    const data = await safeJson(resp); // defined in app.js
    if (!resp.ok) {
      chatError(data.error || "The assistant couldn't answer right now. Try again shortly.");
      return;
    }
    currentConversationId = data.conversation_id;
    addChatBubble("assistant", data.answer, data.sources);
  } catch (err) {
    thinking.remove();
    chatError(err.message || "Couldn't reach the assistant.");
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

// ---------------------------------------------------------------------------
// Sharing preference
// ---------------------------------------------------------------------------

async function loadSharePreference() {
  try {
    const resp = await fetch("/api/auth/me");
    const data = await resp.json();
    sharePreference = !!data.share_anonymized_data;
    const toggle = $a("shareToggle");
    if (toggle) toggle.checked = sharePreference;
  } catch (err) { /* default to unchecked */ }
}

async function onShareToggle(e) {
  const wanted = e.target.checked;
  try {
    const resp = await fetch("/api/sharing", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ share_anonymized_data: wanted }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      e.target.checked = sharePreference; // revert on failure
      chatError(data.error || "Couldn't update the sharing preference.");
      return;
    }
    sharePreference = !!data.share_anonymized_data;
  } catch (err) {
    e.target.checked = sharePreference;
    chatError("Couldn't update the sharing preference.");
  }
}

// ---------------------------------------------------------------------------
// Benchmarks ("How you compare" panel on the results tab)
// ---------------------------------------------------------------------------

const BENCH_LABELS = {
  overall: "Overall", pay_equity: "Pay equity", promotion_equity: "Promotion equity",
  hiring_funnel: "Hiring funnel", representation_pipeline: "Representation",
  job_language: "Job language",
};

function renderBenchmarks(payload) {
  const panel = $a("benchmarksPanel");
  const content = $a("benchmarksContent");
  const patterns = $a("patternsContent");
  if (!panel || !content) return;

  panel.style.display = "block";
  content.innerHTML = "";
  patterns.innerHTML = "";

  if (!payload || !payload.available) {
    const note = document.createElement("p");
    note.className = "benchmark-unavailable";
    note.textContent = payload && payload.reason ? payload.reason :
      `Peer benchmarks unlock once at least ${payload.min_cohort} companies in a matching cohort have opted in.`;
    content.appendChild(note);
    return;
  }

  payload.comparisons.forEach((c) => {
    const row = document.createElement("div");
    row.className = "benchmark-row";
    const name = document.createElement("span");
    name.textContent = BENCH_LABELS[c.metric] || c.metric;

    if (!c.available) {
      const why = document.createElement("span");
      why.className = "benchmark-unavailable";
      why.textContent = c.reason || "Not enough peer data yet.";
      row.appendChild(name);
      row.appendChild(why);
      content.appendChild(row);
      return;
    }

    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max(0, Math.min(100, c.your_percentile ?? 0))}%`;
    fill.style.background = "var(--indigo)";
    track.appendChild(fill);

    const val = document.createElement("span");
    val.className = "val";
    val.textContent = `${c.your_percentile ?? "–"}th pct`;

    row.appendChild(name);
    row.appendChild(track);
    row.appendChild(val);
    content.appendChild(row);
  });

  const note = $a("benchmarksCohortNote");
  const first = (payload.comparisons || []).find((c) => c.available);
  if (note && first) note.textContent = `vs ${first.cohort.label} · n=${first.cohort.n_companies}`;

  (payload.patterns || []).forEach((p) => {
    const item = document.createElement("div");
    item.className = "pattern-item";
    const text = document.createElement("span");
    text.textContent = p.statement;
    const n = document.createElement("span");
    n.className = "pattern-n";
    n.textContent = `Correlation ${p.correlation} · based on ${p.n_companies} anonymized companies`;
    item.appendChild(text);
    item.appendChild(n);
    patterns.appendChild(item);
  });
}

async function fetchBenchmarks() {
  if (typeof currentScorecard === "undefined" || !currentScorecard) return;
  const serialized = JSON.stringify(currentScorecard);
  if (serialized === lastBenchmarksFetched) return; // same scorecard, cached panel is fine
  lastBenchmarksFetched = serialized;

  const formSnapshot = typeof readForm === "function" ? readForm() : {};
  const params = new URLSearchParams({ scorecard: serialized });
  if (formSnapshot.companySize) params.set("company_size", formSnapshot.companySize);
  if (formSnapshot.industry) params.set("industry", formSnapshot.industry);

  try {
    const resp = await fetch(`/api/benchmarks?${params.toString()}`);
    const data = await resp.json();
    if (resp.ok) renderBenchmarks(data);
  } catch (err) { /* benchmarks are additive; scorecard still works */ }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const sendBtn = $a("chatSendBtn");
  const input = $a("chatInput");
  const newBtn = $a("newConversationBtn");
  const toggle = $a("shareToggle");
  if (!sendBtn) return; // not on the app page

  sendBtn.addEventListener("click", sendChat);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  newBtn.addEventListener("click", newConversation);
  toggle.addEventListener("change", onShareToggle);

  loadSharePreference();
  refreshConversations();

  // Fetch benchmarks whenever the results tab is opened (after a run or a
  // load of a saved report). switchTab is app.js's; we hook the click on
  // the results tab button rather than monkey-patching it.
  document.querySelectorAll('.tab-btn[data-tab="results"]').forEach((btn) => {
    btn.addEventListener("click", fetchBenchmarks);
  });
});
