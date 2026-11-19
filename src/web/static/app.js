/**
 * AutoBot Sovereign v3 — Next-Gen 3D Cyber-Industrial Controller
 * Architecture: Clean Reactive Web UI · Web Audio Synthesizer · Real-time SSE
 */

(function () {
  "use strict";

  // ── Global State ──────────────────────────────────────────────────
  const state = {
    activeView: "mission",
    isRunning: false,
    currentNode: "idle",
    config: null,
    jobsOffset: 0,
    jobsLimit: 20,
    jobsTotal: 0,
    sseSource: null,
    audioEnabled: localStorage.getItem("autobot_audio") !== "muted",
  };

  // ── Authenticated HTTP Request Helper ─────────────────────────────
  function authedFetch(url, options = {}) {
    const token = localStorage.getItem("auth_token");
    options.headers = options.headers || {};
    if (token && !options.headers["Authorization"]) {
      options.headers["Authorization"] = `Bearer ${token}`;
    }
    return fetch(url, options);
  }

  // ── Web Audio Synthesizer (Zero External Dependencies) ─────────────
  let audioCtx = null;
  function getAudioContext() {
    if (!audioCtx && (window.AudioContext || window.webkitAudioContext)) {
      const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AudioCtxClass();
    }
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function playTone(freqStart, freqEnd, duration, type = "sine", gainVal = 0.04) {
    if (!state.audioEnabled) return;
    try {
      const ctx = getAudioContext();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freqStart, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(Math.max(20, freqEnd), ctx.currentTime + duration);
      gain.gain.setValueAtTime(gainVal, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + duration);
    } catch (e) {
      // Audio autoplay policy fallback
    }
  }

  const sfx = {
    click: () => playTone(800, 1200, 0.05, "sine", 0.03),
    launch: () => playTone(180, 880, 0.35, "triangle", 0.07),
    scan: () => playTone(600, 300, 0.2, "sawtooth", 0.03),
    success: () => playTone(440, 880, 0.25, "sine", 0.05),
    error: () => playTone(300, 150, 0.3, "sawtooth", 0.06),
  };

  // ── DOM Elements ──────────────────────────────────────────────────
  const els = {
    // Navigation
    navBtns: document.querySelectorAll(".nav-menu button"),
    views: document.querySelectorAll(".view-container"),
    topbarTitle: document.getElementById("topbar-title"),

    // Sidebar status
    statusDot: document.getElementById("status-indicator-dot"),
    statusText: document.getElementById("status-indicator-text"),
    providerBadge: document.getElementById("system-provider-badge"),

    // Audio toggle
    btnAudioToggle: document.getElementById("btn-audio-toggle"),
    audioStateText: document.getElementById("audio-state-text"),

    // Controls
    dryRunCheckbox: document.getElementById("dry-run-checkbox"),
    btnStart: document.getElementById("btn-start-run"),
    btnSearchChrome: document.getElementById("btn-search-chrome"),
    btnStop: document.getElementById("btn-stop-run"),
    btnForceIngest: document.getElementById("btn-force-ingest"),
    btnQuickUpload: document.getElementById("btn-quick-upload"),
    btnHeroLaunch: document.getElementById("btn-hero-launch"),
    btnHeroUpload: document.getElementById("btn-hero-upload"),

    // Mission Control metrics
    metricTotal: document.getElementById("metric-total"),
    metricApplied: document.getElementById("metric-applied"),
    metricDryRun: document.getElementById("metric-dry-run"),
    metricSkipped: document.getElementById("metric-skipped"),
    activeNodeIndicator: document.getElementById("active-node-indicator"),
    terminalFeed: document.getElementById("terminal-feed"),
    btnClearLogs: document.getElementById("btn-clear-logs"),

    // Pipeline nodes
    nodes: {
      search: document.getElementById("node-search"),
      filter: document.getElementById("node-filter"),
      evaluate: document.getElementById("node-evaluate"),
      apply: document.getElementById("node-apply"),
      record: document.getElementById("node-record"),
      advance: document.getElementById("node-advance"),
    },

    // Applications Board
    jobsSearch: document.getElementById("table-search"),
    jobsStatusFilter: document.getElementById("status-filter"),
    jobsRefreshBtn: document.getElementById("btn-refresh-jobs"),
    jobsTableBody: document.getElementById("jobs-table-body"),
    paginationInfo: document.getElementById("pagination-info"),
    btnPrevPage: document.getElementById("btn-prev-page"),
    btnNextPage: document.getElementById("btn-next-page"),

    // Profile View & Upload
    resumeDropzone: document.getElementById("resume-dropzone"),
    resumeFileInput: document.getElementById("resume-file-input"),
    uploadProgressBox: document.getElementById("upload-progress-box"),
    uploadProgressFill: document.getElementById("upload-progress-fill"),
    uploadStatusLabel: document.getElementById("upload-status-label"),
    uploadPctLabel: document.getElementById("upload-pct-label"),
    profileResumePath: document.getElementById("profile-resume-path"),
    profileTotalChunks: document.getElementById("profile-total-chunks"),
    profileStatusBadge: document.getElementById("profile-status-badge"),
    profileSectionsContainer: document.getElementById("profile-sections-container"),

    // Settings View
    cfgKeywords: document.getElementById("cfg-keywords"),
    cfgLocation: document.getElementById("cfg-location"),
    cfgMaxApps: document.getElementById("cfg-max-apps"),
    cfgMinScore: document.getElementById("cfg-min-score"),
    cfgScoreDisplay: document.getElementById("cfg-score-display"),
    cfgExpSalary: document.getElementById("cfg-exp-salary"),
    cfgYearsExp: document.getElementById("cfg-years-exp"),
    cfgWorkAuth: document.getElementById("cfg-work-auth"),
    cfgSponsorship: document.getElementById("cfg-sponsorship"),
    cfgNotice: document.getElementById("cfg-notice"),
    btnSaveSettings: document.getElementById("btn-save-settings"),

    // Browser Health Telemetry & Admin Controls
    browserPulseIndicator: document.getElementById("browser-pulse-indicator"),
    browserEngineText: document.getElementById("browser-engine-text"),
    browserProcStatus: document.getElementById("browser-proc-status"),
    browserFallbackBadge: document.getElementById("browser-fallback-badge"),
    adminBrowserConfigCard: document.getElementById("admin-browser-config-card"),
    cfgBrowserEngine: document.getElementById("cfg-browser-engine"),
    cfgExperimentalBrowserToggle: document.getElementById("cfg-experimental-browser-toggle"),
    infoActiveEngine: document.getElementById("info-active-engine"),
    infoProcStatus: document.getElementById("info-proc-status"),
    infoLastHealth: document.getElementById("info-last-health"),
    infoFallbackStatus: document.getElementById("info-fallback-status"),
    btnSaveBrowserConfig: document.getElementById("btn-save-browser-config"),
    browserConfigStatusMsg: document.getElementById("browser-config-status-msg"),

    // Toast
    toastContainer: document.getElementById("toast-container"),
  };

  // ── Toast Utility ─────────────────────────────────────────────────
  function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s ease-out";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // ── Navigation Tab Switching ──────────────────────────────────────
  function switchView(viewName) {
    state.activeView = viewName;
    sfx.click();

    els.views.forEach((v) => {
      if (v.id === `view-${viewName}`) {
        v.classList.add("active");
      } else {
        v.classList.remove("active");
      }
    });

    els.navBtns.forEach((btn) => {
      if (btn.getAttribute("data-view") === viewName) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    const titles = {
      mission: "Mission Control",
      applications: "Applications Tracker",
      profile: "Candidate Profile & Vector Memory",
      settings: "Agent Parameters",
      discovery: "Multi-Source Job Discovery",
      matching: "Deterministic Fit & Eligibility",
      packs: "Application Materials & Workflows",
      "apply-portals": "Application Portals & Direct Form Links",
    };
    els.topbarTitle.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" color="var(--primary)">
        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
        <polyline points="2 17 12 22 22 17"></polyline>
        <polyline points="2 12 12 17 22 12"></polyline>
      </svg>
      ${titles[viewName] || "Mission Control"}
    `;

    if (viewName === "applications") loadJobs();
    if (viewName === "apply-portals") loadApplyPortals();
    if (viewName === "profile") loadProfile();
    if (viewName === "settings") loadConfig();
    if (viewName === "discovery") {
      loadDiscoveryJobs();
      loadSourceHealth();
      loadKeywordExpansion();
    }
  }

  // ── LangGraph Active Node Visualizer ──────────────────────────────
  function updateGraphNode(nodeName) {
    const cleanNode = (nodeName || "").toLowerCase().trim();
    state.currentNode = cleanNode;

    Object.keys(els.nodes).forEach((key) => {
      if (key === cleanNode && cleanNode !== "idle") {
        els.nodes[key].classList.add("active");
      } else {
        els.nodes[key].classList.remove("active");
      }
    });

    if (cleanNode === "idle") {
      els.activeNodeIndicator.textContent = "STATUS: IDLE";
      els.activeNodeIndicator.className = "badge badge-dry-run";
    } else {
      els.activeNodeIndicator.textContent = `PIPELINE: ${cleanNode.toUpperCase()}`;
      els.activeNodeIndicator.className = "badge badge-applied";
    }
  }

  // ── Live Telemetry Feed (SSE) ─────────────────────────────────────
  function appendLog(level, message, timestamp) {
    const entry = document.createElement("div");
    entry.className = "log-entry";

    const timeStr = timestamp
      ? new Date(timestamp).toLocaleTimeString()
      : new Date().toLocaleTimeString();

    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    timeSpan.textContent = `[${timeStr}]`;

    const lvlSpan = document.createElement("span");
    lvlSpan.className = `log-level ${level.toLowerCase()}`;
    lvlSpan.textContent = `[${level.toUpperCase()}]`;

    const msgSpan = document.createElement("span");
    msgSpan.className = "log-msg";
    msgSpan.textContent = message;

    entry.appendChild(timeSpan);
    entry.appendChild(lvlSpan);
    entry.appendChild(msgSpan);

    els.terminalFeed.appendChild(entry);

    if (els.terminalFeed.childElementCount > 300) {
      els.terminalFeed.removeChild(els.terminalFeed.firstElementChild);
    }
    els.terminalFeed.scrollTop = els.terminalFeed.scrollHeight;
  }

  function initSSE() {
    if (state.sseSource) {
      state.sseSource.close();
    }

    state.sseSource = new EventSource("/api/events");

    state.sseSource.addEventListener("status", (e) => {
      try {
        const data = JSON.parse(e.data);
        setRunningState(data.state === "running");
        updateGraphNode(data.node);
      } catch (err) {
        console.error("SSE status parse error:", err);
      }
    });

    state.sseSource.addEventListener("log", (e) => {
      try {
        const data = JSON.parse(e.data);
        appendLog(data.level || "info", data.message || "", e.timestamp);
      } catch (err) {
        console.error("SSE log parse error:", err);
      }
    });

    state.sseSource.onerror = () => {
      els.statusDot.classList.remove("active");
      els.statusText.textContent = "Reconnecting...";
      setTimeout(initSSE, 4000);
    };
  }

  function setRunningState(isRunning) {
    state.isRunning = isRunning;
    if (isRunning) {
      els.statusDot.classList.add("active");
      els.statusText.textContent = "Agent Active";
      els.btnStart.disabled = true;
      els.btnStop.disabled = false;
      els.btnForceIngest.disabled = true;
      if (els.btnHeroLaunch) els.btnHeroLaunch.disabled = true;
    } else {
      els.statusDot.classList.remove("active");
      els.statusText.textContent = "Agent Idle";
      els.btnStart.disabled = false;
      els.btnStop.disabled = true;
      els.btnForceIngest.disabled = false;
      if (els.btnHeroLaunch) els.btnHeroLaunch.disabled = false;
      updateGraphNode("idle");
    }
  }

  // ── Mission Control & Stats Loader ────────────────────────────────
  async function loadStatus() {
    try {
      const res = await authedFetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      setRunningState(data.status === "running");
      updateGraphNode(data.current_node);

      if (data.llm_provider) {
        els.providerBadge.textContent = `${data.llm_provider.toUpperCase()}`;
      }

      if (data.stats) {
        els.metricTotal.textContent = data.stats.total ?? 0;
        els.metricApplied.textContent = data.stats.applied ?? 0;
        els.metricDryRun.textContent = data.stats.dry_run ?? 0;
        els.metricSkipped.textContent = data.stats.skipped ?? 0;
      }

      if (data.browser_health) {
        updateBrowserHealthUI(data.browser_health);
      }
    } catch (err) {
      console.error("Failed to load status:", err);
    }
  }

  // ── Browser Health Telemetry & Admin Controls ────────────────────
  function updateBrowserHealthUI(health) {
    if (!health) return;

    if (els.browserEngineText) {
      const isObscura = health.active_engine === "obscura";
      els.browserEngineText.textContent = isObscura ? "Obscura v0.2.7 (Exp)" : "Chromium (Default)";
      els.browserEngineText.style.color = isObscura ? "var(--cyan)" : "var(--text-main)";
    }

    if (els.browserProcStatus) {
      els.browserProcStatus.textContent = (health.process_status || "ready").toUpperCase();
    }

    if (els.browserPulseIndicator) {
      if (health.fallback_active) {
        els.browserPulseIndicator.classList.add("fallback");
      } else {
        els.browserPulseIndicator.classList.remove("fallback");
      }
    }

    if (els.browserFallbackBadge) {
      if (health.fallback_active) {
        els.browserFallbackBadge.className = "badge-fallback-triggered";
        els.browserFallbackBadge.textContent = "Fallback: ACTIVE";
      } else {
        els.browserFallbackBadge.className = "badge-fallback-ok";
        els.browserFallbackBadge.textContent = "Fallback: Standby";
      }
    }

    // Admin Panel Controls
    if (els.adminBrowserConfigCard) {
      if (health.is_admin) {
        els.adminBrowserConfigCard.style.display = "block";
        if (els.cfgBrowserEngine) els.cfgBrowserEngine.value = health.active_engine || "chromium";
        if (els.cfgExperimentalBrowserToggle) {
          els.cfgExperimentalBrowserToggle.checked = Boolean(health.experimental_backend?.enabled);
        }
        if (els.infoActiveEngine) els.infoActiveEngine.textContent = health.active_engine || "chromium";
        if (els.infoProcStatus) els.infoProcStatus.textContent = health.process_status || "ready";
        if (els.infoLastHealth && health.last_health_check) {
          const d = new Date(health.last_health_check);
          els.infoLastHealth.textContent = d.toLocaleTimeString();
        }
        if (els.infoFallbackStatus) els.infoFallbackStatus.textContent = health.fallback_status || "standby";

        // Prevent switching mid-application
        const isLocked = Boolean(health.active_application);
        if (els.cfgBrowserEngine) els.cfgBrowserEngine.disabled = isLocked;
        if (els.cfgExperimentalBrowserToggle) els.cfgExperimentalBrowserToggle.disabled = isLocked;
        if (els.btnSaveBrowserConfig) {
          els.btnSaveBrowserConfig.disabled = isLocked;
          if (isLocked) {
            els.btnSaveBrowserConfig.title = "Engine switching locked during active application";
          } else {
            els.btnSaveBrowserConfig.title = "";
          }
        }
      } else {
        els.adminBrowserConfigCard.style.display = "none";
      }
    }
  }

  async function saveBrowserConfiguration() {
    if (!els.cfgBrowserEngine || !els.cfgExperimentalBrowserToggle) return;
    const requestedEngine = els.cfgBrowserEngine.value;
    const experimentalEnabled = els.cfgExperimentalBrowserToggle.checked;

    if (requestedEngine === "obscura" && !experimentalEnabled) {
      showToast("Cannot select Obscura while experimental mode is disabled.", "error");
      return;
    }

    try {
      const res = await authedFetch("/api/browser/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engine: requestedEngine,
          experimental_enabled: experimentalEnabled,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Failed to update browser configuration", "error");
        return;
      }
      showToast("Browser engine configuration updated successfully!");
      if (els.browserConfigStatusMsg) {
        els.browserConfigStatusMsg.style.display = "inline";
        setTimeout(() => {
          if (els.browserConfigStatusMsg) els.browserConfigStatusMsg.style.display = "none";
        }, 3000);
      }
      updateBrowserHealthUI(data.browser_health);
    } catch (err) {
      showToast(`Network error: ${err.message}`, "error");
    }
  }

  // ── Agent Run Actions ─────────────────────────────────────────────
  async function startAgentRun(forceIngest = false) {
    const dryRun = els.dryRunCheckbox.checked;
    sfx.launch();
    try {
      setRunningState(true);
      const res = await authedFetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dry_run: dryRun, force_ingest: forceIngest }),
      });
      const data = await res.json();

      if (res.ok) {
        showToast(forceIngest ? "Profile sync & agent commenced" : "Sovereign run initiated");
        appendLog("info", `Initiated run (dry_run=${dryRun}, force_ingest=${forceIngest})`);
      } else {
        showToast(data.error || "Failed to start run", "error");
        setRunningState(false);
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, "error");
      setRunningState(false);
    }
  }

  async function stopAgentRun() {
    sfx.click();
    try {
      const res = await authedFetch("/api/stop", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        showToast("Agent run cancelled");
        setRunningState(false);
      } else {
        showToast(data.error || "Could not stop run", "error");
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, "error");
    }
  }

  async function startChromeSearch() {
    sfx.launch();
    try {
      setRunningState(true);
      appendLog("info", "Opening real Google Chrome to search keywords directly on LinkedIn...");
      const res = await authedFetch("/api/search/live", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok) {
        showToast("Direct Google Chrome search started!");
      } else {
        showToast(data.error || "Failed to start Chrome search", "error");
        setRunningState(false);
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, "error");
      setRunningState(false);
    }
  }

  // ── Applications Hologrid ─────────────────────────────────────────
  async function loadJobs() {
    const query = encodeURIComponent(els.jobsSearch.value.trim());
    const status = encodeURIComponent(els.jobsStatusFilter.value.trim());
    const limit = state.jobsLimit;
    const offset = state.jobsOffset;

    try {
      const res = await authedFetch(`/api/jobs?limit=${limit}&offset=${offset}&status=${status}&q=${query}`);
      if (!res.ok) return;
      const data = await res.json();

      state.jobsTotal = data.total;
      renderJobsTable(data.jobs || []);
      updatePaginationControls();
    } catch (err) {
      console.error("Failed to fetch jobs:", err);
    }
  }

  function renderJobsTable(jobs) {
    els.jobsTableBody.innerHTML = "";

    if (!jobs || jobs.length === 0) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td colspan="9" style="text-align: center; color: var(--text-dim); padding: 45px;">
          No matching application records in SQLite database.
        </td>
      `;
      els.jobsTableBody.appendChild(row);
      return;
    }

    jobs.forEach((job) => {
      const row = document.createElement("tr");

      const st = (job.status || "unknown").toLowerCase();
      let badgeClass = "badge-skipped";
      if (st === "applied" || st === "submitted") badgeClass = "badge-applied";
      else if (st === "dry_run" || st === "prepared") badgeClass = "badge-dry-run";
      else if (st === "failed" || st === "rejected") badgeClass = "badge-failed";
      else if (st === "interview" || st === "offer") badgeClass = "badge-applied";
      else if (st === "discovered" || st === "evaluated") badgeClass = "badge-dry-run";

      const score = Math.round((job.match_score || 0) * 100);
      let pillClass = "low";
      if (score >= 80) pillClass = "high";
      else if (score >= 60) pillClass = "mid";

      const rawTime = job.applied_at || job.timestamp;
      const timeStr = rawTime
        ? new Date(rawTime).toLocaleString(undefined, {
            dateStyle: "short",
            timeStyle: "short",
          })
        : "—";

      row.innerHTML = `
        <td style="font-family: var(--font-mono); color: var(--text-dim); font-size: 11px;">#${job.id}</td>
        <td style="font-weight: 700;">
          <a href="${job.url || job.job_url || '#'}" target="_blank" rel="noopener noreferrer" style="color: #fff; text-decoration: none;">
            ${escapeHtml(job.job_title || "Untitled Role")}
          </a>
        </td>
        <td style="color: var(--cyan); font-weight: 600;">${escapeHtml(job.company || "Unknown")}</td>
        <td style="color: var(--text-muted);">${escapeHtml(job.location || "Remote")}</td>
        <td>
          <span style="font-size: 11px; font-weight: 600; color: var(--text-muted);">
            ${escapeHtml(job.apply_type || "Easy Apply")}
          </span>
        </td>
        <td>
          <span class="match-pill ${pillClass}">${score}% FIT</span>
        </td>
        <td>
          <span class="badge ${badgeClass}">${escapeHtml(job.status || "")}</span>
        </td>
        <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-dim);">
          ${timeStr}
        </td>
        <td>
          <select onchange="window.updateJobStatus('${job.job_id || job.id}', this.value)" style="background: rgba(0,0,0,0.5); color: var(--text-main); border: 1px solid var(--border); border-radius: 4px; font-size: 11px; padding: 3px 6px; cursor: pointer;">
            <option value="">Move status...</option>
            <option value="interview">Move to Interview</option>
            <option value="offer">Move to Offer</option>
            <option value="rejected">Move to Rejected</option>
            <option value="submitted">Move to Submitted</option>
          </select>
        </td>
      `;
      els.jobsTableBody.appendChild(row);
    });
  }

  function updatePaginationControls() {
    const start = state.jobsTotal === 0 ? 0 : state.jobsOffset + 1;
    const end = Math.min(state.jobsOffset + state.jobsLimit, state.jobsTotal);
    els.paginationInfo.textContent = `Showing ${start} to ${end} of ${state.jobsTotal} applications`;
    els.btnPrevPage.disabled = state.jobsOffset === 0;
    els.btnNextPage.disabled = end >= state.jobsTotal;
  }

  // ── Candidate Profile & 3D Laser Upload ───────────────────────────
  async function loadProfile() {
    try {
      const res = await authedFetch("/api/profile");
      if (!res.ok) return;
      const data = await res.json();

      els.profileResumePath.textContent = data.path || "data/resume/resume.pdf";
      els.profileTotalChunks.textContent = data.total_chunks || 0;

      if (data.found) {
        els.profileStatusBadge.textContent = "VERIFIED INGESTION";
        els.profileStatusBadge.className = "badge badge-applied";
      } else {
        els.profileStatusBadge.textContent = "AGILE PROFILE (NO RESUME)";
        els.profileStatusBadge.className = "badge badge-dry-run";
      }

      renderProfileSections(data.sections || {});

      // Load and populate Candidate Profile form fields
      try {
        const profRes = await authedFetch("/api/candidate/profile");
        if (profRes.ok) {
          const prof = await profRes.json();
          const candName = document.getElementById("cand-full-name");
          if (candName) candName.value = prof.full_name || "";
          const candEmail = document.getElementById("cand-email");
          if (candEmail) candEmail.value = prof.email || "";
          const candPhone = document.getElementById("cand-phone");
          if (candPhone) candPhone.value = prof.phone || "";
          const candLoc = document.getElementById("cand-location");
          if (candLoc) candLoc.value = prof.location || "";
          const candHeadline = document.getElementById("cand-headline");
          if (candHeadline) candHeadline.value = prof.headline || "";
          const candTech = document.getElementById("cand-tech-skills");
          if (candTech) candTech.value = (prof.technical_skills || []).join(", ");
          const candAch = document.getElementById("cand-achievements");
          if (candAch) {
            const achs = prof.achievements || [];
            candAch.value = achs.map(a => typeof a === "object" ? (a.title || a.description || "") : a).join("\n");
          }
        }
      } catch (pe) {
        console.debug("Could not load candidate profile:", pe);
      }

      // Load and populate Job Preferences form fields
      try {
        const prefRes = await authedFetch("/api/candidate/preferences");
        if (prefRes.ok) {
          const pref = await prefRes.json();
          const targetRoles = document.getElementById("pref-target-roles");
          if (targetRoles) targetRoles.value = (pref.target_roles || []).join(", ");
          const empType = document.getElementById("pref-emp-type");
          if (empType) {
            const types = pref.employment_types || ["full-time"];
            if (types.includes("full-time") && types.includes("internship")) empType.value = "both";
            else if (types.includes("internship")) empType.value = "internship";
            else empType.value = "full-time";
          }
          const expLvl = document.getElementById("pref-experience-level");
          if (expLvl) expLvl.value = pref.experience_level || "mid-senior";
          const arr = document.getElementById("pref-work-arrangement");
          if (arr) arr.value = pref.work_arrangement || "remote";
          const minSal = document.getElementById("pref-min-salary");
          if (minSal) minSal.value = pref.min_salary || 0;
          const eligCountries = document.getElementById("pref-eligible-countries");
          if (eligCountries) eligCountries.value = (pref.eligible_countries || []).join(", ");
          const minFit = document.getElementById("pref-min-fit");
          if (minFit) minFit.value = pref.min_fit_threshold || 60;
        }
      } catch (pe) {
        console.debug("Could not load candidate preferences:", pe);
      }
    } catch (err) {
      console.error("Failed to load profile:", err);
    }
  }

  function renderProfileSections(sections) {
    els.profileSectionsContainer.innerHTML = "";
    const keys = Object.keys(sections);

    if (keys.length === 0) {
      els.profileSectionsContainer.innerHTML = `
        <div class="profile-card" style="text-align: center; color: var(--text-dim); padding: 35px;">
          No extracted resume chunks found. You can upload a resume above, or click "Start Run" to let AutoBot proceed with configuration answers!
        </div>
      `;
      return;
    }

    keys.forEach((sectionKey) => {
      const card = document.createElement("div");
      card.className = "profile-card";

      const title = sectionKey.replace(/_/g, " ").toUpperCase();
      const chunks = sections[sectionKey] || [];

      let contentHtml = "";
      if (sectionKey === "skills") {
        contentHtml = `<div class="tag-cloud">`;
        chunks.forEach((chunk) => {
          chunk.split(/[,•|\n]+/).forEach((item) => {
            const clean = item.trim();
            if (clean.length > 1 && clean.length < 40) {
              contentHtml += `<span class="skill-tag">${escapeHtml(clean)}</span>`;
            }
          });
        });
        contentHtml += `</div>`;
      } else {
        chunks.forEach((chunk) => {
          contentHtml += `<div class="chunk-card">${escapeHtml(chunk)}</div>`;
        });
      }

      card.innerHTML = `
        <div class="profile-card-header">
          <div class="profile-card-title">${escapeHtml(title)}</div>
          <span class="badge badge-dry-run">${chunks.length} ${chunks.length === 1 ? 'chunk' : 'chunks'}</span>
        </div>
        ${contentHtml}
      `;
      els.profileSectionsContainer.appendChild(card);
    });
  }

  // ── Document & Resume Upload ─────────────────────────────────────
  async function uploadResumeFile(file) {
    if (!file) return;

    const allowed = [".pdf", ".docx", ".doc", ".txt"];
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      showToast(`Unsupported format '${ext}'. Please upload PDF, DOCX, or TXT.`, "error");
      sfx.error();
      return;
    }

    if (file.size > 15 * 1024 * 1024) {
      showToast("File size exceeds 15MB limit.", "error");
      sfx.error();
      return;
    }

    sfx.scan();
    if (els.resumeDropzone) els.resumeDropzone.classList.add("scanning");

    const formData = new FormData();
    formData.append("file", file);

    if (els.uploadProgressBox) {
      els.uploadProgressBox.style.display = "block";
      els.uploadProgressFill.style.width = "25%";
      els.uploadPctLabel.textContent = "25%";
      els.uploadStatusLabel.textContent = `Streaming '${file.name}' to neural ingestion pipeline...`;
    }

    try {
      setTimeout(() => {
        if (els.uploadProgressFill) {
          els.uploadProgressFill.style.width = "70%";
          els.uploadPctLabel.textContent = "70%";
          els.uploadStatusLabel.textContent = "Extracting semantic boundaries and vector embeddings...";
        }
      }, 350);

      const res = await authedFetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (res.ok) {
        sfx.success();
        if (els.uploadProgressFill) {
          els.uploadProgressFill.style.width = "100%";
          els.uploadPctLabel.textContent = "100%";
          els.uploadStatusLabel.textContent = "Document indexed into Qdrant vector memory!";
        }

        showToast(`Document uploaded: ${file.name} (${data.chunks_count || 0} chunks)`);
        appendLog("success", `Candidate resume uploaded: '${file.name}' (${data.chunks_count || 0} semantic chunks extracted)`);

        setTimeout(() => {
          if (els.resumeDropzone) els.resumeDropzone.classList.remove("scanning");
          if (els.uploadProgressBox) {
            els.uploadProgressBox.style.display = "none";
            els.uploadProgressFill.style.width = "0%";
          }
          loadProfile();
          loadStatus();
        }, 1200);
      } else {
        sfx.error();
        if (els.resumeDropzone) els.resumeDropzone.classList.remove("scanning");
        showToast(data.error || "Upload failed", "error");
        if (els.uploadProgressBox) els.uploadProgressBox.style.display = "none";
      }
    } catch (err) {
      sfx.error();
      if (els.resumeDropzone) els.resumeDropzone.classList.remove("scanning");
      showToast(`Upload error: ${err.message}`, "error");
      if (els.uploadProgressBox) els.uploadProgressBox.style.display = "none";
    }
  }

  // ── Agent Configuration ───────────────────────────────────────────
  async function loadConfig() {
    try {
      const res = await authedFetch("/api/config");
      if (!res.ok) return;
      state.config = await res.json();
      populateConfigForm(state.config);
    } catch (err) {
      console.error("Failed to load config:", err);
    }
  }

  function populateConfigForm(cfg) {
    if (!cfg) return;

    const kw = cfg.search?.keywords || [];
    els.cfgKeywords.value = Array.isArray(kw) ? kw.join(", ") : kw;
    els.cfgLocation.value = cfg.search?.location || "India / Remote";
    els.cfgMaxApps.value = cfg.apply?.max_applications || cfg.execution?.max_applications || 10;

    const minScore = cfg.apply?.min_match_score ?? cfg.matching?.min_match_score ?? 0.70;
    els.cfgMinScore.value = minScore;
    els.cfgScoreDisplay.textContent = Number(minScore).toFixed(2);

    const answers = cfg.apply?.answers || cfg.screening || {};
    els.cfgExpSalary.value = answers.expected_salary || "15 LPA";
    els.cfgYearsExp.value = answers.years_of_experience || 4;
    els.cfgWorkAuth.value = answers.work_authorization || answers.legally_authorized || "Yes";
    els.cfgSponsorship.value = String(answers.sponsorship_required || answers.require_sponsorship || false);
    els.cfgNotice.value = answers.notice_period || "30 days";
  }

  async function saveConfig() {
    if (!state.config) state.config = {};
    sfx.click();

    const keywordsArr = els.cfgKeywords.value
      .split(",")
      .map((k) => k.trim())
      .filter((k) => k.length > 0);

    state.config.search = {
      ...(state.config.search || {}),
      keywords: keywordsArr,
      location: els.cfgLocation.value.trim(),
    };

    state.config.apply = {
      ...(state.config.apply || {}),
      max_applications: parseInt(els.cfgMaxApps.value, 10) || 10,
      min_match_score: parseFloat(els.cfgMinScore.value) || 0.70,
      answers: {
        ...((state.config.apply && state.config.apply.answers) || {}),
        expected_salary: els.cfgExpSalary.value.trim(),
        years_of_experience: parseInt(els.cfgYearsExp.value, 10) || 4,
        work_authorization: els.cfgWorkAuth.value.trim(),
        sponsorship_required: els.cfgSponsorship.value === "true" ? "Yes" : "No",
        notice_period: els.cfgNotice.value.trim(),
      },
    };

    try {
      const res = await authedFetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.config),
      });

      if (res.ok) {
        sfx.success();
        showToast("Configuration parameters synchronized!");
        appendLog("success", "Updated agent search and screening thresholds.");
      } else {
        const data = await res.json();
        showToast(data.error || "Failed to update configuration", "error");
      }
    } catch (err) {
      showToast(`Save error: ${err.message}`, "error");
    }
  }



  // ── Helper Utilities ──────────────────────────────────────────────
  function escapeHtml(str) {
    if (typeof str !== "string") return str ?? "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ── Event Handlers Registration ───────────────────────────────────
  function initListeners() {
    // Navigation
    els.navBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const view = btn.getAttribute("data-view");
        if (view) switchView(view);
      });
    });

    // Audio Toggle
    if (els.btnAudioToggle) {
      els.btnAudioToggle.addEventListener("click", () => {
        state.audioEnabled = !state.audioEnabled;
        localStorage.setItem("autobot_audio", state.audioEnabled ? "enabled" : "muted");
        els.audioStateText.textContent = state.audioEnabled ? "AUDIO ON" : "MUTED";
        if (state.audioEnabled) sfx.click();
        showToast(state.audioEnabled ? "Tactile audio feedback enabled" : "Audio muted");
      });
    }

    // Run actions
    els.btnStart.addEventListener("click", () => startAgentRun(false));
    if (els.btnSearchChrome) {
      els.btnSearchChrome.addEventListener("click", () => startChromeSearch());
    }
    els.btnForceIngest.addEventListener("click", () => startAgentRun(true));
    els.btnStop.addEventListener("click", () => stopAgentRun());

    if (els.btnHeroLaunch) {
      els.btnHeroLaunch.addEventListener("click", () => startAgentRun(false));
    }

    // Terminal clear
    els.btnClearLogs.addEventListener("click", () => {
      sfx.click();
      els.terminalFeed.innerHTML = "";
      appendLog("info", "Terminal telemetry log buffer cleared.");
    });

    // Applications board search & filter
    let debounceTimer;
    els.jobsSearch.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.jobsOffset = 0;
        loadJobs();
      }, 300);
    });

    els.jobsStatusFilter.addEventListener("change", () => {
      state.jobsOffset = 0;
      loadJobs();
    });

    els.jobsRefreshBtn.addEventListener("click", () => {
      sfx.click();
      loadJobs();
    });

    els.btnPrevPage.addEventListener("click", () => {
      sfx.click();
      if (state.jobsOffset > 0) {
        state.jobsOffset = Math.max(0, state.jobsOffset - state.jobsLimit);
        loadJobs();
      }
    });

    els.btnNextPage.addEventListener("click", () => {
      sfx.click();
      if (state.jobsOffset + state.jobsLimit < state.jobsTotal) {
        state.jobsOffset += state.jobsLimit;
        loadJobs();
      }
    });

    // Settings slider
    els.cfgMinScore.addEventListener("input", (e) => {
      els.cfgScoreDisplay.textContent = Number(e.target.value).toFixed(2);
    });

    // Settings save
    els.btnSaveSettings.addEventListener("click", (e) => {
      e.preventDefault();
      saveConfig();
    });

    // Apply Portals category tabs
    document.querySelectorAll(".platform-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".platform-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        portalsState.category = tab.getAttribute("data-category") || "all";
        loadApplyPortals();
      });
    });

    // Apply Portals search input
    const portalSearch = document.getElementById("portals-search-input");
    if (portalSearch) {
      let pDebounce;
      portalSearch.addEventListener("input", () => {
        clearTimeout(pDebounce);
        pDebounce = setTimeout(() => {
          portalsState.search = portalSearch.value.trim();
          loadApplyPortals();
        }, 300);
      });
    }

    // Refresh portals button
    const btnRefPortals = document.getElementById("btn-refresh-portals");
    if (btnRefPortals) {
      btnRefPortals.addEventListener("click", () => {
        if (state.audioEnabled && sfx) sfx.click();
        loadApplyPortals();
      });
    }

    // Quick Chrome Search button in portals view
    const btnQuickChrome = document.getElementById("btn-quick-chrome-search");
    if (btnQuickChrome) {
      btnQuickChrome.addEventListener("click", () => {
        if (state.audioEnabled && sfx) sfx.click();
        startChromeSearch();
      });
    }

    // Job Description Modal Controls
    const modalCloseBtn = document.getElementById("modal-close-btn");
    const modalCancelBtn = document.getElementById("modal-cancel-btn");
    const modalOverlay = document.getElementById("job-modal-overlay");
    if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeJobModal);
    if (modalCancelBtn) modalCancelBtn.addEventListener("click", closeJobModal);
    if (modalOverlay) {
      modalOverlay.addEventListener("click", (e) => {
        if (e.target === modalOverlay) closeJobModal();
      });
    }

    if (els.btnSaveBrowserConfig) {
      els.btnSaveBrowserConfig.addEventListener("click", (e) => {
        e.preventDefault();
        saveBrowserConfiguration();
      });
    }

    // Resume Dropzone & Upload triggers
    if (els.btnQuickUpload) {
      els.btnQuickUpload.addEventListener("click", () => {
        switchView("profile");
        if (els.resumeFileInput) els.resumeFileInput.click();
      });
    }

    if (els.btnHeroUpload) {
      els.btnHeroUpload.addEventListener("click", () => {
        switchView("profile");
        if (els.resumeFileInput) els.resumeFileInput.click();
      });
    }

    if (els.resumeDropzone) {
      els.resumeDropzone.addEventListener("click", (e) => {
        if (e.target.tagName !== "INPUT" && els.resumeFileInput) {
          els.resumeFileInput.click();
        }
      });

      ["dragenter", "dragover"].forEach((eventName) => {
        els.resumeDropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          els.resumeDropzone.classList.add("dragover");
        });
      });

      ["dragleave", "drop"].forEach((eventName) => {
        els.resumeDropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          els.resumeDropzone.classList.remove("dragover");
        });
      });

      els.resumeDropzone.addEventListener("drop", (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
          uploadResumeFile(files[0]);
        }
      });
    }

    if (els.resumeFileInput) {
      els.resumeFileInput.addEventListener("change", (e) => {
        const files = e.target.files;
        if (files && files.length > 0) {
          uploadResumeFile(files[0]);
        }
      });
    }

    // ── Milestone 2 Candidate Profile & Preferences Save ────────────
    const btnSaveCandProfile = document.getElementById("btn-save-candidate-profile");
    if (btnSaveCandProfile) {
      btnSaveCandProfile.addEventListener("click", async () => {
        sfx.click();
        const fullName = (document.getElementById("cand-full-name")?.value || "").trim();
        const email = (document.getElementById("cand-email")?.value || "").trim();
        const phone = (document.getElementById("cand-phone")?.value || "").trim();
        const location = (document.getElementById("cand-location")?.value || "").trim();
        const headline = (document.getElementById("cand-headline")?.value || "").trim();
        const techSkills = (document.getElementById("cand-tech-skills")?.value || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        const achievements = (document.getElementById("cand-achievements")?.value || "")
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);

        const targetRoles = (document.getElementById("pref-target-roles")?.value || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        const empTypeVal = document.getElementById("pref-emp-type")?.value || "full-time";
        const empTypes = empTypeVal === "both" ? ["full-time", "internship"] : [empTypeVal];
        const expLevel = document.getElementById("pref-experience-level")?.value || "mid-senior";
        const workArr = document.getElementById("pref-work-arrangement")?.value || "remote";
        const minSalary = parseFloat(document.getElementById("pref-min-salary")?.value || "0") || 0;
        const eligCountries = (document.getElementById("pref-eligible-countries")?.value || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        const minFit = parseFloat(document.getElementById("pref-min-fit")?.value || "60") || 60;

        try {
          const profRes = await authedFetch("/api/candidate/profile", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              full_name: fullName,
              email: email,
              phone: phone,
              location: location,
              headline: headline,
              technical_skills: techSkills,
              achievements: achievements,
            }),
          });

          const prefRes = await authedFetch("/api/candidate/preferences", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              target_roles: targetRoles,
              employment_types: empTypes,
              experience_level: expLevel,
              work_arrangement: workArr,
              min_salary: minSalary,
              eligible_countries: eligCountries,
              min_fit_threshold: minFit,
            }),
          });

          if (profRes.ok && prefRes.ok) {
            sfx.success();
            showToast("Candidate profile and preferences saved successfully!");
            loadProfile();
          } else {
            sfx.error();
            showToast("Failed to save some profile/preference settings", "error");
          }
        } catch (err) {
          sfx.error();
          showToast(`Save error: ${err.message}`, "error");
        }
      });
    }

    // ── Milestone 7 Discovery, Matching & Privacy Bindings ───────────
    const btnTriggerDiscovery = document.getElementById("btn-trigger-discovery");
    if (btnTriggerDiscovery) {
      btnTriggerDiscovery.addEventListener("click", async () => {
        sfx.launch();
        showToast("Starting multi-source job discovery...");
        try {
          const res = await authedFetch("/api/discovery/run", { method: "POST" });
          const data = await res.json();
          if (data.success) {
            showToast(`Discovered & normalized ${data.discovered_count} vacancies!`);
            loadDiscoveryJobs();
          } else {
            showToast(data.error || "Discovery failed", "error");
          }
        } catch (err) {
          showToast(`Discovery error: ${err.message}`, "error");
        }
      });
    }

    const btnSubmitImport = document.getElementById("btn-submit-import");
    if (btnSubmitImport) {
      btnSubmitImport.addEventListener("click", async () => {
        const title = document.getElementById("import-job-title").value.trim();
        const company = document.getElementById("import-job-company").value.trim();
        const location = document.getElementById("import-job-location").value.trim();
        const url = document.getElementById("import-job-url").value.trim();
        const description = document.getElementById("import-job-desc").value.trim();

        if (!title || !company || !description) {
          showToast("Please provide title, company, and description", "error");
          return;
        }

        sfx.click();
        try {
          const res = await authedFetch("/api/discovery/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, company, location, application_url: url, description }),
          });
          const data = await res.json();
          if (data.success) {
            sfx.success();
            showToast("Job description imported successfully!");
            document.getElementById("import-job-title").value = "";
            document.getElementById("import-job-company").value = "";
            document.getElementById("import-job-location").value = "";
            document.getElementById("import-job-url").value = "";
            document.getElementById("import-job-desc").value = "";
            loadDiscoveryJobs();
          } else {
            showToast(data.error || "Import failed", "error");
          }
        } catch (err) {
          showToast(`Error: ${err.message}`, "error");
        }
      });
    }

    const btnRefreshSources = document.getElementById("btn-refresh-sources");
    if (btnRefreshSources) {
      btnRefreshSources.addEventListener("click", () => {
        loadSourceHealth();
      });
    }

    const btnLoadPersonalized = document.getElementById("btn-load-personalized");
    if (btnLoadPersonalized) {
      btnLoadPersonalized.addEventListener("click", () => {
        loadPersonalizedMatches();
      });
    }

    ["discovery-filter-search", "discovery-filter-status", "discovery-filter-score", "discovery-filter-type", "discovery-filter-workplace"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener(el.tagName === "INPUT" ? "input" : "change", () => {
          loadDiscoveryJobs();
        });
      }
    });
  }

  // ── Clipboard & Tracker Helper ────────────────────────────────────
  window.copyToClipboard = function (text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast("Copied to clipboard!");
      }).catch(() => {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  };

  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      showToast("Copied to clipboard!");
    } catch (e) {
      showToast("Failed to copy", "error");
    }
    ta.remove();
  }

  window.updateJobStatus = async function (jobId, newStatus) {
    if (!newStatus) return;
    try {
      const res = await authedFetch("/api/tracker/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, status: newStatus }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Status updated to ${newStatus}`);
        loadJobs();
        loadStatus();
      } else {
        showToast(data.error || "Failed to update status", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    }
  };

  // ── Discovery, Matching, & Workflow Helpers ───────────────────────
  async function loadSourceHealth() {
    const container = document.getElementById("sources-health-container");
    if (!container) return;
    try {
      const res = await authedFetch("/api/discovery/sources/health");
      const data = await res.json();
      const sources = data.sources || [];
      if (!sources.length) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No ATS sources configured.</div>';
        return;
      }
      container.innerHTML = "";
      sources.forEach((s) => {
        const card = document.createElement("div");
        const statusBadge = s.status === "active" ? '<span class="badge badge-normal" style="background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid #10b981;">Active</span>' : '<span class="badge badge-normal" style="background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid #ef4444;">Error</span>';
        card.style.cssText = "background: rgba(255,255,255,0.02); border: 1px solid var(--border); border-radius: 6px; padding: 10px;";
        card.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <strong style="font-size: 12px; color: var(--text-main);">${escapeHtml(s.name)}</strong>
            ${statusBadge}
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 3px;">
            ATS: <span style="color: var(--primary);">${escapeHtml(s.source_type)}</span> (${escapeHtml(s.board_slug)})
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 3px;">
            Vacancies: <strong style="color: var(--text-main);">${s.active_jobs_count} active</strong> ${s.expired_jobs_count ? `(${s.expired_jobs_count} expired)` : ''}
          </div>
          <div style="font-size: 10px; color: var(--text-muted);">
            Last Synced: ${escapeHtml(s.last_synced_at ? (s.last_synced_at.includes('T') ? s.last_synced_at.split('T')[0] + ' ' + s.last_synced_at.split('T')[1].slice(0,5) : s.last_synced_at) : 'Never')}
          </div>
          ${s.last_error ? `<div style="font-size: 10px; color: #ef4444; margin-top: 4px;">${escapeHtml(s.last_error.slice(0, 80))}</div>` : ''}
        `;
        container.appendChild(card);
      });
    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; font-size: 11px;">Error loading ATS sources: ${err.message}</div>`;
    }
  }

  async function loadKeywordExpansion() {
    const container = document.getElementById("keyword-expansion-container");
    if (!container) return;
    try {
      const res = await authedFetch("/api/matching/expand-keywords");
      const data = await res.json();
      const keywords = data.expanded_keywords || [];
      const explanations = data.explanations || [];
      if (!keywords.length) {
        container.innerHTML = '<div>No skills configured. Add skills in Candidate Profile.</div>';
        return;
      }
      const tags = keywords.map(k => `<span class="badge" style="background: rgba(99,102,241,0.15); color: #818cf8; border: 1px solid rgba(99,102,241,0.3); font-size: 11px; margin-right: 4px; margin-bottom: 4px; display: inline-block;">${escapeHtml(k)}</span>`).join('');
      const explCount = explanations.length;
      container.innerHTML = `
        <div style="margin-bottom: 8px;">${tags}</div>
        <div style="font-size: 11px; color: var(--text-muted);">
          Derived ${keywords.length} expanded industry terms (${explCount} synonym/framework mappings) from candidate skills: <em>${escapeHtml((data.original_skills || []).join(', '))}</em>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; font-size: 11px;">Failed to load keyword expansion: ${err.message}</div>`;
    }
  }

  async function loadPersonalizedMatches() {
    const container = document.getElementById("discovery-jobs-container");
    if (!container) return;
    container.innerHTML = '<div style="color: var(--primary); font-size: 13px;">Searching personalized jobs matching candidate profile...</div>';
    try {
      const res = await authedFetch("/api/discovery/personalized");
      const data = await res.json();
      renderDiscoveredJobsList(data.jobs || []);
      const countEl = document.getElementById("discovery-job-count");
      if (countEl) countEl.innerText = `${(data.jobs || []).length} personalized matches`;
    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; font-size: 12px;">Error loading personalized matches: ${err.message}</div>`;
    }
  }

  function renderDiscoveredJobsList(jobs) {
    const container = document.getElementById("discovery-jobs-container");
    if (!container) return;
    if (!jobs.length) {
      container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">No matching jobs found with current filters.</div>';
      return;
    }
    container.innerHTML = "";
    jobs.forEach((j) => {
      const item = document.createElement("div");
      const isExpired = j.status === "expired";
      const statusBadge = isExpired
        ? '<span class="badge" style="background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid #ef4444; font-size: 10px;">Expired</span>'
        : '<span class="badge" style="background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid #10b981; font-size: 10px;">Active</span>';
      
      const workplaceBadge = `<span class="badge badge-dry-run" style="font-size: 10px;">${escapeHtml(j.workplace_type || (j.is_remote ? 'remote' : 'on-site'))}</span>`;
      const empBadge = `<span class="badge badge-dry-run" style="font-size: 10px;">${escapeHtml(j.employment_type || "full-time")}</span>`;
      
      let fitScoreBadge = '';
      if (j.fit_score != null) {
        const score = Number(j.fit_score);
        const scoreColor = score >= 75 ? '#10b981' : (score >= 60 ? '#f59e0b' : '#94a3b8');
        fitScoreBadge = `<span class="badge" style="background: rgba(255,255,255,0.05); color: ${scoreColor}; border: 1px solid ${scoreColor}; font-weight: 600; font-size: 11px;">Fit: ${score.toFixed(0)}%</span>`;
      }

      item.style.cssText = `background: ${isExpired ? 'rgba(239,68,68,0.03)' : 'rgba(255,255,255,0.03)'}; border: 1px solid var(--border); border-radius: 6px; padding: 10px; display: flex; justify-content: space-between; align-items: center;`;
      item.innerHTML = `
        <div style="flex: 1; min-width: 0; padding-right: 12px;">
          <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 2px;">
            ${escapeHtml(j.title)} ${fitScoreBadge}
          </div>
          <div style="font-size: 11px; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
            <span>${escapeHtml(j.company)}</span> · 
            <span>${escapeHtml(j.location || "Remote")}</span>
            ${statusBadge} ${workplaceBadge} ${empBadge}
          </div>
          <div style="font-size: 10px; color: var(--text-muted); margin-top: 3px;">
            Discovered: ${escapeHtml((j.discovered_at || j.created_at || '').slice(0, 10))} · Verified: ${escapeHtml((j.last_verified_at || '').slice(0, 10) || 'Recent')}
          </div>
        </div>
        <div style="display: flex; gap: 6px;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px;" onclick="window.evaluateCandidateJob('${j.stable_id}')">Evaluate</button>
          ${j.application_url ? `<a href="${escapeHtml(j.application_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px; text-decoration: none;">View</a>` : ''}
        </div>
      `;
      container.appendChild(item);
    });
  }

  async function loadDiscoveryJobs() {
    const container = document.getElementById("discovery-jobs-container");
    if (!container) return;
    try {
      const searchVal = document.getElementById("discovery-filter-search")?.value.trim() || "";
      const statusVal = document.getElementById("discovery-filter-status")?.value || "active";
      const scoreVal = document.getElementById("discovery-filter-score")?.value || "";
      const typeVal = document.getElementById("discovery-filter-type")?.value || "";
      const workplaceVal = document.getElementById("discovery-filter-workplace")?.value || "";

      const params = new URLSearchParams();
      if (searchVal) params.set("q", searchVal);
      if (statusVal) params.set("status", statusVal);
      if (scoreVal) params.set("min_score", scoreVal);
      if (typeVal) params.set("employment_type", typeVal);
      if (workplaceVal) params.set("workplace_type", workplaceVal);

      const res = await authedFetch(`/api/discovery/jobs?${params.toString()}`);
      const data = await res.json();
      const jobs = data.jobs || [];

      const countEl = document.getElementById("discovery-job-count");
      if (countEl) countEl.innerText = `${jobs.length} jobs`;

      renderDiscoveredJobsList(jobs);
    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; font-size: 12px;">Error loading jobs: ${err.message}</div>`;
    }
  }

  window.evaluateCandidateJob = async function (stableId) {
    switchView("matching");
    const card = document.getElementById("matching-evaluation-card");
    if (!card) return;
    card.innerHTML = `<div style="color: var(--primary); font-size: 13px;">Computing deterministic fit score in Python...</div>`;

    try {
      const res = await authedFetch("/api/matching/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stable_id: stableId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Evaluation failed");

      const eligColor = data.eligibility_status === "eligible" ? "#10b981" : (data.eligibility_status === "uncertain" ? "#f59e0b" : "#ef4444");

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <div>
            <h2 style="font-size: 18px; color: var(--text-main); margin-bottom: 4px;">${escapeHtml(data.job_title)} at ${escapeHtml(data.company)}</h2>
            <span style="font-size: 12px; font-weight: 700; color: ${eligColor}; text-transform: uppercase;">● Eligibility: ${escapeHtml(data.eligibility_status)}</span>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 28px; font-weight: 800; color: var(--primary); font-family: monospace;">${data.overall_score.toFixed(1)}<span style="font-size: 14px; color: var(--text-muted);">/100</span></div>
            <div style="font-size: 10px; color: var(--text-muted);">Deterministic Fit Score</div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; text-align: center;">
          <div><div style="font-size: 10px; color: var(--text-muted);">Required Skills (35%)</div><div style="font-size: 14px; font-weight: 700; color: #10b981;">${data.required_skills_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Duties (25%)</div><div style="font-size: 14px; font-weight: 700; color: #3b82f6;">${data.responsibilities_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Role Target (15%)</div><div style="font-size: 14px; font-weight: 700; color: #a855f7;">${data.target_role_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Exp & Edu (15%)</div><div style="font-size: 14px; font-weight: 700; color: #f59e0b;">${data.experience_edu_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Preferred (10%)</div><div style="font-size: 14px; font-weight: 700; color: #06b6d4;">${data.preferred_skills_score}%</div></div>
        </div>

        <div style="font-size: 12px; color: var(--text-muted); line-height: 1.5; margin-bottom: 16px;">
          ${escapeHtml(data.explanation)}
        </div>

        <button class="btn btn-primary" onclick="window.preparePack('${stableId}')">Prepare Application Materials</button>
      `;
    } catch (err) {
      card.innerHTML = `<div style="color: #ef4444; font-size: 13px;">Error: ${err.message}</div>`;
    }
  };

  window.preparePack = async function (stableId) {
    switchView("packs");
    const container = document.getElementById("application-pack-container");
    if (!container) return;
    container.innerHTML = `<div style="color: var(--primary); font-size: 13px;">Assembling application pack...</div>`;

    try {
      const res = await authedFetch("/api/application/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stable_id: stableId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Preparation failed");

      const token = localStorage.getItem("auth_token") || "";
      const dlUrl = `/api/application/download/${data.id}${token ? '?token=' + encodeURIComponent(token) : ''}`;

      container.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <h3 style="font-size: 16px; margin: 0; color: var(--text-main);">Application Pack #${data.id} (Candidate Review)</h3>
          <a href="${dlUrl}" class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;" download>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Download Pack (JSON)
          </a>
        </div>

        ${data.job_match_explanation ? `
          <div style="margin-bottom: 16px; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 6px; padding: 10px;">
            <div style="font-weight: 600; font-size: 12px; color: #60a5fa; margin-bottom: 4px;">Job Match Rationale:</div>
            <div style="font-size: 12px; color: var(--text-muted); line-height: 1.4;">${escapeHtml(data.job_match_explanation)}</div>
          </div>
        ` : ''}
        
        <div style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <div style="font-weight: 600; font-size: 12px; color: var(--primary);">Tailored Experience Summary:</div>
            <button class="btn btn-secondary" style="font-size: 10px; padding: 2px 6px;" onclick="window.copyToClipboard(document.getElementById('pack-summary-text').innerText)">Copy Summary</button>
          </div>
          <div id="pack-summary-text" style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; font-size: 12px; white-space: pre-wrap;">${escapeHtml(data.tailored_resume_summary)}</div>
        </div>

        <div style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <div style="font-weight: 600; font-size: 12px; color: var(--primary);">Tailored Cover Letter:</div>
            <button class="btn btn-secondary" style="font-size: 10px; padding: 2px 6px;" onclick="window.copyToClipboard(document.getElementById('pack-cover-letter').value)">Copy Cover Letter</button>
          </div>
          <textarea id="pack-cover-letter" style="width: 100%; height: 120px; background: rgba(0,0,0,0.2); border: 1px solid var(--border); color: var(--text-main); border-radius: 6px; padding: 10px; font-size: 12px;">${escapeHtml(data.cover_letter)}</textarea>
        </div>

        <div style="margin-bottom: 16px;">
          <div style="font-weight: 600; font-size: 12px; color: var(--primary); margin-bottom: 6px;">Screening Question Drafts:</div>
          ${data.question_drafts.map((q, idx) => `
            <div style="font-size: 12px; margin-bottom: 8px; background: rgba(0,0,0,0.15); padding: 8px 10px; border-radius: 4px; display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
              <div>
                <div style="font-weight: 600; color: var(--text-main); margin-bottom: 2px;">${escapeHtml(q.question)}</div>
                <div style="color: var(--text-muted);" id="q-draft-${idx}">${escapeHtml(q.draft_answer)}</div>
              </div>
              <button class="btn btn-secondary" style="font-size: 10px; padding: 2px 6px; white-space: nowrap;" onclick="window.copyToClipboard(document.getElementById('q-draft-${idx}').innerText)">Copy Answer</button>
            </div>
          `).join("")}
        </div>

        <div style="margin-bottom: 16px;">
          <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; cursor: pointer;">
            <input type="checkbox" id="check-user-approval" ${data.user_approved ? 'checked' : ''} onchange="window.toggleApproval(${data.id}, this.checked)">
            I have reviewed and approved these application materials.
          </label>
        </div>

        <div style="display: flex; gap: 12px;">
          <button class="btn btn-primary" onclick="window.confirmLinkedInSubmission('${stableId}')">Confirm Manual LinkedIn Submission</button>
          <button class="btn btn-secondary" onclick="window.submitExternalATS(${data.id})">Assisted External ATS Submit</button>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; font-size: 13px;">Error: ${err.message}</div>`;
    }
  };

  window.toggleApproval = async function (packId, approved) {
    try {
      await authedFetch("/api/application/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack_id: packId, approved }),
      });
      showToast(approved ? "Pack approved by candidate" : "Approval revoked");
    } catch (e) {
      showToast(`Approval update error: ${e.message}`, "error");
    }
  };

  window.confirmLinkedInSubmission = async function (stableId) {
    try {
      const res = await authedFetch("/api/application/confirm-linkedin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stable_id: stableId, confirmed: true, notes: "Confirmed via dashboard" }),
      });
      const data = await res.json();
      if (data.success) {
        showToast("LinkedIn application recorded in tracker!");
        switchView("applications");
      } else {
        showToast(data.error || "Failed to record submission", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    }
  };

  window.submitExternalATS = async function (packId) {
    const dryRun = document.getElementById("dry-run-checkbox") ? document.getElementById("dry-run-checkbox").checked : false;
    try {
      const res = await authedFetch("/api/application/submit-external", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack_id: packId, dry_run: dryRun }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message || "Submitted successfully!");
        switchView("applications");
      } else {
        showToast(data.error || "Submission failed", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    }
  };

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ── Apply Portals & Direct Form Links ─────────────────────────────
  const portalsState = {
    category: "all",
    search: "",
    jobs: [],
    loading: false,
  };

  async function loadApplyPortals() {
    const grid = document.getElementById("portals-cards-grid");
    if (!grid) return;

    portalsState.loading = true;
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 48px; color: var(--text-muted);">
        <div class="loading-spinner" style="margin: 0 auto 12px auto;"></div>
        Fetching direct application form links...
      </div>
    `;

    try {
      let url = `/api/apply-portals?limit=100`;
      if (portalsState.category && portalsState.category !== "all") {
        url += `&platform=${encodeURIComponent(portalsState.category)}`;
      }
      if (portalsState.search) {
        url += `&q=${encodeURIComponent(portalsState.search)}`;
      }

      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Update summary metric cards
      const elTotal = document.getElementById("stat-apply-total");
      const elLi = document.getElementById("stat-apply-linkedin");
      const elExt = document.getElementById("stat-apply-external");
      const cntAll = document.getElementById("cnt-tab-all");
      const cntLi = document.getElementById("cnt-tab-linkedin");
      const cntExt = document.getElementById("cnt-tab-external");

      if (elTotal) elTotal.textContent = data.total || 0;
      if (elLi) elLi.textContent = data.linkedin_count || 0;
      if (elExt) elExt.textContent = data.external_count || 0;
      if (cntAll) cntAll.textContent = data.total || 0;
      if (cntLi) cntLi.textContent = data.linkedin_count || 0;
      if (cntExt) cntExt.textContent = data.external_count || 0;

      portalsState.jobs = data.jobs || [];
      renderApplyPortals(portalsState.jobs);
    } catch (err) {
      console.error("Failed to load apply portals:", err);
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 32px; color: #EF4444;">
          Error loading application portals: ${escapeHtml(err.message)}
        </div>
      `;
    } finally {
      portalsState.loading = false;
    }
  }

  function getPlatformBadgeHtml(platform, category) {
    const p = (platform || "").toLowerCase();
    let badgeClass = "platform-badge-external";
    let iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`;

    if (category === "linkedin" || p.includes("linkedin")) {
      badgeClass = "platform-badge-linkedin";
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>`;
    } else if (p.includes("greenhouse")) {
      badgeClass = "platform-badge-greenhouse";
    } else if (p.includes("lever")) {
      badgeClass = "platform-badge-lever";
    } else if (p.includes("ashby")) {
      badgeClass = "platform-badge-ashby";
    } else if (p.includes("workday")) {
      badgeClass = "platform-badge-workday";
    }

    return `<span class="platform-badge ${badgeClass}">${iconSvg} ${escapeHtml(platform || "Direct")}</span>`;
  }

  function renderApplyPortals(jobs) {
    const grid = document.getElementById("portals-cards-grid");
    if (!grid) return;

    if (!jobs || jobs.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 48px; color: var(--text-muted); background: rgba(15, 23, 42, 0.4); border-radius: 12px; border: 1px dashed var(--border);">
          <div style="font-size: 16px; font-weight: 600; color: #FFFFFF; margin-bottom: 6px;">No application portals found</div>
          <div style="font-size: 13px;">Try searching for a different keyword or click 'Scrape with Chrome' to discover live listings.</div>
        </div>
      `;
      return;
    }

    grid.innerHTML = jobs
      .map((job, idx) => {
        const badgeHtml = getPlatformBadgeHtml(job.platform, job.platform_category);
        const applyUrl = job.apply_url || job.source_url || "#";
        const descText = (job.description || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
        const snippet = descText.length > 200 ? descText.slice(0, 200) + "..." : descText || "No description preview available.";

        return `
          <div class="portal-card" data-idx="${idx}">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 10px;">
                ${badgeHtml}
                <span class="badge ${job.status === 'applied' ? 'badge-applied' : 'badge-dry-run'}" style="font-size: 10.5px;">
                  ${escapeHtml(job.status || 'discovered')}
                </span>
              </div>

              <h3 style="font-size: 15.5px; font-weight: 700; color: #FFFFFF; margin: 0 0 5px 0; line-height: 1.35;">
                ${escapeHtml(job.title)}
              </h3>

              <div style="display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-muted); margin-bottom: 10px;">
                <span style="font-weight: 600; color: #E2E8F0;">${escapeHtml(job.company)}</span>
                <span>•</span>
                <span>${escapeHtml(job.location || 'Remote')}</span>
              </div>

              <div class="portal-desc-snippet">
                ${escapeHtml(snippet)}
              </div>
            </div>

            <div style="display: flex; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);">
              <button class="btn btn-secondary btn-sm btn-view-desc" data-idx="${idx}" style="flex: 1; padding: 7px 10px; font-size: 12px;">
                View Details
              </button>
              <a href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm" style="flex: 1.3; padding: 7px 12px; font-size: 12px; display: flex; align-items: center; justify-content: center; gap: 5px; text-decoration: none;">
                Open Form ↗
              </a>
            </div>
          </div>
        `;
      })
      .join("");

    // Attach click listeners to "View Details" buttons
    grid.querySelectorAll(".btn-view-desc").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        const job = jobs[idx];
        if (job) openJobModal(job);
      });
    });
  }

  function openJobModal(job) {
    const modal = document.getElementById("job-modal-overlay");
    if (!modal) return;

    const modalBadge = document.getElementById("modal-platform-badge");
    const modalTitle = document.getElementById("modal-job-title");
    const modalSubtitle = document.getElementById("modal-job-subtitle");
    const modalDesc = document.getElementById("modal-job-desc");
    const modalApply = document.getElementById("modal-apply-link");

    if (modalBadge) {
      modalBadge.innerHTML = getPlatformBadgeHtml(job.platform, job.platform_category);
    }
    if (modalTitle) modalTitle.textContent = job.title;
    if (modalSubtitle) modalSubtitle.textContent = `${job.company} • ${job.location || "Remote"}`;
    if (modalDesc) {
      const cleanDesc = (job.description || "").replace(/<[^>]*>/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
      modalDesc.textContent = cleanDesc || "No detailed job description captured.";
    }
    if (modalApply) {
      modalApply.href = job.apply_url || job.source_url || "#";
    }

    modal.style.display = "flex";
  }

  function closeJobModal() {
    const modal = document.getElementById("job-modal-overlay");
    if (modal) modal.style.display = "none";
  }

  // ── Lifecycle Boot ────────────────────────────────────────────────
  function init() {
    initListeners();
    initSSE();
    loadStatus();

    setInterval(loadStatus, 10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
