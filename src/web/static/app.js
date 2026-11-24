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
    logFilter: "all",
    autoScroll: true,
  };

  // ── Open-Source HTTP Request Helper ──────────────────────────────
  function authedFetch(url, options = {}) {
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
    bgModeCheckbox: document.getElementById("bg-mode-checkbox"),
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
    cfgCookiePolicy: document.getElementById("cfg-cookie-policy"),
    cfgLoginPortalPolicy: document.getElementById("cfg-login-portal-policy"),
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
    const lvlKey = (level || "info").toLowerCase();
    entry.setAttribute("data-level", lvlKey);

    if (state.logFilter !== "all" && lvlKey !== state.logFilter) {
      entry.style.display = "none";
    }

    const timeStr = timestamp
      ? new Date(timestamp).toLocaleTimeString()
      : new Date().toLocaleTimeString();

    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    timeSpan.textContent = `[${timeStr}]`;

    const lvlSpan = document.createElement("span");
    lvlSpan.className = `log-level ${lvlKey}`;
    lvlSpan.textContent = `[${(level || "INFO").toUpperCase()}]`;

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
    if (state.autoScroll) {
      els.terminalFeed.scrollTop = els.terminalFeed.scrollHeight;
    }
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

    state.sseSource.addEventListener("portal_update", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.job_id != null) {
          updatePortalCardStatus(data.job_id, data.status);
        }
        if (data.stable_id) {
          updatePortalCardStatus(data.stable_id, data.status);
        }
        loadMissionFeaturedJobs();
        loadStatus();
      } catch (err) {
        console.error("SSE portal_update parse error:", err);
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

      loadMissionFeaturedJobs();
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
    const isBackground = els.bgModeCheckbox ? els.bgModeCheckbox.checked : true;
    sfx.launch();
    try {
      setRunningState(true);
      const res = await authedFetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dry_run: dryRun,
          force_ingest: forceIngest,
          background: isBackground,
          headless: isBackground,
        }),
      });
      const data = await res.json();

      if (res.ok) {
        showToast(forceIngest ? "Profile sync & agent commenced" : "Sovereign run initiated");
        appendLog("info", `Initiated run (dry_run=${dryRun}, force_ingest=${forceIngest}, background=${isBackground})`);
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

  // ── Autonomous LinkedIn Search & Application Setup Modal ─────────
  async function openChromeSearchModal() {
    if (state.audioEnabled && sfx) sfx.click();
    const overlay = document.getElementById("search-modal-overlay");
    if (!overlay) return;
    overlay.style.display = "flex";

    const kwInput = document.getElementById("search-modal-keywords");
    const pillsContainer = document.getElementById("search-modal-suggested-pills");
    const bgCb = document.getElementById("search-modal-background");
    const dryRunCb = document.getElementById("search-modal-dryrun");

    if (bgCb && els.bgModeCheckbox) {
      bgCb.checked = els.bgModeCheckbox.checked;
    }
    if (dryRunCb && els.dryRunCheckbox) {
      dryRunCb.checked = els.dryRunCheckbox.checked;
    }

    // Pre-populate candidate screening answers & config from backend
    try {
      const cfgRes = await authedFetch("/api/config");
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        const answers = cfg?.apply?.answers || {};
        if (answers.expected_salary && document.getElementById("launch-exp-salary")) {
          document.getElementById("launch-exp-salary").value = answers.expected_salary;
        }
        if (answers.years_experience !== undefined && document.getElementById("launch-years-exp")) {
          document.getElementById("launch-years-exp").value = answers.years_experience;
        }
        if (answers.work_authorization && document.getElementById("launch-work-auth")) {
          document.getElementById("launch-work-auth").value = answers.work_authorization;
        }
        if (answers.visa_sponsorship !== undefined && document.getElementById("launch-sponsorship")) {
          document.getElementById("launch-sponsorship").value = String(answers.visa_sponsorship);
        }
        if (answers.notice_period && document.getElementById("launch-notice")) {
          document.getElementById("launch-notice").value = answers.notice_period;
        }

        // Job types from config
        const jobTypes = cfg?.search?.job_type || ["full-time", "internship"];
        const ftCb = document.getElementById("search-modal-jt-fulltime");
        const inCb = document.getElementById("search-modal-jt-internship");
        const ctCb = document.getElementById("search-modal-jt-contract");
        const ptCb = document.getElementById("search-modal-jt-parttime");
        if (ftCb) ftCb.checked = jobTypes.includes("full-time");
        if (inCb) inCb.checked = jobTypes.includes("internship");
        if (ctCb) ctCb.checked = jobTypes.includes("contract");
        if (ptCb) ptCb.checked = jobTypes.includes("part-time");

        // Min score threshold from config
        const minMatch = cfg?.apply?.min_match_score;
        if (minMatch !== undefined) {
          const pct = Math.round(minMatch * 100);
          const tSlider = document.getElementById("search-modal-threshold");
          const tDisplay = document.getElementById("search-modal-threshold-display");
          if (tSlider) tSlider.value = pct;
          if (tDisplay) tDisplay.textContent = `${pct}%`;
        }
      }
    } catch (e) {
      console.debug("Config prefill error:", e);
    }

    // Wire up browser count buttons
    const browserBtns = document.querySelectorAll("#browser-count-buttons .btn-browser-count");
    browserBtns.forEach((btn) => {
      btn.onclick = () => {
        if (state.audioEnabled && sfx) sfx.click();
        browserBtns.forEach((b) => {
          b.classList.remove("active", "btn-primary");
          b.classList.add("btn-secondary");
        });
        btn.classList.add("active", "btn-primary");
        btn.classList.remove("btn-secondary");
        const count = btn.getAttribute("data-count") || "2";
        const bInput = document.getElementById("search-modal-browsers");
        if (bInput) bInput.value = count;
        const bLabel = document.getElementById("search-modal-browsers-label");
        if (bLabel) {
          const labelText =
            count === "1" ? "1 Browser (Sequential)" :
            count === "2" ? "2 Browsers (Recommended ⚡)" :
            count === "3" ? "3 Browsers (High-Speed)" :
            "4 Browsers (Ultra-Fast 🚀)";
          bLabel.textContent = labelText;
        }
      };
    });

    // Wire up threshold slider and presets
    const thresholdSlider = document.getElementById("search-modal-threshold");
    const thresholdDisplay = document.getElementById("search-modal-threshold-display");
    if (thresholdSlider && thresholdDisplay) {
      thresholdSlider.oninput = () => {
        thresholdDisplay.textContent = `${thresholdSlider.value}%`;
      };
    }
    document.querySelectorAll(".btn-preset-pct").forEach((btn) => {
      btn.onclick = () => {
        if (state.audioEnabled && sfx) sfx.click();
        const val = btn.getAttribute("data-val");
        if (thresholdSlider) thresholdSlider.value = val;
        if (thresholdDisplay) thresholdDisplay.textContent = `${val}%`;
      };
    });

    if (pillsContainer) {
      pillsContainer.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">Analyzing candidate resume & skills...</span>';
      try {
        const res = await authedFetch("/api/candidate/suggested-keywords");
        if (res.ok) {
          const data = await res.json();
          const kws = data.suggested_keywords || [];
          if (kws.length === 0) {
            pillsContainer.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">No suggested secondary keywords found in profile.</span>';
          } else {
            pillsContainer.innerHTML = "";
            kws.forEach((kw) => {
              const pill = document.createElement("span");
              pill.className = "keyword-pill";
              pill.setAttribute("data-kw", kw);
              pill.textContent = `+ ${kw}`;
              pill.title = "Click to add this secondary keyword to search";
              pill.addEventListener("click", () => {
                if (state.audioEnabled && sfx) sfx.click();
                if (!kwInput) return;
                const cur = kwInput.value.trim();
                if (!cur) {
                  kwInput.value = kw;
                } else {
                  const parts = cur.split(",").map((p) => p.trim());
                  if (!parts.includes(kw)) {
                    kwInput.value = `${cur}, ${kw}`;
                  }
                }
                kwInput.focus();
              });
              pillsContainer.appendChild(pill);
            });
          }
        } else {
          pillsContainer.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">Could not load suggestions.</span>';
        }
      } catch (err) {
        console.error("Failed to load suggested keywords:", err);
        pillsContainer.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">Failed to load suggestions.</span>';
      }
    }

    if (kwInput) kwInput.focus();
  }

  function closeChromeSearchModal() {
    const overlay = document.getElementById("search-modal-overlay");
    if (overlay) overlay.style.display = "none";
  }

  async function startChromeSearch(options = {}) {
    if (state.audioEnabled && sfx) sfx.launch();

    const kwInput = document.getElementById("search-modal-keywords");
    const secondaryKeywords = (options.keywords !== undefined ? options.keywords : (kwInput ? kwInput.value.trim() : "")).trim();

    // Collect job types
    const jobTypes = [];
    if (document.getElementById("search-modal-jt-fulltime")?.checked) jobTypes.push("full-time");
    if (document.getElementById("search-modal-jt-internship")?.checked) jobTypes.push("internship");
    if (document.getElementById("search-modal-jt-contract")?.checked) jobTypes.push("contract");
    if (document.getElementById("search-modal-jt-parttime")?.checked) jobTypes.push("part-time");

    // Concurrency: Number of Chrome browsers
    const numBrowsers = parseInt(document.getElementById("search-modal-browsers")?.value || "2", 10);

    // Continuous 1-100% threshold
    const thresholdPct = parseInt(document.getElementById("search-modal-threshold")?.value || "60", 10);
    const minScore = thresholdPct / 100.0;

    // Candidate screening answers
    const answers = {
      expected_salary: document.getElementById("launch-exp-salary")?.value?.trim() || "15 LPA",
      years_experience: parseInt(document.getElementById("launch-years-exp")?.value || "2", 10),
      work_authorization: document.getElementById("launch-work-auth")?.value || "Yes",
      visa_sponsorship: document.getElementById("launch-sponsorship")?.value === "true",
      notice_period: document.getElementById("launch-notice")?.value?.trim() || "30 days",
    };

    const saveSettings = Boolean(document.getElementById("search-modal-save-settings")?.checked);
    const isDryRun = Boolean(document.getElementById("search-modal-dryrun")?.checked);
    const isBackground = Boolean(document.getElementById("search-modal-background")?.checked);

    closeChromeSearchModal();

    try {
      setRunningState(true);
      appendLog(
        "info",
        `🚀 Initiating Autonomous LinkedIn Application Loop:\n` +
        `  • Priority #1: Python Developer (Searched 1st to completion)\n` +
        (secondaryKeywords ? `  • Secondary Keywords: ${secondaryKeywords}\n` : "") +
        `  • Parallel Workers: ${numBrowsers} Chrome instances\n` +
        `  • LinkedIn Job Types: ${jobTypes.join(", ") || "All"}\n` +
        `  • Resume Match Cutoff: ≥ ${thresholdPct}%\n` +
        `  • Mode: ${isDryRun ? "Dry Run (Form Simulation)" : "Live Application Submission"}`
      );

      const res = await authedFetch("/api/search/live", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          keyword: secondaryKeywords || undefined,
          keywords: secondaryKeywords || undefined,
          job_types: jobTypes,
          num_browsers: numBrowsers,
          min_score: minScore,
          answers: answers,
          save_settings: saveSettings,
          dry_run: isDryRun,
          background: isBackground,
          headless: isBackground,
          location: "India",
          target: "linkedin",
        }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(
          isBackground
            ? `Autonomous search running in background across ${numBrowsers} browsers!`
            : `Autonomous search launched with ${numBrowsers} Chrome browsers!`
        );
      } else {
        showToast(data.error || "Failed to start autonomous search", "error");
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
          <div style="display: flex; align-items: center; gap: 8px;">
            <a href="${job.url && !job.url.includes('linkedin.com') && !job.url.includes('lnkd.in') ? escapeHtml(job.url) : `/api/jobs/${encodeURIComponent(job.job_id || job.id)}/open-form`}" target="_blank" rel="noopener noreferrer" style="color: #fff; text-decoration: none;" title="Open direct application form">
              ${escapeHtml(job.job_title || "Untitled Role")}
            </a>
            ${job.linkedin_url || (job.job_id && /^\d+$/.test(String(job.job_id))) ? `
            <a href="${escapeHtml(job.linkedin_url || `https://www.linkedin.com/jobs/view/${job.job_id}/`)}" target="_blank" rel="noopener noreferrer" style="color: #70B5F9; font-size: 10.5px; text-decoration: none; padding: 1px 5px; border: 1px solid rgba(10,102,194,0.4); border-radius: 4px; display: inline-flex; align-items: center; gap: 2px;" title="View original job post on LinkedIn">
              <span>LI ↗</span>
            </a>` : ''}
          </div>
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
          <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-start;">
            <span class="badge ${badgeClass}">${escapeHtml(job.status || "")}</span>
            ${job.proof_screenshot ? `
              <button class="btn btn-xs btn-view-proof" data-shot="${escapeHtml(job.proof_screenshot)}" data-title="${escapeHtml(job.job_title || job.title || '')}" data-company="${escapeHtml(job.company || '')}" data-reason="${escapeHtml(job.failure_reason || '')}" style="font-size: 10px; padding: 2px 7px; background: rgba(16, 185, 129, 0.15); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 4px; display: inline-flex; align-items: center; gap: 3px; cursor: pointer;" title="View verified application proof screenshot">
                <span>Proof 📸</span>
              </button>
            ` : ''}
            ${job.failure_reason && job.status !== 'applied' && job.status !== 'dry_run' ? `
              <span style="font-size: 10px; color: #F87171; max-width: 140px; line-height: 1.25; word-break: break-word;" title="${escapeHtml(job.failure_reason)}">
                ⚠️ ${escapeHtml(job.failure_reason.slice(0, 42))}${job.failure_reason.length > 42 ? '...' : ''}
              </span>
            ` : ''}
          </div>
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
    if (els.cfgCookiePolicy) {
      els.cfgCookiePolicy.value = cfg.browser?.cookie_policy || "hide_banner";
    }
    if (els.cfgLoginPortalPolicy) {
      els.cfgLoginPortalPolicy.value = cfg.apply?.login_portal_policy || "skip_portal";
    }
  }

  async function saveConfig() {
    if (!state.config) state.config = {};
    sfx.click();

    if (els.cfgCookiePolicy) {
      if (!state.config.browser) state.config.browser = {};
      state.config.browser.cookie_policy = els.cfgCookiePolicy.value;
    }
    if (els.cfgLoginPortalPolicy) {
      if (!state.config.apply) state.config.apply = {};
      state.config.apply.login_portal_policy = els.cfgLoginPortalPolicy.value;
    }

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

    // Watch Bot (Visible vs Background) Toggle Sync
    const watchBotEl = document.getElementById("watch-bot-checkbox");
    if (watchBotEl) {
      const savedWatchBot = localStorage.getItem("autobot_watch_bot");
      if (savedWatchBot !== null) {
        watchBotEl.checked = savedWatchBot === "true";
      } else {
        watchBotEl.checked = true; // Default to visible Chrome
      }
      if (els.bgModeCheckbox) {
        els.bgModeCheckbox.checked = !watchBotEl.checked;
      }
      const updateWatchBotLabel = () => {
        const label = document.getElementById("watch-bot-label");
        if (label) {
          label.textContent = watchBotEl.checked ? "Watch Bot (Visible)" : "Background (Silent)";
        }
      };
      updateWatchBotLabel();

      watchBotEl.addEventListener("change", () => {
        localStorage.setItem("autobot_watch_bot", watchBotEl.checked ? "true" : "false");
        if (els.bgModeCheckbox) {
          els.bgModeCheckbox.checked = !watchBotEl.checked;
        }
        updateWatchBotLabel();
        if (state.audioEnabled && sfx) sfx.click();
        showToast(
          watchBotEl.checked
            ? "👁️ Bot will open visible Google Chrome so you can watch form filling"
            : "🔇 Bot will apply silently in background mode",
          "info"
        );
      });
    }

    // Run actions - All trigger the Autonomous LinkedIn Setup modal so user can configure parallel browsers, job types, and match threshold
    els.btnStart.addEventListener("click", () => openChromeSearchModal());
    if (els.btnSearchChrome) {
      els.btnSearchChrome.addEventListener("click", () => openChromeSearchModal());
    }
    els.btnForceIngest.addEventListener("click", () => startAgentRun(true));
    els.btnStop.addEventListener("click", () => stopAgentRun());

    if (els.btnHeroLaunch) {
      els.btnHeroLaunch.addEventListener("click", () => openChromeSearchModal());
    }

    // Terminal clear
    els.btnClearLogs.addEventListener("click", () => {
      sfx.click();
      els.terminalFeed.innerHTML = "";
      appendLog("info", "Terminal telemetry log buffer cleared.");
    });

    // Terminal copy logs
    const btnCopyLogs = document.getElementById("btn-copy-logs");
    if (btnCopyLogs) {
      btnCopyLogs.addEventListener("click", () => {
        sfx.click();
        const text = Array.from(els.terminalFeed.querySelectorAll(".log-entry"))
          .filter((el) => el.style.display !== "none")
          .map((el) => el.textContent.trim())
          .join("\n");
        navigator.clipboard.writeText(text).then(() => {
          showToast("Terminal logs copied to clipboard!");
        }).catch(() => {
          showToast("Failed to copy logs", "error");
        });
      });
    }

    // Terminal auto-scroll toggle
    const btnAutoScroll = document.getElementById("btn-autoscroll-toggle");
    if (btnAutoScroll) {
      btnAutoScroll.addEventListener("click", () => {
        sfx.click();
        state.autoScroll = !state.autoScroll;
        btnAutoScroll.textContent = state.autoScroll ? "Auto-Scroll: ON" : "Auto-Scroll: OFF";
        showToast(state.autoScroll ? "Terminal auto-scroll enabled" : "Terminal auto-scroll paused");
      });
    }

    // Terminal log filter buttons
    document.querySelectorAll(".log-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        sfx.click();
        document.querySelectorAll(".log-filter-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const filter = btn.getAttribute("data-filter") || "all";
        state.logFilter = filter;

        els.terminalFeed.querySelectorAll(".log-entry").forEach((entry) => {
          const entryLevel = entry.getAttribute("data-level") || "info";
          if (filter === "all" || entryLevel === filter) {
            entry.style.display = "";
          } else {
            entry.style.display = "none";
          }
        });
      });
    });

    // Interactive LangGraph node click inspection
    const nodeDescriptions = {
      search: "1. SEARCH: Discovers fresh vacancies via Playwright Stealth & deep resume keyword analysis.",
      filter: "2. FILTER: Removes duplicates, senior titles, and expired roles via SQLite ACID predicates.",
      evaluate: "3. EVALUATE: Computes deterministic 0–100 candidate-job similarity fit with Qdrant vector memory.",
      apply: "4. APPLY: Automates form filling, resume PDF upload, and screening question submission.",
      record: "5. RECORD: Commits application telemetry, timestamps, and artifacts to SQLite database.",
      advance: "6. ADVANCE: Iterates to subsequent search page and monitors candidate application quotas.",
    };

    document.querySelectorAll(".graph-node").forEach((nodeEl) => {
      nodeEl.addEventListener("click", () => {
        sfx.click();
        const nodeName = nodeEl.getAttribute("data-node") || "search";
        updateGraphNode(nodeName);
        appendLog("info", `[pipeline] ℹ Active inspection: ${nodeDescriptions[nodeName] || nodeName}`);
      });
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
        if (state.audioEnabled && sfx) sfx.click();
        document.querySelectorAll(".platform-tab").forEach((t) => {
          t.classList.remove("active");
          t.style.background = "transparent";
          t.style.color = "var(--text-muted)";
        });
        tab.classList.add("active");
        tab.style.background = "var(--primary)";
        tab.style.color = "#ffffff";
        portalsState.category = tab.getAttribute("data-category") || "all";
        portalsState.platform = "all";

        // Highlight platform dropdown when external platforms tab is active
        const platformWrap = document.getElementById("portal-platform-filter-wrap");
        if (platformWrap) {
          if (portalsState.category === "external") {
            platformWrap.style.borderColor = "rgba(16, 185, 129, 0.45)";
          } else if (portalsState.category === "linkedin_external") {
            platformWrap.style.borderColor = "rgba(14, 165, 233, 0.45)";
          } else if (portalsState.category === "linkedin_easy" || portalsState.category === "linkedin") {
            platformWrap.style.borderColor = "rgba(99, 102, 241, 0.45)";
          } else {
            platformWrap.style.borderColor = "var(--border)";
          }
        }

        loadApplyPortals();
      });
    });

    // Apply Portals View Mode Toggle (Grid vs Group by Platform)
    const btnGrid = document.getElementById("btn-view-grid");
    const btnGrouped = document.getElementById("btn-view-grouped");
    function updateViewModeButtons() {
      if (btnGrid && btnGrouped) {
        if (portalsState.viewMode === "grouped") {
          btnGrouped.classList.add("active");
          btnGrouped.style.background = "var(--primary)";
          btnGrouped.style.color = "#FFFFFF";
          btnGrid.classList.remove("active");
          btnGrid.style.background = "transparent";
          btnGrid.style.color = "var(--text-muted)";
        } else {
          btnGrid.classList.add("active");
          btnGrid.style.background = "var(--primary)";
          btnGrid.style.color = "#FFFFFF";
          btnGrouped.classList.remove("active");
          btnGrouped.style.background = "transparent";
          btnGrouped.style.color = "var(--text-muted)";
        }
      }
    }
    if (btnGrid) {
      btnGrid.addEventListener("click", () => {
        if (portalsState.viewMode === "grid") return;
        portalsState.viewMode = "grid";
        localStorage.setItem("autobot_portal_view_mode", "grid");
        updateViewModeButtons();
        if (state.audioEnabled && sfx) sfx.click();
        renderApplyPortals(portalsState.jobs);
      });
    }
    if (btnGrouped) {
      btnGrouped.addEventListener("click", () => {
        if (portalsState.viewMode === "grouped") return;
        portalsState.viewMode = "grouped";
        localStorage.setItem("autobot_portal_view_mode", "grouped");
        updateViewModeButtons();
        if (state.audioEnabled && sfx) sfx.click();
        renderApplyPortals(portalsState.jobs);
      });
    }
    updateViewModeButtons();

    // Apply Portals Platform dropdown
    const platformSelect = document.getElementById("portal-platform-select");
    if (platformSelect) {
      platformSelect.addEventListener("change", () => {
        portalsState.platform = platformSelect.value;
        if (state.audioEnabled && sfx) sfx.click();
        loadApplyPortals();
      });
    }

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

    // Continuous 1-100% Resume Match Threshold Slider (Toolbar)
    const portalSlider = document.getElementById("portal-threshold-slider");
    const portalSliderVal = document.getElementById("portal-threshold-slider-val");
    if (portalSlider) {
      portalSlider.addEventListener("input", () => {
        const val = portalSlider.value;
        if (portalSliderVal) portalSliderVal.textContent = `≥ ${val}%`;
        portalsState.minScore = (val / 100).toFixed(2);
        loadApplyPortals();
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
        openChromeSearchModal();
      });
    }

    // Search in Chrome Modal Controls
    const searchModalOverlay = document.getElementById("search-modal-overlay");
    const searchModalCloseBtn = document.getElementById("search-modal-close-btn");
    const searchModalCancelBtn = document.getElementById("search-modal-cancel-btn");
    const searchModalSubmitBtn = document.getElementById("search-modal-submit-btn");
    const searchModalKwInput = document.getElementById("search-modal-keywords");
    const searchModalLocInput = document.getElementById("search-modal-location");

    if (searchModalCloseBtn) {
      searchModalCloseBtn.addEventListener("click", () => closeChromeSearchModal());
    }
    if (searchModalCancelBtn) {
      searchModalCancelBtn.addEventListener("click", () => closeChromeSearchModal());
    }
    if (searchModalOverlay) {
      searchModalOverlay.addEventListener("click", (e) => {
        if (e.target === searchModalOverlay) closeChromeSearchModal();
      });
    }
    if (searchModalSubmitBtn) {
      searchModalSubmitBtn.addEventListener("click", () => startChromeSearch());
    }
    if (searchModalKwInput) {
      searchModalKwInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          startChromeSearch();
        }
      });
    }
    if (searchModalLocInput) {
      searchModalLocInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          startChromeSearch();
        }
      });
    }

    // Portals Batch Bar Controls
    const selectAllCb = document.getElementById("portals-select-all-checkbox");
    if (selectAllCb) {
      selectAllCb.addEventListener("change", () => {
        if (state.audioEnabled && sfx) sfx.click();
        if (selectAllCb.checked) {
          portalsState.jobs.forEach((j) => {
            const id = String(j.id != null ? j.id : (j.job_id || ""));
            if (id) portalsState.selectedIds.add(id);
          });
        } else {
          portalsState.selectedIds.clear();
        }
        renderApplyPortals(portalsState.jobs);
        updateBatchBarState();
      });
    }

    const clearSelBtn = document.getElementById("btn-clear-selection");
    if (clearSelBtn) {
      clearSelBtn.addEventListener("click", () => {
        if (state.audioEnabled && sfx) sfx.click();
        portalsState.selectedIds.clear();
        renderApplyPortals(portalsState.jobs);
        updateBatchBarState();
      });
    }

    const btnApplySelected = document.getElementById("btn-apply-selected");
    if (btnApplySelected) {
      btnApplySelected.addEventListener("click", async () => {
        const ids = Array.from(portalsState.selectedIds);
        if (!ids.length) return;
        const dryRunCb = document.getElementById("portals-dryrun-checkbox");
        const dryRun = dryRunCb ? dryRunCb.checked : false;
        await executePortalApplyBot(ids, dryRun, btnApplySelected);
      });
    }

    const dryRunCb = document.getElementById("portals-dryrun-checkbox");
    const modeBadge = document.getElementById("dryrun-mode-badge");
    if (dryRunCb && modeBadge) {
      dryRunCb.addEventListener("change", () => {
        if (dryRunCb.checked) {
          modeBadge.style.background = "rgba(245, 158, 11, 0.15)";
          modeBadge.style.color = "#F59E0B";
          modeBadge.style.borderColor = "rgba(245, 158, 11, 0.3)";
          modeBadge.textContent = "🛡️ DRY-RUN SIMULATION (NO SUBMIT)";
        } else {
          modeBadge.style.background = "rgba(16, 185, 129, 0.15)";
          modeBadge.style.color = "#10B981";
          modeBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";
          modeBadge.textContent = "⚡ LIVE SUBMIT MODE";
        }
      });
    }

    const btnDeleteSelected = document.getElementById("btn-delete-selected");
    if (btnDeleteSelected) {
      btnDeleteSelected.addEventListener("click", () => deleteSelectedPortals());
    }

    const btnDeleteAll = document.getElementById("btn-delete-all-portals");
    if (btnDeleteAll) {
      btnDeleteAll.addEventListener("click", () => deleteAllPortals());
    }

    // ── 1-Click Direct URL Apply Listeners ─────────────────────────
    const inputDirectApply = document.getElementById("input-direct-apply-url");
    const btnDirectApply = document.getElementById("btn-direct-apply-submit");
    if (btnDirectApply && inputDirectApply) {
      btnDirectApply.addEventListener("click", () => {
        const dryRun = els.dryRunCheckbox ? els.dryRunCheckbox.checked : false;
        executeDirectUrlApply(inputDirectApply.value, dryRun, btnDirectApply);
      });
      inputDirectApply.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const dryRun = els.dryRunCheckbox ? els.dryRunCheckbox.checked : false;
          executeDirectUrlApply(inputDirectApply.value, dryRun, btnDirectApply);
        }
      });
    }

    const inputPortalDirect = document.getElementById("input-portal-direct-apply-url");
    const btnPortalDirect = document.getElementById("btn-portal-direct-apply-submit");
    if (btnPortalDirect && inputPortalDirect) {
      btnPortalDirect.addEventListener("click", () => {
        const dryRunCb = document.getElementById("portals-dryrun-checkbox");
        const dryRun = dryRunCb ? dryRunCb.checked : false;
        executeDirectUrlApply(inputPortalDirect.value, dryRun, btnPortalDirect);
      });
      inputPortalDirect.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const dryRunCb = document.getElementById("portals-dryrun-checkbox");
          const dryRun = dryRunCb ? dryRunCb.checked : false;
          executeDirectUrlApply(inputPortalDirect.value, dryRun, btnPortalDirect);
        }
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

    const btnMissionViewAll = document.getElementById("btn-mission-view-all-portals");
    if (btnMissionViewAll) {
      btnMissionViewAll.addEventListener("click", () => {
        switchView("apply-portals");
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
            ATS: <span style="color: var(--primary-light); font-weight: 600;">${escapeHtml(s.source_type)}</span> (${escapeHtml(s.board_slug)})
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
      const tags = keywords.map(k => `<span class="badge" style="background: rgba(255,255,255,0.08); color: #ffffff; border: 1px solid rgba(255,255,255,0.16); font-size: 12px; margin-right: 4px; margin-bottom: 4px; display: inline-block;">${escapeHtml(k)}</span>`).join('');
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
    container.innerHTML = '<div style="color: var(--primary-light); font-size: 13px; font-weight: 500;">Searching personalized jobs matching candidate profile...</div>';
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
        const scoreColor = score >= 75 ? '#10b981' : (score >= 60 ? '#ffffff' : '#a1a1aa');
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
        <div style="display: flex; gap: 6px; align-items: center;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px;" onclick="window.evaluateCandidateJob('${j.stable_id}')">Evaluate</button>
          ${(j.apply_type === 'Easy Apply' || j.apply_type === 'easy_apply' || j.is_easy_apply === true || (j.source_name || '').toLowerCase().includes('easy apply')) ? `
          <a href="${escapeHtml(j.linkedin_url || (j.stable_id && /^\d+$/.test(String(j.stable_id)) ? `https://www.linkedin.com/jobs/view/${j.stable_id}/` : 'https://www.linkedin.com/jobs/'))}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px; text-decoration: none; color: #34D399; border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.08);" title="Open Easy Apply on LinkedIn">Easy Apply on LinkedIn ↗</a>
          ` : `
          <a href="${j.application_url && !j.application_url.includes('linkedin.com') && !j.application_url.includes('lnkd.in') ? escapeHtml(j.application_url) : `/api/jobs/${encodeURIComponent(j.stable_id || j.id)}/open-form`}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px; text-decoration: none; color: #38BDF8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.08);" title="Open direct application form">Apply Form ↗</a>
          <a href="${escapeHtml(j.linkedin_url || (j.stable_id && /^\d+$/.test(String(j.stable_id)) ? `https://www.linkedin.com/jobs/view/${j.stable_id}/` : 'https://www.linkedin.com/jobs/'))}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px; text-decoration: none; color: #70B5F9;" title="View original job post on LinkedIn">LinkedIn ↗</a>
          `}
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

      const eligColor = data.eligibility_status === "eligible" ? "#10b981" : (data.eligibility_status === "uncertain" ? "#e4e4e7" : "#ef4444");

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
          <div><div style="font-size: 10px; color: var(--text-muted);">Duties (25%)</div><div style="font-size: 14px; font-weight: 700; color: #ffffff;">${data.responsibilities_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Role Target (15%)</div><div style="font-size: 14px; font-weight: 700; color: #a855f7;">${data.target_role_score}%</div></div>
          <div><div style="font-size: 10px; color: var(--text-muted);">Exp & Edu (15%)</div><div style="font-size: 14px; font-weight: 700; color: #e4e4e7;">${data.experience_edu_score}%</div></div>
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

      const dlUrl = `/api/application/download/${data.id}`;

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
    platform: "all",
    search: "",
    minScore: "0.60",
    viewMode: localStorage.getItem("autobot_portal_view_mode") || "grid",
    jobs: [],
    platforms: {},
    loading: false,
    selectedIds: new Set(),
    grandTotals: null,  // cached grand totals (unfiltered) for metric cards
  };

  function updatePlatformPills(platforms, currentPlatform) {
    const container = document.getElementById("portal-dynamic-platform-pills");
    if (!container) return;

    if (!platforms || typeof platforms !== "object" || Object.keys(platforms).length === 0) {
      container.innerHTML = "";
      return;
    }

    const platformMeta = {
      "Greenhouse": { icon: "🌿", color: "#34D399", bg: "rgba(16, 185, 129, 0.12)", border: "rgba(16, 185, 129, 0.35)", activeBg: "#10B981" },
      "Ashby": { icon: "⚡", color: "#C084FC", bg: "rgba(168, 85, 247, 0.12)", border: "rgba(168, 85, 247, 0.35)", activeBg: "#A855F7" },
      "Lever": { icon: "🟧", color: "#FB923C", bg: "rgba(249, 115, 22, 0.12)", border: "rgba(249, 115, 22, 0.35)", activeBg: "#F97316" },
      "Workday": { icon: "🔷", color: "#60A5FA", bg: "rgba(59, 130, 246, 0.12)", border: "rgba(59, 130, 246, 0.35)", activeBg: "#3B82F6" },
      "SmartRecruiters": { icon: "✨", color: "#F472B6", bg: "rgba(236, 72, 153, 0.12)", border: "rgba(236, 72, 153, 0.35)", activeBg: "#EC4899" },
      "iCIMS": { icon: "🌐", color: "#22D3EE", bg: "rgba(6, 182, 212, 0.12)", border: "rgba(6, 182, 212, 0.35)", activeBg: "#06B6D4" },
      "Oracle": { icon: "🔴", color: "#F87171", bg: "rgba(239, 68, 68, 0.12)", border: "rgba(239, 68, 68, 0.35)", activeBg: "#EF4444" },
    };

    let pillsHtml = "";
    for (const [name, count] of Object.entries(platforms)) {
      if (count <= 0) continue;
      // Hide generic LinkedIn items from dynamic pills as they already have dedicated primary tabs
      if (name.includes("Easy Apply") || name.includes("External Form")) continue;

      const meta = platformMeta[name] || {
        icon: "🌐",
        color: "#38BDF8",
        bg: "rgba(56, 189, 248, 0.12)",
        border: "rgba(56, 189, 248, 0.35)",
        activeBg: "var(--primary)"
      };

      const isActive = (currentPlatform && currentPlatform.toLowerCase() === name.toLowerCase());
      const activeStyle = isActive
        ? `background: ${meta.activeBg}; color: #FFFFFF; border: 1px solid ${meta.activeBg}; box-shadow: 0 0 10px ${meta.border}; font-weight: 700;`
        : `background: ${meta.bg}; color: ${meta.color}; border: 1px solid ${meta.border}; font-weight: 600;`;

      pillsHtml += `
        <button class="platform-pill-btn ${isActive ? 'active' : ''}" data-platform="${escapeHtml(name)}" title="Filter directly for ${escapeHtml(name)} (${count} roles)" style="display: inline-flex; align-items: center; gap: 5px; padding: 5px 12px; border-radius: 9999px; font-size: 12px; cursor: pointer; transition: all 0.2s ease; ${activeStyle}">
          <span>${meta.icon}</span>
          <span>${escapeHtml(name)}</span>
          <span style="background: rgba(0,0,0,0.3); border-radius: 9999px; padding: 1px 7px; font-size: 11px;">${count}</span>
        </button>
      `;
    }

    container.innerHTML = pillsHtml;

    container.querySelectorAll(".platform-pill-btn").forEach((pill) => {
      pill.addEventListener("click", () => {
        const plat = pill.getAttribute("data-platform");
        if (portalsState.platform && portalsState.platform.toLowerCase() === plat.toLowerCase()) {
          setPlatformFilter("all");
        } else {
          setPlatformFilter(plat);
        }
      });
    });
  }

  function setPlatformFilter(platformName) {
    if (state.audioEnabled && sfx) sfx.click();
    portalsState.platform = platformName || "all";

    // Synchronize the platform select dropdown
    const select = document.getElementById("portal-platform-select");
    if (select) {
      let found = false;
      for (const opt of select.options) {
        if (opt.value.toLowerCase() === (platformName || "").toLowerCase()) {
          select.value = opt.value;
          found = true;
          break;
        }
      }
      if (!found && platformName === "all") {
        select.value = "all";
      }
    }

    // Synchronize category tabs visual state
    document.querySelectorAll(".platform-tab").forEach((t) => {
      const cat = t.getAttribute("data-category");
      if (platformName && platformName !== "all") {
        const isEasy = platformName.toLowerCase().includes("easy apply");
        const isLiExt = platformName.toLowerCase().includes("external form");
        if (isEasy && cat === "linkedin_easy") {
          t.classList.add("active");
          t.style.background = "var(--primary)";
          t.style.color = "#ffffff";
        } else if (isLiExt && cat === "linkedin_external") {
          t.classList.add("active");
          t.style.background = "var(--primary)";
          t.style.color = "#ffffff";
        } else if (!isEasy && !isLiExt && cat === "external") {
          t.classList.add("active");
          t.style.background = "var(--primary)";
          t.style.color = "#ffffff";
        } else {
          t.classList.remove("active");
          t.style.background = "transparent";
          t.style.color = "var(--text-muted)";
        }
      } else {
        if (cat === (portalsState.category || "all")) {
          t.classList.add("active");
          t.style.background = "var(--primary)";
          t.style.color = "#ffffff";
        } else {
          t.classList.remove("active");
          t.style.background = "transparent";
          t.style.color = "var(--text-muted)";
        }
      }
    });

    loadApplyPortals();
  }

  function updatePlatformDropdown(platforms, category, total, liCount, extCount, liExtCount, liEasyCount) {
    const select = document.getElementById("portal-platform-select");
    const wrap = document.getElementById("portal-platform-filter-wrap");
    if (!select) return;

    const currentVal = portalsState.platform || "all";
    let html = "";

    if (category === "linkedin_external" || category === "linkedin-external" || category === "external") {
      if (wrap) {
        wrap.style.display = "flex";
        wrap.style.borderColor = "rgba(16, 185, 129, 0.45)";
      }
      html += `<option value="all" style="background: #0F172A; color: #FFFFFF;">All Direct External Forms (${liExtCount || extCount || 0})</option>`;
      if (platforms && typeof platforms === "object" && Object.keys(platforms).length > 0) {
        for (const [platName, count] of Object.entries(platforms)) {
          if (count > 0 && !platName.includes("Easy Apply")) {
            html += `<option value="${escapeHtml(platName)}" style="background: #0F172A; color: #FFFFFF;">${escapeHtml(platName)} (${count})</option>`;
          }
        }
      } else {
        html += `<option value="LinkedIn (External Form)" style="background: #0F172A; color: #FFFFFF;">LinkedIn (External Form) (${liExtCount || extCount || 0})</option>`;
      }
    } else if (category === "linkedin_easy" || category === "linkedin-easy") {
      if (wrap) {
        wrap.style.display = "flex";
        wrap.style.borderColor = "rgba(99, 102, 241, 0.45)";
      }
      html += `<option value="all" style="background: #0F172A; color: #FFFFFF;">All LinkedIn Easy Apply (${liEasyCount || 0})</option>`;
      html += `<option value="LinkedIn (Easy Apply)" style="background: #0F172A; color: #FFFFFF;">LinkedIn (Easy Apply) (${liEasyCount || 0})</option>`;
    } else {
      if (wrap) {
        wrap.style.display = "flex";
        wrap.style.borderColor = "var(--border)";
      }
      html += `<option value="all" style="background: #0F172A; color: #FFFFFF;">All Platforms (${total || 0})</option>`;
      if (platforms && typeof platforms === "object" && Object.keys(platforms).length > 0) {
        for (const [platName, count] of Object.entries(platforms)) {
          if (count > 0) {
            html += `<option value="${escapeHtml(platName)}" style="background: #0F172A; color: #FFFFFF;">${escapeHtml(platName)} (${count})</option>`;
          }
        }
      } else {
        if ((liExtCount || extCount || 0) > 0) {
          html += `<option value="LinkedIn (External Form)" style="background: #0F172A; color: #FFFFFF;">LinkedIn (External Form) (${liExtCount || extCount || 0})</option>`;
        }
        if ((liEasyCount || 0) > 0) {
          html += `<option value="LinkedIn (Easy Apply)" style="background: #0F172A; color: #FFFFFF;">LinkedIn (Easy Apply) (${liEasyCount || 0})</option>`;
        }
      }
    }

    select.innerHTML = html;
    const hasOption = Array.from(select.options).some((opt) => opt.value === currentVal);
    select.value = hasOption ? currentVal : "all";
    portalsState.platform = select.value;
  }

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
        url += `&category=${encodeURIComponent(portalsState.category)}`;
      }
      if (portalsState.platform && portalsState.platform !== "all") {
        url += `&platform=${encodeURIComponent(portalsState.platform)}`;
      }
      if (portalsState.search) {
        url += `&q=${encodeURIComponent(portalsState.search)}`;
      }
      if (portalsState.minScore) {
        url += `&min_score=${encodeURIComponent(portalsState.minScore)}`;
      }

      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Update summary metric cards — always show GRAND TOTALS (unfiltered)
      const elTotal = document.getElementById("stat-apply-total");
      const elExt = document.getElementById("stat-apply-external");
      const elLiExt = document.getElementById("stat-apply-linkedin-ext");
      const elLiEasy = document.getElementById("stat-apply-linkedin-easy");
      const cntAll = document.getElementById("cnt-tab-all");
      const cntExt = document.getElementById("cnt-tab-external");
      const cntLiExt = document.getElementById("cnt-tab-linkedin-ext");
      const cntLiEasy = document.getElementById("cnt-tab-linkedin-easy");

      // Compute authentic grand totals
      const directAtsVal = data.direct_ats_count != null ? data.direct_ats_count : (data.external_count || 0);
      const liExtVal = data.linkedin_external_count || 0;
      const liEasyVal = data.linkedin_easy_count || 0;
      const serverGrandTotal = data.grand_total != null ? data.grand_total : (directAtsVal + liExtVal + liEasyVal);

      // Always maintain stable grand totals so metric cards remain rock-solid across filters
      if (!portalsState.grandTotals || serverGrandTotal >= (portalsState.grandTotals.total || 0)) {
        portalsState.grandTotals = {
          total: serverGrandTotal,
          external: directAtsVal,
          liExt: liExtVal,
          liEasy: liEasyVal,
        };
      }
      const gt = portalsState.grandTotals;

      // Metric cards always show consistent grand totals
      if (elTotal) elTotal.textContent = gt.total;
      if (elExt) elExt.textContent = gt.external;
      if (elLiExt) elLiExt.textContent = gt.liExt;
      if (elLiEasy) elLiEasy.textContent = gt.liEasy;

      // Category tab badges always reflect their respective category totals
      if (cntAll) cntAll.textContent = gt.total;
      if (cntExt) cntExt.textContent = gt.external;
      if (cntLiExt) cntLiExt.textContent = gt.liExt;
      if (cntLiEasy) cntLiEasy.textContent = gt.liEasy;

      portalsState.jobs = data.jobs || [];
      portalsState.platforms = data.platforms || {};

      // Synchronize the Platform Dropdown with the exact platform opportunities
      updatePlatformDropdown(
        portalsState.platforms,
        portalsState.category,
        data.total,
        data.linkedin_count,
        data.external_count,
        data.linkedin_external_count,
        data.linkedin_easy_count
      );

      // Render Dynamic Platform Pills in the filter bar
      updatePlatformPills(portalsState.platforms, portalsState.platform);

      renderApplyPortals(portalsState.jobs);
      updateBatchBarState();
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

  function getPlatformBadgeHtml(platform, category, explicitIsEasy = null) {
    const p = (platform || "").toLowerCase();
    const isEasy = (explicitIsEasy !== null ? explicitIsEasy : (category === "linkedin" || p.includes("easy apply") || p.includes("easy_apply")));

    if (isEasy) {
      const iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>`;
      return `<button type="button" class="platform-badge platform-badge-linkedin btn-filter-platform" data-platform="LinkedIn (Easy Apply)" style="background: rgba(16, 185, 129, 0.15); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; border-radius: 9999px; padding: 3px 9px; font-size: 11px;" title="Click to filter only LinkedIn (Easy Apply) roles">${iconSvg} LinkedIn (Easy Apply)</button>`;
    }

    let atsName = "LinkedIn (External Form)";
    let filterPlat = "LinkedIn (External Form)";
    let badgeStyle = "background: rgba(56, 189, 248, 0.12); color: #38BDF8; border: 1px solid rgba(56, 189, 248, 0.35);";
    const extSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`;

    if (p.includes("greenhouse")) {
      atsName = "Greenhouse (External ATS)";
      filterPlat = "Greenhouse";
      badgeStyle = "background: rgba(16, 185, 129, 0.15); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.4);";
    } else if (p.includes("ashby")) {
      atsName = "Ashby (External ATS)";
      filterPlat = "Ashby";
      badgeStyle = "background: rgba(168, 85, 247, 0.15); color: #C084FC; border: 1px solid rgba(168, 85, 247, 0.4);";
    } else if (p.includes("lever")) {
      atsName = "Lever (External ATS)";
      filterPlat = "Lever";
      badgeStyle = "background: rgba(249, 115, 22, 0.15); color: #FB923C; border: 1px solid rgba(249, 115, 22, 0.4);";
    } else if (p.includes("workday")) {
      atsName = "Workday (External ATS)";
      filterPlat = "Workday";
      badgeStyle = "background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.4);";
    } else if (p.includes("smartrecruiters")) {
      atsName = "SmartRecruiters (External ATS)";
      filterPlat = "SmartRecruiters";
      badgeStyle = "background: rgba(236, 72, 153, 0.15); color: #F472B6; border: 1px solid rgba(236, 72, 153, 0.4);";
    } else if (p.includes("icims")) {
      atsName = "iCIMS (External ATS)";
      filterPlat = "iCIMS";
      badgeStyle = "background: rgba(6, 182, 212, 0.15); color: #22D3EE; border: 1px solid rgba(6, 182, 212, 0.4);";
    } else if (p.includes("oracle")) {
      atsName = "Oracle Cloud (External ATS)";
      filterPlat = "Oracle";
      badgeStyle = "background: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.4);";
    }

    return `<button type="button" class="platform-badge platform-badge-linkedin-ext btn-filter-platform" data-platform="${escapeHtml(filterPlat)}" style="${badgeStyle} font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; border-radius: 9999px; padding: 3px 9px; font-size: 11px;" title="Click to filter only ${escapeHtml(filterPlat)} roles">${extSvg} ${escapeHtml(atsName)}</button>`;
  }

  function updateBatchBarState() {
    const count = portalsState.selectedIds.size;
    const counterEl = document.getElementById("portals-selected-counter");
    const clearBtn = document.getElementById("btn-clear-selection");
    const deleteBtn = document.getElementById("btn-delete-selected");
    const deleteBtnCount = document.getElementById("btn-delete-selected-count");
    const applyBtn = document.getElementById("btn-apply-selected");
    const applyBtnText = document.getElementById("btn-apply-selected-text");
    const selectAllCb = document.getElementById("portals-select-all-checkbox");

    if (counterEl) {
      counterEl.textContent = `${count} selected`;
    }
    if (clearBtn) {
      clearBtn.style.display = count > 0 ? "inline-flex" : "none";
    }
    if (deleteBtn) {
      deleteBtn.style.display = count > 0 ? "inline-flex" : "none";
    }
    if (deleteBtnCount) {
      deleteBtnCount.textContent = count;
    }
    if (applyBtn) {
      if (count > 0) {
        applyBtn.style.opacity = "1";
        applyBtn.style.pointerEvents = "auto";
      } else {
        applyBtn.style.opacity = "0.5";
        applyBtn.style.pointerEvents = "none";
      }
    }
    if (applyBtnText) {
      applyBtnText.textContent = `Apply to Selected (${count}) ⚡`;
    }
    if (selectAllCb && portalsState.jobs.length > 0) {
      const allSelected = portalsState.jobs.every((j) => {
        const id = String(j.id != null ? j.id : (j.job_id || ""));
        return portalsState.selectedIds.has(id);
      });
      selectAllCb.checked = allSelected;
    }
  }

  function updatePortalCardStatus(jobId, status) {
    const strId = String(jobId);
    const card = document.querySelector(`.portal-card[data-id="${strId}"], .portal-card[data-stable-id="${strId}"]`);
    if (!card) return;
    const badge = card.querySelector(".portal-status-badge");
    if (badge) {
      badge.className = `badge portal-status-badge ${
        status === 'applied' ? 'badge-applied' : 
        status === 'applying' ? 'badge-applying' : 
        status === 'dry_run' || status === 'dry-run' ? 'badge-dry-run' : 
        status === 'failed' ? 'badge-failed' : 
        status === 'requires_manual' || status === 'challenge_detected' ? 'badge-manual' : 'badge-dry-run'
      }`;
      badge.textContent = status === 'dry_run' ? 'dry-run' : (status === 'challenge_detected' ? 'captcha' : status);
    }
    const btn = card.querySelector(".btn-apply-single");
    if (btn) {
      if (status === 'applying') {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-inline"></span> Applying...`;
        btn.style.opacity = "0.75";
      } else if (status === 'applied') {
        btn.disabled = true;
        btn.innerHTML = `<span>Applied ✓</span>`;
        btn.classList.remove("btn-primary");
        btn.classList.add("btn-secondary");
        btn.style.opacity = "1";
      } else if (status === 'dry_run' || status === 'dry-run') {
        btn.disabled = false;
        btn.innerHTML = `<span>Simulated ✓</span>`;
        btn.classList.remove("btn-primary");
        btn.classList.add("btn-secondary");
        btn.style.opacity = "1";
      } else if (status === 'failed' || status === 'requires_manual' || status === 'challenge_detected') {
        btn.disabled = false;
        btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> Retry Apply ⚡`;
        btn.classList.add("btn-primary");
        btn.classList.remove("btn-secondary");
        btn.style.opacity = "1";
      }
    }
  }

  async function executePortalApplyBot(jobIds, dryRun, triggerBtn) {
    if (!jobIds || !jobIds.length) return;
    if (state.audioEnabled && sfx) sfx.click();

    jobIds.forEach((jid) => {
      updatePortalCardStatus(jid, "applying");
    });

    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.innerHTML = `<span class="spinner-inline"></span> Applying...`;
      triggerBtn.style.opacity = "0.75";
    }

    const batchBtn = document.getElementById("btn-apply-selected");
    if (batchBtn && jobIds.length > 1) {
      batchBtn.disabled = true;
      batchBtn.style.opacity = "0.7";
      batchBtn.innerHTML = `<span class="spinner-inline"></span> Applying to ${jobIds.length}...`;
    }

    // Read Watch Bot toggle (default: true -> visible browser so user can watch form filling)
    const watchBot = document.getElementById("watch-bot-checkbox");
    const isVisible = watchBot ? watchBot.checked : true;
    const isBackground = !isVisible;

    try {
      showToast(`Launching Auto-Apply Bot for ${jobIds.length} job(s)...`, "info");
      const res = await authedFetch("/api/portals/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_ids: jobIds,
          dry_run: dryRun,
          background: isBackground,
          headless: isBackground,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      showToast(`Apply Bot active! Auto-filling forms...`, "success");

    } catch (err) {
      console.error("Portal apply bot failed:", err);
      showToast(`Apply Bot error: ${err.message}`, "error");
      jobIds.forEach((jid) => {
        updatePortalCardStatus(jid, "failed");
      });
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> Retry Apply ⚡`;
        triggerBtn.style.opacity = "1";
      }
    } finally {
      if (batchBtn) {
        updateBatchBarState();
      }
    }
  }

  async function executeDirectUrlApply(rawUrl, dryRun, triggerBtn) {
    let url = (rawUrl || "").trim();
    if (!url) {
      showToast("Please enter a valid job URL to apply", "warning");
      return;
    }
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      if (url.includes(".") && !url.includes(" ")) {
        url = "https://" + url;
      } else {
        showToast("URL must start with http:// or https://", "error");
        return;
      }
    }

    if (state.audioEnabled && sfx) sfx.click();

    // Read Watch Bot toggle (default: true -> visible browser so user can watch form filling)
    const watchBot = document.getElementById("watch-bot-checkbox");
    const isVisible = watchBot ? watchBot.checked : true;
    const isBackground = !isVisible;

    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.innerHTML = `<span class="spinner-inline"></span> Applying...`;
      triggerBtn.style.opacity = "0.75";
    }

    try {
      showToast("⚡ Connecting to direct job link & launching bot...", "info");
      const res = await authedFetch("/api/portals/apply-direct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url,
          dry_run: dryRun,
          background: isBackground,
          headless: isBackground,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      showToast(`🚀 1-Click Apply active for ${data.title || "Job"} @ ${data.company || "Employer"}!`, "success");

      // Reload portals to show new job card immediately
      await loadApplyPortals();
      if (typeof fetchFeaturedPortals === "function") await fetchFeaturedPortals();

    } catch (err) {
      console.error("Direct link apply error:", err);
      showToast(`1-Click Apply error: ${err.message}`, "error");
    } finally {
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> <span>1-Click Apply ⚡</span>`;
        triggerBtn.style.opacity = "1";
      }
    }
  }

  function renderPortalCardHtml(job, idx) {
    const jobId = String(job.id != null ? job.id : (job.job_id || idx));
    const stableId = String(job.stable_id || jobId);
    const isSelected = portalsState.selectedIds.has(jobId);
    const isEasy = (
      job.apply_type === 'Easy Apply' ||
      job.is_easy_apply === true ||
      job.platform_category === 'linkedin' ||
      (job.platform || '').toLowerCase().includes('easy apply')
    );
    const badgeHtml = getPlatformBadgeHtml(job.platform, job.platform_category, isEasy);
    const rawApplyUrl = job.apply_url || job.source_url || "#";
    const openFormHref = `/api/jobs/${encodeURIComponent(stableId)}/open-form`;
    const isFromLinkedIn = Boolean(
      isEasy ||
      job.platform_category === 'linkedin' ||
      (job.platform || '').toLowerCase().includes('linkedin') ||
      (job.source_name || '').toLowerCase().includes('linkedin') ||
      (job.url && job.url.includes('linkedin.com')) ||
      (job.apply_url && job.apply_url.includes('linkedin.com'))
    );
    const linkedinDigits = isFromLinkedIn ? ((String(stableId).startsWith("urn:li:") || String(stableId).includes("linkedin")) ? (String(stableId).match(/\d{6,15}/) || [])[0] : null) : null;
    const linkedinUrl = isFromLinkedIn ? (job.linkedin_url || (linkedinDigits ? `https://www.linkedin.com/jobs/view/${linkedinDigits}/` : (job.url && job.url.includes('linkedin.com') ? job.url : ''))) : '';
    const descText = (job.description || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    const snippet = descText.length > 200 ? descText.slice(0, 200) + "..." : descText || "No description preview available.";
    const matchPct = Math.round((job.match_score || 0.60) * 100);
    let matchBadgeClass = "badge-match-med";
    if (matchPct >= 80) matchBadgeClass = "badge-match-high";
    else if (matchPct < 60) matchBadgeClass = "badge-match-low";

    // Status badge mapping — explicit class per status
    const statusBadgeClass = ({
      'applied': 'badge-applied',
      'applying': 'badge-applying',
      'dry_run': 'badge-dry-run',
      'dry-run': 'badge-dry-run',
      'failed': 'badge-failed',
      'requires_manual': 'badge-manual',
      'challenge_detected': 'badge-manual',
      'skipped_low_fit': 'badge-skipped',
      'skipped': 'badge-skipped',
      'discovered': 'badge-discovered',
      'evaluated': 'badge-discovered',
    })[job.status] || 'badge-discovered';

    // Visually dim cards with low fit or skipped status
    const isLowFit = job.status === 'skipped_low_fit' || matchPct < 50;
    const cardDimClass = isLowFit ? 'portal-card-dimmed' : '';

    // Truncate failure_reason to avoid overflow
    const rawFailReason = job.failure_reason || '';
    const truncFailReason = rawFailReason.length > 110 ? rawFailReason.slice(0, 110) + '…' : rawFailReason;

    return `
      <div class="portal-card ${cardDimClass} ${isSelected ? 'is-selected' : ''}" data-idx="${idx}" data-id="${escapeHtml(jobId)}" data-stable-id="${escapeHtml(stableId)}">
        <div>
          <!-- Row 1: Checkbox + Platform Badge -->
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 7px; min-width: 0;">
            <input type="checkbox" class="portal-card-checkbox" data-id="${escapeHtml(jobId)}" data-idx="${idx}" ${isSelected ? 'checked' : ''} title="Select this portal for automated application" style="flex-shrink: 0;">
            <div style="flex: 1; min-width: 0; overflow: hidden;">
              ${badgeHtml}
            </div>
          </div>
          <!-- Row 2: Match % + Status Badge -->
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 10px; flex-wrap: wrap;">
            <span class="badge ${matchBadgeClass}" style="font-size: 11px; padding: 2px 7px; flex-shrink: 0;">
              ⚡ ${matchPct}% Match
            </span>
            <span class="badge portal-status-badge ${statusBadgeClass}" style="font-size: 10px; padding: 2px 7px; flex-shrink: 0; text-transform: uppercase; letter-spacing: 0.3px;">
              ${escapeHtml((job.status || 'discovered').replace(/_/g, ' '))}
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
          ${rawFailReason && job.status !== 'applied' && job.status !== 'dry_run' ? `
          <div style="margin-top: 8px; padding: 6px 10px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; font-size: 11px; color: #FCA5A5; display: flex; align-items: flex-start; gap: 6px; line-height: 1.4; word-break: break-word; overflow: hidden;">
            <span style="flex-shrink: 0;">⚠️</span>
            <span title="${escapeHtml(rawFailReason)}">${escapeHtml(truncFailReason)}</span>
          </div>` : ''}
        </div>

        <div style="display: flex; gap: 6px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06); flex-wrap: wrap; align-items: center;">
          <button class="btn btn-secondary btn-sm btn-view-desc" data-idx="${idx}" style="flex: 1; min-width: 78px; padding: 7px 8px; font-size: 11.5px;">
            View Details
          </button>
          ${job.proof_screenshot ? `
          <button class="btn btn-secondary btn-sm btn-view-proof" data-shot="${escapeHtml(job.proof_screenshot)}" data-title="${escapeHtml(job.title)}" data-company="${escapeHtml(job.company)}" data-reason="${escapeHtml(job.failure_reason || '')}" style="flex: 1; min-width: 74px; padding: 7px 8px; font-size: 11.5px; display: flex; align-items: center; justify-content: center; gap: 4px; color: #10B981; border-color: rgba(16, 185, 129, 0.4); cursor: pointer;" title="View verified application proof screenshot">
            Proof 📸
          </button>` : ''}
          ${isEasy ? `
          <a href="${escapeHtml(linkedinUrl || rawApplyUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="flex: 1.2; min-width: 120px; padding: 7px 8px; font-size: 11.5px; display: flex; align-items: center; justify-content: center; gap: 4px; text-decoration: none; color: #34D399; border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.08);" title="Open Easy Apply application directly on LinkedIn">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 8.76a1.64 1.64 0 1 0 0-3.28 1.64 1.64 0 0 0 0 3.28m1.4 9.74v-8.37H5.06v8.37z"/></svg>
            Easy Apply on LinkedIn ↗
          </a>` : `
          <a href="${escapeHtml(openFormHref)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="flex: 1; min-width: 82px; padding: 7px 8px; font-size: 11.5px; display: flex; align-items: center; justify-content: center; gap: 4px; text-decoration: none; color: #38BDF8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.08);" title="Open verified direct ATS application form">
            Apply Form ↗
          </a>
          ${linkedinUrl ? `
          <a href="${escapeHtml(linkedinUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="flex: 1; min-width: 78px; padding: 7px 8px; font-size: 11.5px; display: flex; align-items: center; justify-content: center; gap: 4px; text-decoration: none; color: #70B5F9; border-color: rgba(10, 102, 194, 0.4);" title="View original job post on LinkedIn">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 8.76a1.64 1.64 0 1 0 0-3.28 1.64 1.64 0 0 0 0 3.28m1.4 9.74v-8.37H5.06v8.37z"/></svg>
            LinkedIn ↗
          </a>` : ''}
          `}
          <button class="btn btn-primary btn-sm btn-apply-single" data-id="${escapeHtml(jobId)}" data-stable-id="${escapeHtml(stableId)}" style="flex: 1.1; min-width: 100px; padding: 7px 9px; font-size: 11.5px; display: flex; align-items: center; justify-content: center; gap: 4px; font-weight: 700;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            Apply ⚡
          </button>
          <button class="btn btn-sm btn-delete-single" data-id="${escapeHtml(jobId)}" data-stable-id="${escapeHtml(stableId)}" data-title="${escapeHtml(job.title)}" data-company="${escapeHtml(job.company)}" title="Delete this opportunity" style="padding: 7px 10px; color: #FFFFFF; background: #DC2626; border: 1px solid #EF4444; display: flex; align-items: center; justify-content: center; gap: 4px; cursor: pointer; font-weight: 700; border-radius: 6px; font-size: 11.5px;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>
    `;
  }

  function renderApplyPortals(jobs) {
    const grid = document.getElementById("portals-cards-grid");
    if (!grid) return;

    if (!jobs || jobs.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 48px; color: var(--text-muted); background: rgba(15, 23, 42, 0.4); border-radius: 12px; border: 1px dashed var(--border);">
          <div style="font-size: 16px; font-weight: 600; color: #FFFFFF; margin-bottom: 6px;">No application portals found</div>
          <div style="font-size: 13px;">Try selecting a different platform or searching for a role above.</div>
        </div>
      `;
      return;
    }

    let html = "";
    if (portalsState.viewMode === "grouped") {
      const groups = {};
      jobs.forEach((j, idx) => {
        let pName = "Direct ATS";
        const p = (j.platform || "").toLowerCase();
        const isEasy = (j.apply_type === 'Easy Apply' || j.is_easy_apply === true || j.platform_category === 'linkedin' || p.includes('easy apply'));
        if (isEasy) {
          pName = "LinkedIn (Easy Apply)";
        } else if (p.includes("greenhouse")) {
          pName = "Greenhouse";
        } else if (p.includes("ashby")) {
          pName = "Ashby";
        } else if (p.includes("lever")) {
          pName = "Lever";
        } else if (p.includes("workday")) {
          pName = "Workday";
        } else if (p.includes("smartrecruiters")) {
          pName = "SmartRecruiters";
        } else if (p.includes("icims")) {
          pName = "iCIMS";
        } else if (p.includes("oracle")) {
          pName = "Oracle Cloud";
        } else if (p.includes("linkedin")) {
          pName = "LinkedIn (External Form)";
        } else if (j.platform) {
          pName = j.platform;
        }
        if (!groups[pName]) groups[pName] = [];
        groups[pName].push({ job: j, idx });
      });

      const platformMeta = {
        "Greenhouse": { icon: "🌿", color: "#34D399", border: "rgba(16, 185, 129, 0.4)", bg: "rgba(16, 185, 129, 0.15)", desc: "Direct Greenhouse ATS forms with verified field mapping & submission endpoints" },
        "Ashby": { icon: "⚡", color: "#C084FC", border: "rgba(168, 85, 247, 0.4)", bg: "rgba(168, 85, 247, 0.15)", desc: "Ashby HQ applicant portals with automated candidate resume injection" },
        "Lever": { icon: "🟧", color: "#FB923C", border: "rgba(249, 115, 22, 0.4)", bg: "rgba(249, 115, 22, 0.15)", desc: "Lever modern ATS opportunities with instant candidate profile sync" },
        "Workday": { icon: "🔷", color: "#60A5FA", border: "rgba(59, 130, 246, 0.4)", bg: "rgba(59, 130, 246, 0.15)", desc: "Enterprise Workday portal forms with deep field mapping & automation" },
        "SmartRecruiters": { icon: "✨", color: "#F472B6", border: "rgba(236, 72, 153, 0.4)", bg: "rgba(236, 72, 153, 0.15)", desc: "SmartRecruiters 1-click apply compatible careers pages" },
        "iCIMS": { icon: "🌐", color: "#22D3EE", border: "rgba(6, 182, 212, 0.4)", bg: "rgba(6, 182, 212, 0.15)", desc: "iCIMS talent cloud direct application links" },
        "Oracle Cloud": { icon: "🔴", color: "#F87171", border: "rgba(239, 68, 68, 0.4)", bg: "rgba(239, 68, 68, 0.15)", desc: "Oracle Cloud enterprise career portals" },
        "LinkedIn (Easy Apply)": { icon: "⚡", color: "#34D399", border: "rgba(16, 185, 129, 0.4)", bg: "rgba(16, 185, 129, 0.15)", desc: "1-Click native Easy Apply application forms on LinkedIn" },
        "LinkedIn (External Form)": { icon: "🌐", color: "#38BDF8", border: "rgba(56, 189, 248, 0.4)", bg: "rgba(56, 189, 248, 0.15)", desc: "External company application forms linked from LinkedIn postings" },
      };

      for (const [pName, itemsList] of Object.entries(groups)) {
        const meta = platformMeta[pName] || {
          icon: "🌐",
          color: "#38BDF8",
          border: "rgba(56, 189, 248, 0.4)",
          bg: "rgba(56, 189, 248, 0.15)",
          desc: `Direct application forms hosted on ${escapeHtml(pName)}`
        };

        html += `
          <div style="grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; margin-top: 20px; margin-bottom: 8px; background: rgba(15, 23, 42, 0.9); border: 1px solid ${meta.border}; border-radius: 12px; box-shadow: 0 4px 14px rgba(0,0,0,0.25); flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <span style="font-size: 22px;">${meta.icon}</span>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 15.5px; font-weight: 700; color: #FFFFFF;">${escapeHtml(pName)}</span>
                  <span class="badge" style="background: ${meta.bg}; color: ${meta.color}; font-weight: 700; font-size: 11px; padding: 2px 9px; border-radius: 9999px;">
                    ${itemsList.length} roles
                  </span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                  ${meta.desc}
                </div>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <button class="btn btn-secondary btn-sm btn-group-select-all" data-platform="${escapeHtml(pName)}" style="font-size: 11.5px; padding: 5px 12px; font-weight: 600;">
                Select All in ${escapeHtml(pName)}
              </button>
              <button class="btn btn-secondary btn-sm btn-filter-only-platform" data-platform="${escapeHtml(pName)}" style="font-size: 11.5px; padding: 5px 12px; color: ${meta.color}; border-color: ${meta.border}; font-weight: 600;">
                Filter only ${escapeHtml(pName)}
              </button>
            </div>
          </div>
        `;
        html += itemsList.map(item => renderPortalCardHtml(item.job, item.idx)).join("");
      }
    } else {
      const isAllTab = (!portalsState.category || portalsState.category === "all");
      const extJobsWithIdx = [];
      const easyJobsWithIdx = [];

      jobs.forEach((j, idx) => {
        const isEasy = (j.platform_category === "linkedin" || (j.platform || "").toLowerCase().includes("easy apply"));
        if (isEasy) {
          easyJobsWithIdx.push({ job: j, idx });
        } else {
          extJobsWithIdx.push({ job: j, idx });
        }
      });

      if (isAllTab && extJobsWithIdx.length > 0 && easyJobsWithIdx.length > 0) {
        html += `
          <div style="grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; margin-top: 4px; margin-bottom: 4px; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 10px;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 17px;">🌐</span>
              <span style="font-size: 14.5px; font-weight: 700; color: #FFFFFF;">Direct External Form Portals (ATS & Careers)</span>
              <span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38BDF8; font-size: 11.5px; padding: 2px 8px; border-radius: 9999px;">${extJobsWithIdx.length} roles</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">External ATS portals (Ashby, Workday, Greenhouse, Lever, Oracle)</div>
          </div>
        `;
        html += extJobsWithIdx.map(item => renderPortalCardHtml(item.job, item.idx)).join("");

        html += `
          <div style="grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; margin-top: 24px; margin-bottom: 4px; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 17px;">⚡</span>
              <span style="font-size: 14.5px; font-weight: 700; color: #FFFFFF;">LinkedIn Easy Apply Portals</span>
              <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #34D399; font-size: 11.5px; padding: 2px 8px; border-radius: 9999px;">${easyJobsWithIdx.length} roles</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">1-Click in-app application forms on LinkedIn</div>
          </div>
        `;
        html += easyJobsWithIdx.map(item => renderPortalCardHtml(item.job, item.idx)).join("");
      } else {
        html = jobs.map((job, idx) => renderPortalCardHtml(job, idx)).join("");
      }
    }

    grid.innerHTML = html;

    // Attach click listeners to clickable platform badges
    grid.querySelectorAll(".btn-filter-platform").forEach((badge) => {
      badge.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const plat = badge.getAttribute("data-platform");
        if (plat) setPlatformFilter(plat);
      });
    });

    // Attach click listeners to grouped view platform buttons
    grid.querySelectorAll(".btn-filter-only-platform").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const plat = btn.getAttribute("data-platform");
        if (plat) setPlatformFilter(plat);
      });
    });

    grid.querySelectorAll(".btn-group-select-all").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const plat = (btn.getAttribute("data-platform") || "").toLowerCase();
        const groupJobs = jobs.filter((j) => {
          const p = (j.platform || "").toLowerCase();
          const isEasy = (j.apply_type === 'Easy Apply' || j.is_easy_apply === true || j.platform_category === 'linkedin' || p.includes('easy apply'));
          if (plat.includes("easy apply")) return isEasy;
          if (plat.includes("external form")) return (!isEasy && (p.includes("linkedin") || j.platform_category === "linkedin"));
          return p.includes(plat);
        });

        const allSelected = groupJobs.length > 0 && groupJobs.every((j) => {
          const id = String(j.id != null ? j.id : (j.job_id || ""));
          return portalsState.selectedIds.has(id);
        });

        groupJobs.forEach((j) => {
          const id = String(j.id != null ? j.id : (j.job_id || ""));
          if (id) {
            if (allSelected) {
              portalsState.selectedIds.delete(id);
            } else {
              portalsState.selectedIds.add(id);
            }
          }
        });

        renderApplyPortals(portalsState.jobs);
        updateBatchBarState();
      });
    });

    // Attach click listeners to "View Details" buttons
    grid.querySelectorAll(".btn-view-desc").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        const job = jobs[idx];
        if (job) openJobModal(job);
      });
    });

    // Attach click listeners to individual "Delete" buttons
    grid.querySelectorAll(".btn-delete-single").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id") || btn.getAttribute("data-stable-id");
        const company = btn.getAttribute("data-company") || "Company";
        const title = btn.getAttribute("data-title") || "this role";
        const card = btn.closest(".portal-card");
        await deleteSinglePortal(id, company, title, card);
      });
    });

    // Attach change listeners to card checkboxes
    grid.querySelectorAll(".portal-card-checkbox").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-id");
        const card = cb.closest(".portal-card");
        if (cb.checked) {
          portalsState.selectedIds.add(id);
          if (card) card.classList.add("is-selected");
        } else {
          portalsState.selectedIds.delete(id);
          if (card) card.classList.remove("is-selected");
        }
        updateBatchBarState();
      });
    });

    // Attach click listeners to individual "Apply with Bot ⚡" buttons
    grid.querySelectorAll(".btn-apply-single").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        const dryRunCb = document.getElementById("portals-dryrun-checkbox");
        const dryRun = dryRunCb ? dryRunCb.checked : false;
        await executePortalApplyBot([id], dryRun, btn);
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
    const modalLinkedIn = document.getElementById("modal-linkedin-link");

    const isEasy = (
      job.apply_type === 'Easy Apply' ||
      job.is_easy_apply === true ||
      job.platform_category === 'linkedin' ||
      (job.platform || '').toLowerCase().includes('easy apply')
    );

    if (modalBadge) {
      modalBadge.innerHTML = getPlatformBadgeHtml(job.platform, job.platform_category, isEasy);
    }
    if (modalTitle) modalTitle.textContent = job.title;
    if (modalSubtitle) modalSubtitle.textContent = `${job.company} • ${job.location || "Remote"}`;
    if (modalDesc) {
      const cleanDesc = (job.description || "").replace(/<[^>]*>/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
      modalDesc.textContent = cleanDesc || "No detailed job description captured.";
    }
    const stableId = job.stable_id || job.id || job.job_id || "";
    const isFromLinkedInModal = Boolean(
      isEasy ||
      job.platform_category === 'linkedin' ||
      (job.platform || '').toLowerCase().includes('linkedin') ||
      (job.source_name || '').toLowerCase().includes('linkedin') ||
      (job.url && job.url.includes('linkedin.com')) ||
      (job.apply_url && job.apply_url.includes('linkedin.com'))
    );
    const liDigits = isFromLinkedInModal ? ((String(stableId).startsWith("urn:li:") || String(stableId).includes("linkedin")) ? (String(stableId).match(/\d{6,15}/) || [])[0] : null) : null;
    const liUrl = isFromLinkedInModal ? (job.linkedin_url || (liDigits ? `https://www.linkedin.com/jobs/view/${liDigits}/` : '')) : '';

    if (modalApply) {
      if (isEasy) {
        modalApply.href = liUrl || job.apply_url || "https://www.linkedin.com/jobs/";
        modalApply.innerHTML = `<span>Easy Apply on LinkedIn ↗</span>`;
        modalApply.style.color = "#34D399";
        modalApply.style.borderColor = "rgba(16, 185, 129, 0.45)";
        modalApply.style.background = "rgba(16, 185, 129, 0.08)";
      } else {
        modalApply.href = `/api/jobs/${encodeURIComponent(stableId)}/open-form`;
        modalApply.innerHTML = `<span>Apply Form ↗</span>`;
        modalApply.style.color = "#38BDF8";
        modalApply.style.borderColor = "rgba(56, 189, 248, 0.45)";
        modalApply.style.background = "rgba(56, 189, 248, 0.08)";
      }
    }
    if (modalLinkedIn) {
      if (isEasy) {
        modalLinkedIn.style.display = "none";
      } else if (liUrl) {
        modalLinkedIn.href = liUrl;
        modalLinkedIn.style.display = "inline-flex";
      } else {
        modalLinkedIn.style.display = "none";
      }
    }

    const modalProof = document.getElementById("modal-proof-btn");
    if (modalProof) {
      if (job.proof_screenshot) {
        modalProof.style.display = "inline-flex";
        modalProof.onclick = () => {
          openProofModal(job.proof_screenshot, job.title, job.company, job.failure_reason);
        };
      } else {
        modalProof.style.display = "none";
      }
    }

    const modalDeleteBtn = document.getElementById("modal-delete-btn");
    if (modalDeleteBtn) {
      modalDeleteBtn.onclick = async () => {
        closeJobModal();
        const id = job.id != null ? job.id : (job.job_id || "");
        await deleteSinglePortal(id, job.company, job.title);
      };
    }

    modal.style.display = "flex";
  }

  function closeJobModal() {
    const modal = document.getElementById("job-modal-overlay");
    if (modal) modal.style.display = "none";
  }

  function openProofModal(screenshotPath, title, company, reason) {
    const modal = document.getElementById("proof-modal-overlay");
    if (!modal) return;
    const img = document.getElementById("proof-modal-img");
    const titleEl = document.getElementById("proof-modal-title");
    const subEl = document.getElementById("proof-modal-subtitle");

    const filename = String(screenshotPath).replace(/^.*[\\/]/, "");
    const imgUrl = `/api/proofs/${encodeURIComponent(filename)}`;

    if (img) {
      img.src = imgUrl;
    }
    if (titleEl) {
      const isBlocked = filename.includes("blocked");
      titleEl.innerHTML = isBlocked ? "⚠️ Application Audit Blocker" : "✅ Application Verified Proof";
      titleEl.style.color = isBlocked ? "#F87171" : "#10B981";
    }
    if (subEl) {
      subEl.textContent = `${title || 'Job Application'} • ${company || ''} ${reason ? `• Reason: ${reason}` : ''}`;
    }

    modal.style.display = "flex";
  }

  function closeProofModal() {
    const modal = document.getElementById("proof-modal-overlay");
    if (modal) modal.style.display = "none";
  }

  // Delegated click for any .btn-view-proof
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-view-proof");
    if (btn) {
      e.preventDefault();
      const shot = btn.getAttribute("data-shot");
      const title = btn.getAttribute("data-title") || "";
      const company = btn.getAttribute("data-company") || "";
      const reason = btn.getAttribute("data-reason") || "";
      if (shot) {
        openProofModal(shot, title, company, reason);
      }
    }
  });

  const proofCloseBtn = document.getElementById("proof-modal-close-btn");
  if (proofCloseBtn) proofCloseBtn.addEventListener("click", closeProofModal);
  const proofDismissBtn = document.getElementById("proof-modal-dismiss-btn");
  if (proofDismissBtn) proofDismissBtn.addEventListener("click", closeProofModal);
  const proofOverlay = document.getElementById("proof-modal-overlay");
  if (proofOverlay) {
    proofOverlay.addEventListener("click", (e) => {
      if (e.target === proofOverlay) closeProofModal();
    });
  }

  // ── Portal Deletion Actions (Individual, Batch, All) ─────────────
  async function deleteSinglePortal(jobId, company, title, cardEl) {
    if (!jobId) return;
    const confirmMsg = `Delete "${title || 'this role'}" at ${company || 'Company'}?`;
    if (!window.confirm(confirmMsg)) return;

    if (state.audioEnabled && sfx) sfx.click();
    try {
      showToast(`Deleting opportunity at ${company}...`, "info");
      const res = await authedFetch("/api/apply-portals/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

      showToast(`Opportunity deleted successfully.`, "success");
      portalsState.selectedIds.delete(String(jobId));

      if (cardEl) {
        cardEl.style.transition = "all 0.25s ease";
        cardEl.style.opacity = "0";
        cardEl.style.transform = "scale(0.96)";
        setTimeout(() => {
          cardEl.remove();
          updateBatchBarState();
          loadApplyPortals();
        }, 250);
      } else {
        loadApplyPortals();
      }
    } catch (err) {
      console.error("Delete single portal failed:", err);
      showToast(`Failed to delete: ${err.message}`, "error");
    }
  }

  async function deleteSelectedPortals() {
    const selected = Array.from(portalsState.selectedIds);
    if (!selected.length) return;

    const confirmMsg = `Are you sure you want to delete ${selected.length} selected opportunit${selected.length > 1 ? 'ies' : 'y'}?`;
    if (!window.confirm(confirmMsg)) return;

    if (state.audioEnabled && sfx) sfx.click();
    try {
      showToast(`Deleting ${selected.length} selected opportunities...`, "info");
      const res = await authedFetch("/api/apply-portals/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: selected }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

      showToast(`Deleted ${data.deleted_count || selected.length} opportunities successfully.`, "success");
      portalsState.selectedIds.clear();
      updateBatchBarState();
      loadApplyPortals();
    } catch (err) {
      console.error("Delete selected portals failed:", err);
      showToast(`Failed to delete selected: ${err.message}`, "error");
    }
  }

  async function deleteAllPortals() {
    const totalCount = document.getElementById("stat-apply-total")?.textContent || "all";
    const confirmMsg = `Are you sure you want to delete ALL (${totalCount}) opportunities in this view? This action cannot be undone.`;
    if (!window.confirm(confirmMsg)) return;

    if (state.audioEnabled && sfx) sfx.click();
    try {
      showToast("Deleting all opportunities...", "info");
      const res = await authedFetch("/api/apply-portals/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          all: true,
          category: portalsState.category,
          platform: portalsState.platform,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

      showToast(`All opportunities deleted (${data.deleted_count || 0} removed).`, "success");
      portalsState.selectedIds.clear();
      portalsState.grandTotals = null;  // force re-fetch of grand totals
      updateBatchBarState();
      loadApplyPortals();
    } catch (err) {
      console.error("Delete all portals failed:", err);
      showToast(`Failed to delete all: ${err.message}`, "error");
    }
  }

  // ── Mission Control High-Fit Portals Feed ─────────────────────────
  async function loadMissionFeaturedJobs() {
    const container = document.getElementById("mission-featured-portals");
    if (!container) return;

    try {
      const res = await authedFetch("/api/apply-portals?limit=6&min_score=0.60");
      if (!res.ok) return;
      const data = await res.json();

      const badgeCount = document.getElementById("nav-badge-portals");
      if (badgeCount && data.total != null) {
        badgeCount.textContent = data.total;
      }

      const jobs = data.jobs || [];
      if (jobs.length === 0) {
        container.innerHTML = `
          <div class="featured-portals-empty">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--text-dim); margin-bottom: 4px;">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <div style="font-weight: 600; color: var(--text-main);">No matched opportunities yet</div>
            <div style="font-size: 11px; color: var(--text-muted);">Click "Start Run" or "Search in Chrome" to discover live listings.</div>
          </div>
        `;
        return;
      }

      container.innerHTML = jobs
        .map((job, idx) => {
          const matchPct = Math.round((job.match_score || 0.60) * 100);
          let matchBadgeClass = "chip-emerald";
          if (matchPct < 70) matchBadgeClass = "chip-cyan";
          if (matchPct >= 80) matchBadgeClass = "chip-emerald";

          const platformBadge = getPlatformBadgeHtml(job.platform, job.platform_category);
          const stableId = job.stable_id || job.id;
          const rawApplyUrl = job.apply_url || job.source_url || "#";
          const openFormHref = `/api/jobs/${encodeURIComponent(stableId)}/open-form`;
          const linkedinDigits = (String(stableId).match(/\d{6,15}/) || String(job.id || '').match(/\d{6,15}/) || [])[0];
          const linkedinUrl = job.linkedin_url || (linkedinDigits ? `https://www.linkedin.com/jobs/view/${linkedinDigits}/` : '');

          return `
            <div class="featured-portal-card" data-idx="${idx}">
              <div class="portal-card-header">
                ${platformBadge}
                <span class="metric-chip ${matchBadgeClass}">
                  ⚡ ${matchPct}% Fit
                </span>
              </div>
              <div class="portal-body">
                <div class="portal-role">${escapeHtml(job.title)}</div>
                <div class="portal-company-loc">${escapeHtml(job.company)} • ${escapeHtml(job.location || 'Remote')}</div>
              </div>
              <div class="portal-actions">
                <a href="${escapeHtml(openFormHref)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-xs" style="text-decoration: none; color: #38BDF8; border-color: rgba(56, 189, 248, 0.4);" title="Open direct application form">
                  <span>Apply Form ↗</span>
                </a>
                ${linkedinUrl ? `
                <a href="${escapeHtml(linkedinUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-xs" style="text-decoration: none; color: #70B5F9; border-color: rgba(10, 102, 194, 0.4); display: inline-flex; align-items: center; gap: 3px;" title="View original job post on LinkedIn">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 8.76a1.64 1.64 0 1 0 0-3.28 1.64 1.64 0 0 0 0 3.28m1.4 9.74v-8.37H5.06v8.37z"/></svg>
                  <span>LinkedIn ↗</span>
                </a>` : ''}
                <button class="btn btn-secondary btn-xs btn-featured-view" data-idx="${idx}">
                  <span>View Details</span>
                </button>
                <button class="btn btn-primary btn-xs btn-featured-apply" data-id="${escapeHtml(String(stableId))}">
                  <span>Apply with Bot</span>
                </button>
              </div>
            </div>
          `;
        })
        .join("");

      // Wire up clicks on the featured cards
      container.querySelectorAll(".btn-featured-view").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = parseInt(btn.getAttribute("data-idx"), 10);
          if (jobs[idx]) openJobModal(jobs[idx]);
        });
      });

      container.querySelectorAll(".btn-featured-apply").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const stableId = btn.getAttribute("data-id");
          const dryRun = els.dryRunCheckbox ? els.dryRunCheckbox.checked : true;
          await executePortalApplyBot([stableId], dryRun, btn);
        });
      });
    } catch (err) {
      console.error("Failed to load featured jobs:", err);
    }
  }

  // ── 3D Card Perspective Tilt Effect (Hardware-accelerated RAF) ──────
  function init3DTiltEffects() {
    if (window.matchMedia("(pointer: coarse)").matches) return;

    let ticking = false;

    document.addEventListener("mousemove", (e) => {
      const card = e.target.closest(".bento-card, .featured-portal-card, .candidate-cockpit-bar");
      if (!card) return;

      if (!ticking) {
        window.requestAnimationFrame(() => {
          const rect = card.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;

          const centerX = rect.width / 2;
          const centerY = rect.height / 2;

          const rotateX = ((y - centerY) / centerY) * -4.5;
          const rotateY = ((x - centerX) / centerX) * 4.5;

          card.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) scale3d(1.008, 1.008, 1.008)`;
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });

    document.addEventListener("mouseout", (e) => {
      const card = e.target.closest(".bento-card, .featured-portal-card, .candidate-cockpit-bar");
      if (card && (!e.relatedTarget || !card.contains(e.relatedTarget))) {
        card.style.transform = "";
      }
    }, { passive: true });
  }

  // ── Lifecycle Boot ────────────────────────────────────────────────
  function init() {
    initListeners();
    initSSE();
    loadStatus();
    loadMissionFeaturedJobs();
    init3DTiltEffects();

    setInterval(loadStatus, 10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
