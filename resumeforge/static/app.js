/* ResumeForge uses the local server only; resume text is never inserted as HTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const DRAFT_KEY = "resumeforge.draft.v1";
const state = { profile: null, plan: null, result: null, busy: false, importing: false, claimEdits: new Map(), confirmed: new Set(), pollTimer: null };
let analysisKey = null;
let analysisRows = [];
let priorityJob = null;
let suggestedList = "";
let analyzing = false;
let revision = 0;
const exampleEdits = new Map();
let exampleRows = [];
const scratch = { drafts: [], loading: false, generation: 0 };
const IDEAS_PER_ROLE = 12;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}

function message(text, error = false) {
  const target = $(error ? "error-message" : "app-message");
  $(error ? "app-message" : "error-message").hidden = true;
  target.textContent = text;
  target.hidden = !text;
}

function inline(id, text, kind = "") {
  $(id).textContent = text;
  $(id).className = `inline-status ${kind}`;
}

function describeError(data) {
  const detail = data?.detail ?? data?.error ?? data?.message ?? data;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => {
    const location = Array.isArray(item.loc) ? `${item.loc.filter((part) => part !== "body").join(".")}: ` : "";
    return location + (item.msg || item.message || JSON.stringify(item));
  }).join("; ");
  return detail && typeof detail === "object" ? JSON.stringify(detail) : "The server could not complete the request.";
}

async function api(path, body, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      ...options,
    });
  } catch (error) {
    throw new Error(`Could not reach the local ResumeForge server. Keep its terminal running. ${error.message}`);
  }
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { throw new Error(`The server returned an unreadable response (${response.status}).`); }
  if (!response.ok) throw new Error(describeError(data));
  return data;
}

function settings(allowBlankModel = false) {
  const maxRounds = Number($("max-rounds").value);
  const timeout = Number($("timeout").value);
  if (!Number.isInteger(maxRounds) || maxRounds < 1 || maxRounds > 5) throw new Error("Maximum revision rounds must be from 1 to 5.");
  if (!Number.isInteger(timeout) || timeout < 10 || timeout > 900) throw new Error("Model timeout must be from 10 to 900 seconds.");
  const provider = $("provider").value;
  const baseUrl = $("base-url").value.trim();
  const model = $("model-name").value.trim();
  if (provider !== "none") {
    let endpoint;
    try { endpoint = new URL(baseUrl); } catch { throw new Error("Enter a valid model endpoint URL."); }
    if (!["http:", "https:"].includes(endpoint.protocol)) throw new Error("The model endpoint must use HTTP or HTTPS.");
    if (endpoint.username || endpoint.password || /[?&](?:api_key|key|token|access_token)=/i.test(endpoint.search)) throw new Error("Keep credentials out of the endpoint URL. Set the API key in the server environment instead.");
    if (!model && !allowBlankModel) throw new Error("Enter the name of a model available at your endpoint.");
  }
  const apiKeyEnv = $("api-key-env").value.trim() || "RESUMEFORGE_API_KEY";
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(apiKeyEnv)) throw new Error("Enter an environment variable name for the API key, such as RESUMEFORGE_API_KEY. Never enter the key itself.");
  return { draft_mode: $("draft-mode").value, strategy: $("strategy").value, wording_policy: $("draft-mode").value === "inspiration" ? "rewrite" : $("wording-policy").value, provider, base_url: baseUrl || "http://127.0.0.1:11434", model, api_key_env: apiKeyEnv, timeout_seconds: timeout, max_rounds: maxRounds };
}

function populateSettings(value = {}) {
  $("draft-mode").value = value.wording_policy === "verified" || value.draft_mode === "grounded" ? "grounded" : "inspiration";
  $("grounded-options").hidden = $("draft-mode").value === "inspiration";
  $("wording-policy").value = value.wording_policy === "verified" ? "verified" : "rewrite";
  $("strategy").value = value.strategy || "full";
  $("provider").value = ["none", "ollama", "openai-compatible"].includes(value.provider) ? value.provider : "none";
  $("base-url").value = value.base_url || "http://127.0.0.1:11434";
  $("model-name").value = value.model || "";
  $("api-key-env").value = value.api_key_env || "RESUMEFORGE_API_KEY";
  $("timeout").value = value.timeout_seconds || 180;
  $("max-rounds").value = value.max_rounds || 3;
  updateProvider();
}

function updateProvider() {
  const provider = $("provider").value;
  const connected = provider !== "none";
  $("model-fields").hidden = !connected;
  $("api-key-field").hidden = provider !== "openai-compatible";
  $("model-note").textContent = connected
    ? "The endpoint supplies the writing model. ResumeForge measures and checks the resulting PDF locally."
    : "Render and inspect your resume without AI. Connect a model for contextual rewriting.";
  updateActions();
  $("run-note").textContent = connected ? "Rewrite, render, measure, and review. Export unlocks when the checks pass." : "Built-in examples are available offline. Connect a local model for original wording.";
  inline("model-status", "");
}

function parseJSON(id, label) {
  try { return JSON.parse($(id).value); }
  catch (error) { throw new Error(`${label} is not valid JSON: ${error.message}`); }
}

function readProfile() {
  const profile = parseJSON("profile-json", "Source profile");
  if (!profile || !profile.name || !Array.isArray(profile.roles) || !profile.roles.length) throw new Error("Your source profile needs a name and at least one experience role.");
  state.profile = profile;
  return profile;
}

function populateProfile(profile) {
  state.profile = profile;
  $("profile-json").value = JSON.stringify(profile, null, 2);
  renderProfileSummary(profile);
}

function renderProfileSummary(profile) {
  $("profile-name").textContent = profile.name;
  const roles = profile.roles || [];
  const bullets = roles.reduce((count, role) => count + (role.bullets?.length || 0), 0);
  $("profile-summary").textContent = `${roles.length} ${roles.length === 1 ? "role" : "roles"} · ${bullets} source bullets · ${(profile.facts || []).length} added facts`;
  for (const id of ["fact-role", "idea-role"]) {
    const select = $(id);
    const selectedRole = select.value;
    select.replaceChildren();
    for (const role of roles) {
      const option = node("option", "", `${role.title} · ${role.company}`);
      option.value = role.id;
      select.append(option);
    }
    if (roles.some((role) => role.id === selectedRole)) select.value = selectedRole;
  }
  const currentRoles = new Set(roles.map(role => ideaRoleKey(profile, role.id)));
  scratch.drafts = scratch.drafts.filter(idea => currentRoles.has(idea.roleKey));
  renderIdeas();
  renderFacts(profile);
  updateActions();
}

function roleName(roleId) {
  const role = state.profile?.roles?.find((item) => item.id === roleId);
  return role ? `${role.title} · ${role.company}` : roleId || "Profile";
}

function renderFacts(profile) {
  $("fact-list").replaceChildren();
  for (const fact of profile.facts || []) {
    const item = node("li");
    const content = node("p");
    content.append(node("strong", "", `${fact.confirmed ? "Verified" : "Unconfirmed"} · ${roleName(fact.role_id)}`), document.createTextNode(fact.text));
    const remove = node("button", "", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove fact: ${fact.text.slice(0, 70)}`);
    remove.addEventListener("click", () => {
      try {
        const latest = readProfile();
        latest.facts = (latest.facts || []).filter((item) => item.id !== fact.id);
        populateProfile(latest);
        sourceChanged();
        message("Fact removed from the source profile. Rebuild to update the PDF.");
      } catch (error) { message(error.message, true); }
    });
    item.append(content, remove);
    $("fact-list").append(item);
  }
}

function recordVerifiedFact(profile, roleId, text) {
  if (state.busy || state.importing) throw new Error("Wait for the current build or import to finish.");
  if (!profile.roles.some(role => role.id === roleId)) throw new Error("Choose an experience role in your current profile.");
  profile.facts = profile.facts || [];
  if (profile.facts.some(fact => fact.confirmed && fact.role_id === roleId && fact.text.trim() === text)) {
    throw new Error("This verified experience already exists under that role.");
  }
  profile.facts.push({ id: `fact-${crypto.randomUUID()}`, text, role_id: roleId, confirmed: true });
  populateProfile(profile);
  sourceChanged();
}

function addFact() {
  try {
    const text = $("fact-text").value.trim();
    if (!text) { $("fact-text").focus(); throw new Error("Describe the verified experience you want to add."); }
    recordVerifiedFact(readProfile(), $("fact-role").value, text);
    $("fact-text").value = "";
    message("Verified experience added. The next build can use it as evidence.");
  } catch (error) { message(error.message, true); }
}

function ideaRoleKey(profile, roleId) {
  const role = profile?.roles?.find(item => item.id === roleId);
  return role ? JSON.stringify([profile.source_sha256 || profile.name, role.id, role.company, role.title, role.dates]) : null;
}

function ideaWords(text) {
  return text.toLowerCase().match(/[\p{L}\p{N}]+(?:\.\d+)?|[%$€£¥<>]/gu)?.join(" ") || "";
}

function renderIdeas() {
  const roleId = $("idea-role").value;
  const roleKey = ideaRoleKey(state.profile, roleId);
  const drafts = scratch.drafts.filter(item => item.roleKey === roleKey);
  const waiting = state.busy || state.importing;
  $("generate-ideas").disabled = waiting || !roleKey || scratch.loading;
  $("generate-ideas").textContent = scratch.loading ? "Generating ideas…" : drafts.length ? "Generate more ideas" : "Generate ideas";
  const list = $("idea-list");
  list.replaceChildren();
  for (const [index, idea] of drafts.entries()) {
    const card = node("article", "claim-card idea-card");
    const label = node("label", "", `Fictional example ${index + 1} · edit into your own words`);
    const input = node("textarea");
    input.id = `idea-text-${index}`;
    label.htmlFor = input.id;
    input.value = idea.edited;
    input.rows = 4;
    input.maxLength = 2000;
    const checks = node("ul", "note-list");
    for (const item of idea.verify) checks.append(node("li", "", item));
    const confirm = node("button", "button secondary", "Confirm as accurate & add");
    confirm.type = "button";
    const edited = () => Boolean(ideaWords(input.value)) && ideaWords(input.value) !== ideaWords(idea.original);
    confirm.disabled = waiting || !edited();
    input.addEventListener("input", () => {
      idea.edited = input.value;
      confirm.disabled = state.busy || state.importing || !edited();
    });
    confirm.addEventListener("click", () => {
      try {
        const profile = readProfile();
        if (!scratch.drafts.includes(idea) || ideaRoleKey(profile, $("idea-role").value) !== idea.roleKey) throw new Error("Choose this idea’s original experience role.");
        if (!edited()) throw new Error("Replace the example with a statement about your real work.");
        const text = input.value.trim();
        const problem = claimProblem({ text, role_id: roleId });
        if (problem) throw new Error(problem);
        recordVerifiedFact(profile, roleId, text);
        scratch.drafts = scratch.drafts.filter(item => item !== idea);
        renderIdeas();
        inline("ideas-status", `Added your verified wording to ${roleName(roleId)}. Build to use it.`, "success");
      } catch (error) { inline("ideas-status", error.message, "error"); }
    });
    const discard = node("button", "text-button", "Discard");
    discard.type = "button";
    discard.addEventListener("click", () => {
      scratch.drafts = scratch.drafts.filter(item => item !== idea);
      renderIdeas();
    });
    const actions = node("div", "idea-actions");
    actions.append(confirm, discard);
    card.append(label, input);
    if (idea.verify.length) card.append(node("p", "micro", "Details to verify"), checks);
    card.append(actions);
    list.append(card);
  }
}

async function generateIdeas() {
  if (scratch.loading || state.busy || state.importing) return;
  try {
    const profile = readProfile();
    const roleId = $("idea-role").value;
    const roleKey = ideaRoleKey(profile, roleId);
    if (!roleKey) throw new Error("Choose an experience role first.");
    const previous = scratch.drafts.filter(item => item.roleKey === roleKey).map(item => item.original);
    if (previous.length > IDEAS_PER_ROLE - 3) throw new Error("Add or discard a few ideas for this role to make room for another three.");
    const body = { profile, role_id: roleId, focus: $("idea-focus").value.trim(), previous,
      job_description: $("job-description").value.trim(), keywords: keywords(), settings: settings() };
    const generation = scratch.generation;
    scratch.loading = true;
    renderIdeas();
    inline("ideas-status", `Preparing fictional examples for ${roleName(roleId)}…`);
    const data = await api("/api/ideas", body);
    if (generation !== scratch.generation || roleKey !== ideaRoleKey(readProfile(), roleId)) return;
    const seen = new Set(previous.map(ideaWords));
    const fresh = [];
    for (const item of (data.ideas || []).slice(0, 3)) {
      const original = typeof item.text === "string" ? item.text.trim() : "";
      const words = ideaWords(original);
      if (!words || original.length > 2000 || seen.has(words)) continue;
      seen.add(words);
      fresh.push({ roleKey, original, edited: original, verify: (item.verify || []).filter(x => typeof x === "string").slice(0, 8) });
    }
    scratch.drafts.unshift(...fresh);
    inline("ideas-status", fresh.length ? `${fresh.length} fictional ${fresh.length === 1 ? "example" : "examples"} for ${roleName(roleId)}.` : "No new ideas this time. Try a different topic.");
  } catch (error) { inline("ideas-status", error.message, "error"); }
  finally {
    scratch.loading = false;
    renderIdeas();
  }
}

function setBusy(busy, progress = "Building your document…") {
  state.busy = busy;
  renderIdeas();
  updateActions();
  $("apply-review").disabled = busy;
  $("apply-plan").disabled = busy;
  $("source-file").disabled = busy;
  $("preview-working").hidden = !busy;
  $("progress-text").textContent = progress;
  if (busy) {
    $("result-badge").textContent = "Checking the page";
    $("result-badge").className = "status-badge neutral";
    setDownload(null);
    $("export-note").textContent = "Checking the current draft…";
  }
}

function setDownload(url) {
  const button = $("download-button");
  if (url) {
    button.href = url;
    button.classList.remove("disabled");
    button.removeAttribute("aria-disabled");
    button.removeAttribute("tabindex");
    button.setAttribute("download", "resume.pdf");
  } else {
    button.removeAttribute("href");
    button.classList.add("disabled");
    button.setAttribute("aria-disabled", "true");
    button.setAttribute("tabindex", "-1");
    button.removeAttribute("download");
  }
}

function keywords() {
  const values = [...new Set($("keywords").value.split(/[,;\n]/).map((term) => term.trim()).filter(Boolean))];
  if (values.length > 100) throw new Error("Use no more than 100 keywords.");
  if (values.some((term) => term.length > 100)) throw new Error("Each keyword must be no more than 100 characters.");
  return values;
}

function editedPlan(useClaimFields = true) {
  const plan = parseJSON("plan-json", "Tailoring plan");
  if (!plan || !Array.isArray(plan.candidates) || !Array.isArray(plan.proposed_claims)) throw new Error("The tailoring plan needs candidates and proposed_claims arrays.");
  if (useClaimFields) {
    for (const claim of plan.proposed_claims) {
      if (state.claimEdits.has(claim.id)) claim.text = state.claimEdits.get(claim.id).trim();
      if (!claim.text) throw new Error("A proposed claim cannot be blank. Leave it unconfirmed to exclude it.");
    }
  }
  for (const claim of plan.proposed_claims) {
    if (!state.confirmed.has(claim.id)) continue;
    const problem = claimProblem(claim);
    if (problem) throw new Error(problem);
  }
  return plan;
}

function claimProblem(claim) {
  if (!state.profile.roles.some((role) => role.id === claim.role_id)) return "Choose the relevant role for each confirmed claim.";
  const text = String(claim.text || "").trim();
  if (!text || /\?|\[[^\]]+\]|<[^>]+>|\b(?:TBD|TODO|PLACEHOLDER)\b|\b(?:X|XX|N)\s*%/i.test(text) || /^(?:have you|did you|do you|can you|could you|would you|describe |tell us|insert |add (?:a|your) |confirm whether)/i.test(text) || /\b(?:if true|if applicable|if accurate)\b/i.test(text)) {
    return "Replace questions and placeholders with the actual accomplishment before confirming a claim.";
  }
  return "";
}

function analysisInput() {
  return JSON.stringify([$("job-description").value.trim(), $("profile-json").value,
    $("provider").value, $("base-url").value, $("model-name").value, $("strategy").value]);
}

function updateActions() {
  const waiting = state.busy || state.importing || analyzing;
  const job = $("job-description").value.trim();
  const reviewFirst = job && analysisKey !== analysisInput();
  $("run-label").textContent = reviewFirst ? "Analyze posting" : "Build & inspect PDF";
  $("analyze-job").disabled = !job || !state.profile || waiting;
  $("run-button").disabled = !state.profile || waiting;
  $("apply-examples").disabled = waiting;
}

function invalidateAnalysis(changePosting = false) {
  if (changePosting && priorityJob !== null && priorityJob !== $("job-description").value.trim()) {
    $("keywords").value = "";
    priorityJob = null;
    suggestedList = "";
  }
  analysisKey = null;
  analysisRows = [];
  $("analysis-detail").hidden = true;
  inline("analysis-status", "");
  updateActions();
}

function hideProof() {
  setDownload(null);
  $("pdf-preview").removeAttribute("src");
  $("pdf-preview").hidden = true;
  $("open-preview").removeAttribute("href");
  $("open-preview").hidden = true;
  $("preview-empty").hidden = false;
  renderMetrics({});
  $("results-section").hidden = true;
}

function invalidateOutput(keepPlan = false) {
  revision++;
  if (!state.result && !state.plan && !state.busy) return;
  hideProof();
  state.result = null;
  if (!keepPlan) { renderPlan(null); renderExamples({}); }
  $("result-badge").textContent = "Draft changed";
  $("result-badge").className = "status-badge warning";
  $("export-note").textContent = keepPlan ? "Apply your edits to check the updated PDF." : "Build again to check this draft.";
}

function sourceChanged() {
  invalidateOutput();
  invalidateAnalysis();
}

function showAnalysis(rows) {
  analysisRows = rows;
  const labels = {exact: "Exact source match", related: "Related source evidence", missing: "Missing from source"};
  $("analysis-list").replaceChildren(...rows.map(row => {
    const category = row.kind === "credential" ? " · Education/eligibility requirement" : "";
    return node("li", "", `${row.term}${category} · ${labels[row.evidence] || "Unknown"}. ${row.rationale}`);
  }));
  $("analysis-detail").hidden = !rows.length;
  analysisKey = analysisInput();
  priorityJob = $("job-description").value.trim();
  inline("analysis-status", rows.length ? "Review the priorities below, then build when ready." : "Add your priorities below or build with the list empty.", "success");
  updateActions();
}

async function analyzePosting() {
  if (state.busy || state.importing || analyzing) return;
  const job = $("job-description").value.trim();
  if (!job) { message("Paste a posting to analyze.", true); return; }
  if (analysisKey === analysisInput()) {
    $("analysis-detail").open = true;
    $("keywords").focus();
    return;
  }
  const key = analysisInput();
  const previous = $("keywords").value;
  const keepList = priorityJob === job && previous !== suggestedList;
  try {
    analyzing = true;
    updateActions();
    inline("analysis-status", "Reading posting…");
    const requested = priorityJob === job ? [] : keywords();
    const response = await api("/api/analyze", {profile: readProfile(), job_description: job, keywords: requested, settings: settings(true)});
    if (key !== analysisInput()) return;
    const rows = response.priorities;
    if (!keepList && previous === $("keywords").value) {
      const actionable = rows.filter(row => row.kind !== "credential").slice(0, 7).map(row => row.term);
      suggestedList = [...new Set([...requested, ...actionable])].join("\n");
      $("keywords").value = suggestedList;
    }
    showAnalysis(rows);
    $("keywords").focus();
    message("Your priority list is ready to review.");
  } catch (error) {
    inline("analysis-status", error.message, "error");
  } finally {
    analyzing = false;
    updateActions();
  }
}

function renderExamples(report, edits = {}) {
  exampleEdits.clear();
  const rows = report.inspiration_bullets || [];
  exampleRows = rows;
  $("example-section").hidden = !rows.length;
  $("example-list").replaceChildren();
  for (const item of rows) {
    const label = node("label", "", roleName(item.role_id));
    const field = node("textarea");
    if (typeof edits[item.id] === "string") exampleEdits.set(item.id, edits[item.id]);
    field.value = exampleEdits.get(item.id) ?? item.text;
    field.maxLength = 2000;
    field.rows = 4;
    field.addEventListener("input", () => {
      exampleEdits.set(item.id, field.value.trim());
      invalidateOutput(true);
    });
    label.append(field);
    $("example-list").append(label);
  }
}

async function startRun(usePlan = false, useClaimFields = true) {
  if (state.busy || state.importing || analyzing) return;
  const startedAt = revision;
  try {
    const profile = readProfile();
    if ($("job-description").value.trim() && analysisKey !== analysisInput()) {
      await analyzePosting();
      return;
    }
    const plan = usePlan ? editedPlan(useClaimFields) : null;
    if (plan) {
      // Rebuild previously confirmed claims from the currently reviewed text and
      // role. Unchecking a claim removes it from this run, including old copies.
      const confirmedFactIds = new Set(plan.proposed_claims.map((claim) => `confirmed:${claim.id}`));
      profile.facts = (profile.facts || []).filter((fact) => !confirmedFactIds.has(fact.id));
      plan.candidates = plan.candidates.filter((candidate) => !candidate.evidence_ids?.some((id) => confirmedFactIds.has(id)));
    }
    const request = { profile, edit_request: $("edit-request").value, job_description: $("job-description").value.trim(), keywords: keywords(), settings: settings(), plan, reviewed_priorities: analysisKey ? keywords() : null, draft_edits: usePlan ? Object.fromEntries(exampleEdits) : {}, confirmed_claim_ids: usePlan ? [...state.confirmed] : [] };
    hideProof();
    message("");
    setBusy(true, "Selecting accomplishments and measuring the page…");
    const result = await api("/api/run", request);
    if (startedAt !== revision) { setBusy(false); return; }
    if (["running", "queued", "pending"].includes(result.status)) {
      if (!result.id) throw new Error("The server did not provide a run ID.");
      pollRun(result.id, startedAt);
    } else finishRun(result);
  } catch (error) { if (startedAt === revision) failRun(error); else setBusy(false); }
}

async function pollRun(id, startedAt, failures = 0) {
  state.pollTimer = window.setTimeout(async () => {
    try {
      const result = await api(`/api/runs/${encodeURIComponent(id)}`);
      if (startedAt !== revision) { setBusy(false); return; }
      if (["running", "queued", "pending"].includes(result.status)) {
        if (result.message) $("progress-text").textContent = result.message;
        pollRun(id, startedAt);
      } else finishRun(result);
    } catch (error) {
      if (startedAt !== revision) { setBusy(false); return; }
      if (failures < 3) {
        $("progress-text").textContent = "Reconnecting to the local server…";
        pollRun(id, startedAt, failures + 1);
      } else failRun(error);
    }
  }, failures ? 3000 : 1200);
}

function failRun(error) {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  setBusy(false);
  $("result-badge").textContent = "Build interrupted";
  $("result-badge").className = "status-badge failed";
  $("export-note").textContent = "Resolve the error and rebuild to enable export.";
  setDownload(null);
  message(error.message || String(error), true);
}

function localPath(value, fallback) {
  if (!value) return fallback;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : fallback;
  } catch { return fallback; }
}

function finishRun(result) {
  if (result.status === "failed" && !result.report) {
    failRun(new Error(result.error || result.message || "Build failed."));
    return;
  }
  setBusy(false);
  state.result = result;
  if (result.profile) {
    // The returned profile contains the user's explicit confirmations, including removals.
    const wasAnalyzed = analysisKey === analysisInput();
    populateProfile(result.profile);
    if (wasAnalyzed) analysisKey = analysisInput();
    updateActions();
  }
  const status = result.status || "failed";
  const report = result.report || {};
  const descriptions = {
    ready: ["Ready to export", "ready", "The document passed its content and layout checks."],
    needs_review: ["Review needed", "warning", "Inspect the content review notes and any proposed claims, then apply your edits to check the page again."],
    needs_content: ["More content needed", "warning", "The page is not ready to export. Add relevant verified experience or revise the plan, then check the fit again."],
    failed: ["Checks did not pass", "failed", "This version did not pass the required checks. See the review notes and revise before exporting."],
  };
  const description = descriptions[status] || descriptions.failed;
  if (status === "needs_content" && finite(report.bottom_gap_pt) && report.bottom_gap_pt < 0) description[0] = "Content needs fitting";
  $("result-badge").textContent = description[0];
  $("result-badge").className = `status-badge ${description[1]}`;
  message(result.message || result.error || description[2], status === "failed");
  const runId = encodeURIComponent(result.id || "");
  const previewUrl = result.id ? localPath(result.pdf_url, `/api/runs/${runId}/preview.pdf`) : null;
  if (previewUrl && (result.pdf_url || report.pages)) {
    $("pdf-preview").src = previewUrl;
    $("pdf-preview").hidden = false;
    $("preview-empty").hidden = true;
    $("open-preview").href = previewUrl;
    $("open-preview").hidden = false;
  }
  const canExport = status === "ready" && report.geometry_passed === true && report.quality_review?.passed === true;
  setDownload(canExport ? localPath(result.download_url, `/api/runs/${runId}/resume.pdf`) : null);
  $("export-note").textContent = canExport
    ? (report.inspiration_bullets?.length ? "Generated examples are included. You can edit them above and refit the page." : report.wording_policy === "verified" ? "Experience wording matches your verified sources. Check that the selection suits the job." : "Automated checks passed. Compare changed bullets with your source before submitting.")
    : status === "needs_review" ? "Confirm accurate claims and rerun the checks to unlock export."
      : "Export is locked until content and layout checks pass.";
  renderMetrics(report);
  renderPlan(result.plan, report.confirmed_claim_ids || []);
  renderChanges(report);
  renderExamples(report);
}

function finite(value) { return typeof value === "number" && Number.isFinite(value); }

function renderMetrics(report) {
  $("metric-pages").textContent = finite(report.pages) ? report.pages : "—";
  $("metric-fill").textContent = finite(report.fill_ratio) ? `${Math.round(report.fill_ratio * 100)}%` : "—";
  $("metric-gap").textContent = finite(report.bottom_gap_pt) ? `${report.bottom_gap_pt.toFixed(1)} pt` : "—";
  $("fill-bar").style.width = finite(report.fill_ratio) ? `${Math.max(0, Math.min(100, report.fill_ratio * 100))}%` : "0%";
  const iterations = Array.isArray(report.iterations) ? report.iterations.length : report.iterations;
  $("iteration-count").textContent = finite(iterations) ? `${iterations} ${iterations === 1 ? "render pass" : "render passes"}` : "Measured after rendering";
  $("fit-explanation").textContent = finite(report.target_bottom_gap_pt)
    ? `Bottom gap is measured above the fixed bottom margin. Target: 0–${report.target_bottom_gap_pt.toFixed(1)} pt. Fonts, margins, and line spacing remain fixed.`
    : "Content must fit one page and finish within the template’s bottom tolerance.";
  $("check-list").replaceChildren();
  const checks = [
    ["One page", finite(report.pages) ? report.pages === 1 : undefined],
    ["Geometry", report.geometry_passed],
    [report.semantic_review === "source-preserving checks" ? "Source text checks" : "Content review", report.quality_review?.passed],
  ];
  for (const [label, pass] of checks) {
    if (pass === undefined) continue;
    $("check-list").append(node("span", `check-item${pass ? "" : " fail"}`, `${pass ? "✓" : "○"} ${label}`));
  }
}

function renderPlan(plan, confirmedIds = []) {
  state.plan = plan || null;
  state.claimEdits.clear();
  state.confirmed.clear();
  for (const id of confirmedIds) state.confirmed.add(id);
  $("claims-list").replaceChildren();
  $("plan-editor").hidden = !plan;
  $("plan-json").value = plan ? JSON.stringify(plan, null, 2) : "";
  const claims = plan?.proposed_claims || [];
  $("review-section").hidden = claims.length === 0;
  $("claim-count").textContent = String(claims.length);
  for (const [index, claim] of claims.entries()) {
    const card = node("article", "claim-card");
    const labelId = `claim-label-${index}`;
    const title = node("h3", "", roleName(claim.role_id));
    title.id = labelId;
    const reason = node("p", "claim-reason", claim.reason || "This claim needs your confirmation.");
    const roleLabel = node("label", "", "Relevant role");
    roleLabel.htmlFor = `claim-role-${index}`;
    const roleSelect = node("select");
    roleSelect.id = roleLabel.htmlFor;
    const placeholder = node("option", "", "Choose the relevant role…");
    placeholder.value = "";
    roleSelect.append(placeholder);
    for (const role of state.profile?.roles || []) {
      const option = node("option", "", `${role.title} · ${role.company}`);
      option.value = role.id;
      roleSelect.append(option);
    }
    roleSelect.value = claim.role_id || "";
    roleSelect.addEventListener("change", () => {
      claim.role_id = roleSelect.value;
      state.confirmed.delete(claim.id);
      checkbox.checked = false;
      title.textContent = roleName(claim.role_id);
      syncClaimToPlan(claim.id, undefined, roleSelect.value);
      invalidateOutput(true);
    });
    const textarea = node("textarea");
    textarea.value = claim.text;
    textarea.maxLength = 2000;
    textarea.rows = 4;
    textarea.setAttribute("aria-labelledby", labelId);
    state.claimEdits.set(claim.id, claim.text);
    textarea.addEventListener("input", () => {
      state.claimEdits.set(claim.id, textarea.value);
      state.confirmed.delete(claim.id);
      checkbox.checked = false;
      syncClaimToPlan(claim.id, textarea.value);
      invalidateOutput(true);
    });
    const label = node("label", "check-label");
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.confirmed.has(claim.id);
    checkbox.addEventListener("change", () => {
      const problem = checkbox.checked ? claimProblem({ ...claim, text: textarea.value, role_id: roleSelect.value }) : "";
      if (problem) {
        checkbox.checked = false;
        state.confirmed.delete(claim.id);
        message(problem, true);
        return;
      }
      invalidateOutput(true);
      if (checkbox.checked) state.confirmed.add(claim.id);
      else state.confirmed.delete(claim.id);
    });
    label.append(checkbox, document.createTextNode("I confirm this experience is accurate"));
    card.append(title, reason, roleLabel, roleSelect, textarea, label);
    $("claims-list").append(card);
  }
}

function syncClaimToPlan(id, text, roleId) {
  try {
    const plan = JSON.parse($("plan-json").value);
    const claim = plan.proposed_claims?.find((item) => item.id === id);
    if (claim) {
      if (text !== undefined) claim.text = text;
      if (roleId !== undefined) claim.role_id = roleId;
      $("plan-json").value = JSON.stringify(plan, null, 2);
    }
  } catch { /* Preserve deliberate in-progress JSON edits until the user applies them. */ }
}

function termText(term) {
  return typeof term === "string" ? term : term.term || term.keyword || JSON.stringify(term);
}

function renderChanges(report) {
  $("results-section").hidden = false;
  $("change-list").replaceChildren();
  const changes = report.changes || [];
  $("change-count").textContent = `${changes.length} ${changes.length === 1 ? "CHANGE" : "CHANGES"}`;
  if (!changes.length) $("change-list").append(node("p", "helper-text", "No bullet changes in this version. The preview reflects the source and selected layout."));
  for (const change of changes) {
    const card = node("article", "change-card");
    card.append(node("h3", "", roleName(change.role_id)));
    if (change.before) card.append(node("p", "before", `Before · ${change.before}`));
    card.append(node("p", "after", change.after ? `After · ${change.after}` : "Removed from this version"));
    if (change.reason) card.append(node("p", "reason", change.reason));
    $("change-list").append(card);
  }
  $("keyword-coverage").replaceChildren();
  for (const [key, label, className] of [["matched", "Present in PDF", "chip"], ["related", "Related evidence in PDF", "chip"], ["missing", "Keywords not present", "chip missing"]]) {
    const terms = report.keyword_coverage?.[key] || [];
    if (!Array.isArray(terms) || !terms.length) continue;
    $("keyword-coverage").append(node("p", "coverage-label", label));
    const chips = node("div", "chips");
    for (const term of terms) chips.append(node("span", className, termText(term)));
    $("keyword-coverage").append(chips);
  }
  const warnings = [...(report.warnings || []), ...(report.issues || []), ...(report.quality_review?.issues || []), ...(report.quality_review?.suggestions || []), ...(state.plan?.notes || [])];
  $("warning-list").replaceChildren();
  for (const warning of [...new Set(warnings.map((value) => typeof value === "string" ? value : JSON.stringify(value)))]) $("warning-list").append(node("li", "", warning));
  $("warnings-details").hidden = warnings.length === 0;
  $("warnings-details").open = warnings.length > 0 && state.result?.status !== "ready";
}

async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    if (!/\.(pdf|docx)$/i.test(file.name)) throw new Error("Choose a PDF or DOCX file.");
    if (file.size > 10 * 1024 * 1024) throw new Error("Choose a resume file no larger than 10 MiB.");
    const currentSettings = settings();
    state.importing = true;
    updateActions();
    renderIdeas();
    $("source-file").disabled = true;
    $("run-button").disabled = true;
    $("apply-review").disabled = true;
    $("apply-plan").disabled = true;
    inline("import-status", "Reading and structuring the resume…");
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error("Could not read that file."));
      reader.readAsDataURL(file);
    });
    const result = await api("/api/import", { filename: file.name, data_base64: data, settings: currentSettings });
    if (result.profile) {
      scratch.generation++;
      scratch.drafts = [];
      $("idea-focus").value = "";
      inline("ideas-status", "");
      populateProfile(result.profile);
      sourceChanged();
      inline("import-status", `Imported ${file.name}. Review the source profile before building.`, "success");
      message("Source imported. Review the structured profile for extraction errors before building your PDF.");
    } else {
      inline("import-status", "Text extracted, but no structured profile was returned. Your current source has been kept.");
      message("The import did not produce a structured profile. Configure a writing model, or use the extracted text to update Source profile & advanced edits.");
    }
    $("extracted-source")?.remove();
    if (result.text) {
      const details = node("details", "small-details");
      details.id = "extracted-source";
      details.append(node("summary", "", "Inspect extracted text"));
      const text = node("textarea", "code-input");
      text.value = result.text;
      text.readOnly = true;
      text.rows = 8;
      text.setAttribute("aria-label", "Text extracted from imported resume");
      details.append(text);
      $("import-status").after(details);
    }
    if (result.warnings?.length) inline("import-status", `${$("import-status").textContent} ${result.warnings.join(" ")}`);

  } catch (error) { inline("import-status", error.message, "error"); }
  finally {
    state.importing = false;
    renderIdeas();
    $("source-file").disabled = state.busy;
    $("source-file").value = "";
    updateActions();
    $("apply-review").disabled = state.busy;
    $("apply-plan").disabled = state.busy;
  }
}

async function testModel() {
  try {
    const value = settings(true);
    $("test-model").disabled = true;
    inline("model-status", "Checking endpoint and model availability…");
    const result = await api("/api/model-health", value);
    $("available-models").replaceChildren();
    for (const name of result.models || []) {
      const option = node("option");
      option.value = name;
      $("available-models").append(option);
    }
    const good = result.ok === true || result.available === true || ["ok", "ready", "healthy"].includes(result.status);
    inline("model-status", result.message || result.error || (good ? "Model is available." : describeError(result)), good ? "success" : "error");
  } catch (error) { inline("model-status", error.message, "error"); }
  finally { $("test-model").disabled = false; }
}

function saveDraft() {
  try {
    const value = { version: 2, profile: readProfile(), settings: settings(), edit_request: $("edit-request").value, job_description: $("job-description").value, keywords: $("keywords").value };
    value.review = analysisKey === analysisInput() ? {rows: analysisRows, suggestedList} : null;
    if (state.plan) {
      value.editor = {plan: editedPlan(false), confirmed: [...state.confirmed],
        examples: exampleRows, edits: Object.fromEntries(exampleEdits)};
    }
    value.brainstorm = { role: $("idea-role").value, focus: $("idea-focus").value, drafts: scratch.drafts };
    // No API key field or credential is accepted or stored by the browser.
    localStorage.setItem(DRAFT_KEY, JSON.stringify(value));
    renderProfileSummary(value.profile);
    message("Draft saved in this browser. It includes your source resume, job description, keywords, and model configuration.");
  } catch (error) { message(`Draft could not be saved. ${error.message}`, true); }
}

function updateJobCount() { $("job-count").textContent = `${$("job-description").value.length.toLocaleString()} / 40,000`; }

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    populateSettings(data.settings);
    if (data.settings?.model === "resumeforge-qwen35-4b") { $("use-laptop").hidden = false; $("use-laptop").onclick = () => { populateSettings(data.settings); invalidateAnalysis(); invalidateOutput(); message("Installed laptop model selected."); }; }
    if (data.profile) populateProfile(data.profile);
    let draft;
    try {
      const saved = localStorage.getItem(DRAFT_KEY);
      draft = saved ? JSON.parse(saved) : null;
    } catch { message("The saved draft could not be read. The original source is loaded."); }
    if ([1, 2].includes(draft?.version) && draft.profile?.name && Array.isArray(draft.profile.roles)) {
      populateProfile(draft.profile);
      populateSettings(draft.settings);
      $("edit-request").value = draft.edit_request || "";
      $("job-description").value = draft.job_description || "";
      $("keywords").value = draft.keywords || "";
      if (draft.version === 2 && draft.job_description && draft.keywords) priorityJob = draft.job_description.trim();
      if (draft.version === 2 && Array.isArray(draft.review?.rows)) {
        suggestedList = draft.review.suggestedList ?? "";
        showAnalysis(draft.review.rows);
      }
      if (draft.version === 2 && draft.editor?.plan && Array.isArray(draft.editor.examples)) {
        renderPlan(draft.editor.plan, draft.editor.confirmed);
        renderExamples({inspiration_bullets: draft.editor.examples}, draft.editor.edits);
      }
      updateActions();
      const savedIdeas = draft.brainstorm;
      if (Array.isArray(savedIdeas?.drafts)) {
        const roles = draft.profile.roles;
        const keys = new Set(roles.map(role => ideaRoleKey(draft.profile, role.id)));
        scratch.drafts = savedIdeas.drafts.slice(0, IDEAS_PER_ROLE * roles.length).filter(item =>
          item && keys.has(item.roleKey) && typeof item.original === "string" && typeof item.edited === "string" &&
          item.original.length <= 2000 && item.edited.length <= 2000 && Array.isArray(item.verify));
        if (roles.some(r => r.id === savedIdeas.role)) $("idea-role").value = savedIdeas.role;
        $("idea-focus").value = typeof savedIdeas.focus === "string" ? savedIdeas.focus.slice(0, 300) : "";
        renderIdeas();
      }
      updateJobCount();
      message(state.plan ? "Draft restored. Apply your saved edits to check the PDF." : "Draft restored. Build a version to refresh the PDF.");
    }
    if (!state.profile) {
      $("profile-name").textContent = "Import your source";
      $("profile-summary").textContent = "Start with a PDF or DOCX resume.";
    }
  } catch (error) {
    $("profile-name").textContent = "Server unavailable";
    $("profile-summary").textContent = "Start ResumeForge and refresh this page.";
    message(error.message, true);
  }
}

$("provider").addEventListener("change", updateProvider);
$("job-description").addEventListener("input", () => {
  updateJobCount();
  invalidateAnalysis(true);
  invalidateOutput();
});
$("profile-json").addEventListener("input", sourceChanged);
$("draft-mode").addEventListener("change", () => { $("grounded-options").hidden = $("draft-mode").value === "inspiration"; });
$("analyze-job").addEventListener("click", analyzePosting);
$("apply-examples").addEventListener("click", () => startRun(true));
for (const id of ["provider", "base-url", "model-name", "strategy"]) {
  $(id).addEventListener("input", () => { invalidateAnalysis(); invalidateOutput(); });
}
for (const id of ["keywords","edit-request","draft-mode","wording-policy","max-rounds","timeout","api-key-env"]) {
  $(id).addEventListener("input", () => invalidateOutput());
}
$("source-file").addEventListener("change", importFile);
$("test-model").addEventListener("click", testModel);
$("run-button").addEventListener("click", () => startRun());
$("apply-review").addEventListener("click", () => startRun(true));
$("apply-plan").addEventListener("click", () => startRun(true, false));
$("add-fact").addEventListener("click", addFact);
$("generate-ideas").addEventListener("click", generateIdeas);
$("idea-role").addEventListener("change", () => { inline("ideas-status", ""); renderIdeas(); });
$("save-draft").addEventListener("click", saveDraft);
$("clear-draft").addEventListener("click", () => {
  try { localStorage.removeItem(DRAFT_KEY); message("Saved draft cleared. The current workspace remains open until you refresh."); }
  catch (error) { message(`Could not clear the saved draft. ${error.message}`, true); }
});
$("profile-json").addEventListener("change", () => {
  try { renderProfileSummary(readProfile()); }
  catch (error) { message(error.message, true); }
});
$("plan-json").addEventListener("input", () => {
  // Any manual plan edit invalidates earlier confirmation. Review the exact new text.
  invalidateOutput(true);
  state.confirmed.clear();
  for (const checkbox of $("claims-list").querySelectorAll('input[type="checkbox"]')) checkbox.checked = false;
});
$("plan-json").addEventListener("change", () => {
  try { renderPlan(parseJSON("plan-json", "Tailoring plan")); }
  catch (error) { message(error.message, true); }
});
bootstrap();
