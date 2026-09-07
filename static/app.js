const METRIC_LABELS = {
  pay_equity: "Pay equity",
  promotion_equity: "Promotion equity",
  hiring_funnel: "Hiring funnel",
  representation_pipeline: "Representation",
  job_language: "Job language",
};

const SAMPLE = {
  companyName: "Acme Software Inc.",
  companySize: 220, industry: "software",
  payIC: 3, payManager: 8, payDirector: 14,
  promoA: 8, eligA: 60, promoB: 15, eligB: 65,
  ttpA: 26, ttpB: 18,
  fAapplied: 500, fAinterviewed: 120, fAoffered: 20, fAhired: 15,
  fBapplied: 700, fBinterviewed: 200, fBoffered: 40, fBhired: 32,
  repIC: 48, repManager: 32, repDirector: 19, repExec: 8,
  postings: "We're looking for a rockstar ninja engineer who is aggressive and driven.\nJoin our collaborative and supportive team of dependable engineers.",
};

let currentScorecard = null;
let currentInsights = null;

const $ = (id) => document.getElementById(id);

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

function scoreColor(score) {
  if (score >= 75) return "var(--good)";
  if (score >= 50) return "var(--warn)";
  return "var(--bad)";
}

function fillForm(data) {
  Object.entries(data).forEach(([key, value]) => {
    const el = $(key);
    if (el) el.value = value;
  });
  updateAllGroupBHints();
}

const REP_FIELDS = ["repIC", "repManager", "repDirector", "repExec"];

function updateGroupBHint(fieldId) {
  const input = $(fieldId);
  const hint = $(`${fieldId}-hint`);
  if (!input || !hint) return;
  const groupA = parseFloat(input.value);
  if (isNaN(groupA)) {
    hint.textContent = "";
    return;
  }
  const groupB = Math.max(0, 100 - groupA);
  hint.textContent = `Group A: ${groupA}% · Group B: ${groupB.toFixed(1)}%`;
}

function updateAllGroupBHints() {
  REP_FIELDS.forEach(updateGroupBHint);
}

function loadSample() {
  fillForm(SAMPLE);
}

function readForm() {
  const v = (id) => $(id).value;
  return {
    companyName: v("companyName"),
    companySize: v("companySize"),
    industry: v("industry"),
    pay_gap_by_level: {
      IC: parseFloat(v("payIC")) || 0,
      Manager: parseFloat(v("payManager")) || 0,
      Director: parseFloat(v("payDirector")) || 0,
    },
    promotion: {
      promotions_a: parseInt(v("promoA")) || 0,
      eligible_a: parseInt(v("eligA")) || 0,
      promotions_b: parseInt(v("promoB")) || 0,
      eligible_b: parseInt(v("eligB")) || 0,
      time_to_promotion_months: {
        group_a: parseFloat(v("ttpA")) || 0,
        group_b: parseFloat(v("ttpB")) || 0,
      },
    },
    hiring_funnel: {
      funnel_a: {
        applied: parseInt(v("fAapplied")) || 0,
        interviewed: parseInt(v("fAinterviewed")) || 0,
        offered: parseInt(v("fAoffered")) || 0,
        hired: parseInt(v("fAhired")) || 0,
      },
      funnel_b: {
        applied: parseInt(v("fBapplied")) || 0,
        interviewed: parseInt(v("fBinterviewed")) || 0,
        offered: parseInt(v("fBoffered")) || 0,
        hired: parseInt(v("fBhired")) || 0,
      },
    },
    representation_by_level: {
      IC: parseFloat(v("repIC")) || 0,
      Manager: parseFloat(v("repManager")) || 0,
      Director: parseFloat(v("repDirector")) || 0,
      Exec: parseFloat(v("repExec")) || 0,
    },
    job_postings: v("postings").split("\n").filter(Boolean),
  };
}

function showError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.style.display = message ? "block" : "none";
}

function setLoading(isLoading) {
  $("runBtn").disabled = isLoading;
  $("runBtn").textContent = isLoading ? "Analyzing…" : "Run scorecard";
  $("statusLine").style.display = isLoading ? "flex" : "none";
}

async function safeJson(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    // Server sent back something that isn't JSON (an HTML error page, an
    // empty body, etc). Surface a readable message instead of a cryptic
    // "Unexpected token" parse error.
    throw new Error(
      `Server returned an unexpected response (status ${response.status}). ` +
      `This usually means the server crashed — check the terminal running app.py for the actual error.`
    );
  }
}

async function runAnalysis() {
  showError(null);
  currentInsights = null;
  $("insightsPanel").style.display = "none";
  setLoading(true);

  try {
    const formSnapshot = readForm();

    const scoreResp = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify(formSnapshot),
    });
    const scoreData = await safeJson(scoreResp);
    if (!scoreResp.ok) throw new Error(scoreData.error || "Scoring failed. Check your inputs and try again.");
    currentScorecard = scoreData;
    renderScorecard(currentScorecard);
    switchTab("results");

    const insightsResp = await fetch("/api/insights", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({
        scorecard: currentScorecard,
        company_size: parseInt(formSnapshot.companySize) || null,
        industry: formSnapshot.industry,
      }),
    });
    const insightsData = await safeJson(insightsResp);
    if (!insightsResp.ok) {
      showError(insightsData.error || "Scorecard generated, but AI recommendations failed. You can still save the scorecard above.");
    } else {
      currentInsights = insightsData;
      renderInsights(insightsData);
    }
  } catch (err) {
    showError(err.message || "Something went wrong.");
  } finally {
    setLoading(false);
  }
}


function renderScorecard(scorecard) {
  const panel = $("scorecardPanel");
  panel.style.display = "block";

  $("overallScore").textContent = scorecard.overall_score;
  $("overallScore").style.color = scoreColor(scorecard.overall_score);

  const barsContainer = $("scoreBars");
  barsContainer.innerHTML = "";
  Object.entries(scorecard.sub_scores).forEach(([key, score]) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span class="name">${METRIC_LABELS[key] || key}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${score}%;background:${scoreColor(score)}"></div></div>
      <span class="val" style="color:${scoreColor(score)}">${score}</span>
    `;
    barsContainer.appendChild(row);
  });

  $("emptyState").style.display = "none";
}

function renderInsights(insights) {
  const panel = $("insightsPanel");
  panel.style.display = "block";
  $("headlineSummary").textContent = insights.headline_summary || "";

  const findingsContainer = $("findings");
  findingsContainer.innerHTML = "";
  (insights.top_findings || []).forEach((f) => {
    const div = document.createElement("div");
    div.className = `finding ${f.priority || "medium"}`;
    div.innerHTML = `
      <div class="area">${f.area}<span class="priority-tag">${f.priority || ""}</span></div>
      <p>${f.why_it_matters || ""}</p>
      <p><em>${f.likely_cause || ""}</em></p>
      <p class="fix">→ ${f.recommended_fix || ""}</p>
    `;
    findingsContainer.appendChild(div);
  });

  const quickWinBox = $("quickWin");
  if (insights.quick_win) {
    quickWinBox.style.display = "block";
    quickWinBox.querySelector(".content").textContent = insights.quick_win;
  } else {
    quickWinBox.style.display = "none";
  }
}

// ---------------------------------------------------------------------------
// CSV uploads
// ---------------------------------------------------------------------------

async function uploadCsv(endpoint, file, onSuccess, summaryElId) {
  const formData = new FormData();
  formData.append("file", file);
  showError(null);

  try {
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: formData,
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Upload failed.");
      return;
    }
    onSuccess(data);

    const summaryEl = $(summaryElId);
    const processed = data.total_rows - data.skipped.length;
    summaryEl.style.display = "block";
    summaryEl.className = data.skipped.length ? "csv-warning" : "csv-success";
    summaryEl.textContent = data.skipped.length
      ? `Processed ${processed} of ${data.total_rows} rows. Skipped: ${data.skipped.slice(0, 5).join(", ")}${data.skipped.length > 5 ? "…" : ""}`
      : `Processed all ${data.total_rows} rows.`;
  } catch (err) {
    showError("Couldn't reach the server to parse that file.");
  }
}

function handleEmployeeUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  uploadCsv("/api/parse/employee", file, (data) => {
    if (data.pay_gap_by_level.IC != null) $("payIC").value = data.pay_gap_by_level.IC.toFixed(1);
    if (data.pay_gap_by_level.Manager != null) $("payManager").value = data.pay_gap_by_level.Manager.toFixed(1);
    if (data.pay_gap_by_level.Director != null) $("payDirector").value = data.pay_gap_by_level.Director.toFixed(1);
    if (data.representation_by_level.IC != null) $("repIC").value = data.representation_by_level.IC.toFixed(1);
    if (data.representation_by_level.Manager != null) $("repManager").value = data.representation_by_level.Manager.toFixed(1);
    if (data.representation_by_level.Director != null) $("repDirector").value = data.representation_by_level.Director.toFixed(1);
    if (data.representation_by_level.Exec != null) $("repExec").value = data.representation_by_level.Exec.toFixed(1);
    $("promoA").value = data.promotion.promotions_a;
    $("eligA").value = data.promotion.eligible_a;
    $("promoB").value = data.promotion.promotions_b;
    $("eligB").value = data.promotion.eligible_b;
    if (data.promotion.time_to_promotion_months.group_a != null) $("ttpA").value = data.promotion.time_to_promotion_months.group_a.toFixed(1);
    if (data.promotion.time_to_promotion_months.group_b != null) $("ttpB").value = data.promotion.time_to_promotion_months.group_b.toFixed(1);
    updateAllGroupBHints();
  }, "employeeSummary");
}

function handleApplicantUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  uploadCsv("/api/parse/applicant", file, (data) => {
    const a = data.hiring_funnel.funnel_a, b = data.hiring_funnel.funnel_b;
    $("fAapplied").value = a.applied; $("fAinterviewed").value = a.interviewed;
    $("fAoffered").value = a.offered; $("fAhired").value = a.hired;
    $("fBapplied").value = b.applied; $("fBinterviewed").value = b.interviewed;
    $("fBoffered").value = b.offered; $("fBhired").value = b.hired;
  }, "applicantSummary");
}

function downloadTemplate(filename, content) {
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const EMPLOYEE_TEMPLATE = `employee_id,level,group,salary,promotion_eligible,promoted,months_to_promotion
E001,IC,a,95000,yes,no,
E002,IC,b,98000,yes,yes,14
E003,Manager,a,125000,yes,no,
E004,Manager,b,136000,yes,yes,16
E005,Director,a,175000,no,no,
E006,Director,b,205000,yes,yes,19
E007,Exec,b,290000,no,no,
`;

const APPLICANT_TEMPLATE = `candidate_id,group,stage_reached
C001,a,applied
C002,a,interviewed
C003,a,offered
C004,a,hired
C005,b,applied
C006,b,interviewed
C007,b,offered
C008,b,hired
`;

// ---------------------------------------------------------------------------
// Saved clients
// ---------------------------------------------------------------------------

async function refreshSavedClients() {
  const container = $("savedClientsList");
  try {
    const resp = await fetch("/api/clients");
    const records = await resp.json();
    container.innerHTML = "";
    if (records.length === 0) {
      container.innerHTML = '<div class="empty-state" style="padding:10px 0">No saved reports yet. Run a scorecard below, then save it to build your client history.</div>';
      return;
    }
    records.forEach((r) => {
      const row = document.createElement("div");
      row.className = "saved-row";
      row.innerHTML = `
        <div class="saved-info">
          <span class="saved-name">${r.company_name}</span>
          <span class="saved-date">${new Date(r.saved_at).toLocaleDateString()} · Score: ${r.overall_score ?? "—"}</span>
        </div>
        <div class="saved-actions">
          <button class="btn-ghost" data-load="${r.id}" style="padding:5px 10px;font-size:12px">Load</button>
          <button class="btn-ghost danger" data-delete="${r.id}" style="padding:5px 10px;font-size:12px">Delete</button>
        </div>
      `;
      container.appendChild(row);
    });

    container.querySelectorAll("[data-load]").forEach((btn) => {
      btn.addEventListener("click", () => loadClient(btn.dataset.load));
    });
    container.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", () => deleteClient(btn.dataset.delete));
    });
  } catch (err) {
    container.innerHTML = '<div class="empty-state" style="padding:10px 0">Couldn\'t load saved reports.</div>';
  }
}

async function loadClient(id) {
  const resp = await fetch(`/api/clients/${id}`);
  const record = await resp.json();
  if (!resp.ok) { showError("Couldn't load that report."); return; }

  fillForm(record.form);
  currentScorecard = record.scorecard;
  currentInsights = record.insights;
  renderScorecard(record.scorecard);
  if (record.insights) renderInsights(record.insights);
  else $("insightsPanel").style.display = "none";

  switchTab("results");
}

async function deleteClient(id) {
  await fetch(`/api/clients/${id}`, {
    method: "DELETE",
    headers: { "X-CSRFToken": getCsrfToken() },
  });
  refreshSavedClients();
}

async function saveCurrentReport() {
  if (!currentScorecard) return;
  const formSnapshot = readForm();
  const saveStatus = $("saveStatus");

  try {
    const resp = await fetch("/api/clients", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({
        company_name: formSnapshot.companyName || "Untitled",
        form: formSnapshot,
        scorecard: currentScorecard,
        insights: currentInsights,
      }),
    });
    if (!resp.ok) throw new Error();
    saveStatus.style.display = "block";
    saveStatus.className = "csv-success";
    saveStatus.textContent = "Saved. Find it under Saved clients above.";
    refreshSavedClients();
  } catch (err) {
    saveStatus.style.display = "block";
    saveStatus.className = "error-box";
    saveStatus.textContent = "Couldn't save this report.";
  }
}

const TAB_META = {
  data: { title: "Data entry", subtitle: "Enter your hiring, pay, and promotion data to generate a scorecard and AI-backed recommendations." },
  results: { title: "Scorecard & insights", subtitle: "Your latest audit results." },
  saved: { title: "Saved clients", subtitle: "Reports you've saved for later, or to track a client over time." },
};

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    panel.style.display = panel.dataset.tabPanel === name ? "" : "none";
  });
  const meta = TAB_META[name];
  if (meta) {
    $("tabTitle").textContent = meta.title;
    $("tabSubtitle").textContent = meta.subtitle;
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  $("loadSampleBtn").addEventListener("click", loadSample);
  $("runBtn").addEventListener("click", runAnalysis);
  $("saveBtn").addEventListener("click", saveCurrentReport);
  $("employeeCsvInput").addEventListener("change", handleEmployeeUpload);
  $("applicantCsvInput").addEventListener("change", handleApplicantUpload);
  $("downloadEmployeeTemplate").addEventListener("click", () => downloadTemplate("employee_data_template.csv", EMPLOYEE_TEMPLATE));
  $("downloadApplicantTemplate").addEventListener("click", () => downloadTemplate("applicant_data_template.csv", APPLICANT_TEMPLATE));

  REP_FIELDS.forEach((id) => {
    $(id).addEventListener("input", () => updateGroupBHint(id));
  });

  $("logoutBtn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
    });
    window.location.href = "/login";
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  refreshSavedClients();
});
