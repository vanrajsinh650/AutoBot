/**
 * AutoBot Sovereign v3 — Next-Gen 3D Cyber-Industrial Controller
 * Architecture: 3D Particle Mesh · Web Audio Synthesizer · 3D Tilt Physics · Reactive SSE
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
    btnStop: document.getElementById("btn-stop-run"),
    btnForceIngest: document.getElementById("btn-force-ingest"),
    btnQuickUpload: document.getElementById("btn-quick-upload"),
    btnSwitchAccount: document.getElementById("btn-switch-account"),
    btnHeroLaunch: document.getElementById("btn-hero-launch"),
    btnHeroUpload: document.getElementById("btn-hero-upload"),
    heroHandCard: document.getElementById("hero-hand-card"),

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
      applications: "Applications Hologrid",
      profile: "Candidate Profile & Vector Memory",
      settings: "Agent Parameters",
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
    if (viewName === "profile") loadProfile();
    if (viewName === "settings") loadConfig();
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
      const res = await fetch("/api/status");
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
    } catch (err) {
      console.error("Failed to load status:", err);
    }
  }

  // ── Agent Run Actions ─────────────────────────────────────────────
  async function startAgentRun(forceIngest = false) {
    const dryRun = els.dryRunCheckbox.checked;
    sfx.launch();
    try {
      setRunningState(true);
      const res = await fetch("/api/run", {
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
      const res = await fetch("/api/stop", { method: "POST" });
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

  // ── Applications Hologrid ─────────────────────────────────────────
  async function loadJobs() {
    const query = encodeURIComponent(els.jobsSearch.value.trim());
    const status = encodeURIComponent(els.jobsStatusFilter.value.trim());
    const limit = state.jobsLimit;
    const offset = state.jobsOffset;

    try {
      const res = await fetch(`/api/jobs?limit=${limit}&offset=${offset}&status=${status}&q=${query}`);
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
        <td colspan="8" style="text-align: center; color: var(--text-dim); padding: 45px;">
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
      if (st === "applied") badgeClass = "badge-applied";
      else if (st === "dry_run") badgeClass = "badge-dry-run";
      else if (st === "failed") badgeClass = "badge-failed";

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
      const res = await fetch("/api/profile");
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

      const res = await fetch("/api/upload", {
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
      const res = await fetch("/api/config");
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
      const res = await fetch("/api/config", {
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

  // ── 3D Card Tilt Physics ──────────────────────────────────────────
  function init3DTiltPhysics() {
    const tiltElements = document.querySelectorAll(".tilt-card, #hero-hand-card");

    tiltElements.forEach((el) => {
      el.addEventListener("mousemove", (e) => {
        const rect = el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;

        const rotateX = ((y - centerY) / centerY) * -12;
        const rotateY = ((x - centerX) / centerX) * 12;

        el.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03, 1.03, 1.03)`;
      });

      el.addEventListener("mouseleave", () => {
        el.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)";
      });
    });
  }

  // ── 3D Background Neural Particle Mesh Canvas ─────────────────────
  function init3DParticleCanvas() {
    const canvas = document.getElementById("canvas-3d-bg");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const numParticles = Math.min(85, Math.floor((width * height) / 18000));
    const particles = [];
    const fov = 350;

    for (let i = 0; i < numParticles; i++) {
      particles.push({
        x: (Math.random() - 0.5) * width * 1.5,
        y: (Math.random() - 0.5) * height * 1.5,
        z: Math.random() * 800 + 50,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        vz: (Math.random() - 0.5) * 0.8,
        radius: Math.random() * 1.8 + 1,
      });
    }

    let mouseX = 0;
    let mouseY = 0;
    window.addEventListener("mousemove", (e) => {
      mouseX = (e.clientX - width / 2) * 0.05;
      mouseY = (e.clientY - height / 2) * 0.05;
    });

    function animate() {
      ctx.clearRect(0, 0, width, height);

      // Render 3D particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx + mouseX * 0.01;
        p.y += p.vy + mouseY * 0.01;
        p.z += p.vz;

        if (p.z <= 0) p.z = 850;
        if (p.z > 850) p.z = 10;

        const scale = fov / (fov + p.z);
        const screenX = p.x * scale + width / 2;
        const screenY = p.y * scale + height / 2;

        if (screenX >= 0 && screenX <= width && screenY >= 0 && screenY <= height) {
          ctx.beginPath();
          ctx.arc(screenX, screenY, p.radius * scale, 0, Math.PI * 2);
          const alpha = (1 - p.z / 850) * 0.5;
          ctx.fillStyle = i % 2 === 0 ? `rgba(16, 185, 129, ${alpha})` : `rgba(6, 182, 212, ${alpha})`;
          ctx.fill();

          // Connect nearby particles in 3D
          for (let j = i + 1; j < particles.length; j++) {
            const p2 = particles[j];
            const dx = p.x - p2.x;
            const dy = p.y - p2.y;
            const dz = p.z - p2.z;
            const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);

            if (dist < 150) {
              const scale2 = fov / (fov + p2.z);
              const screenX2 = p2.x * scale2 + width / 2;
              const screenY2 = p2.y * scale2 + height / 2;

              ctx.beginPath();
              ctx.moveTo(screenX, screenY);
              ctx.lineTo(screenX2, screenY2);
              const lineAlpha = (1 - dist / 150) * 0.15 * (1 - p.z / 850);
              ctx.strokeStyle = `rgba(52, 211, 153, ${lineAlpha})`;
              ctx.lineWidth = 0.8;
              ctx.stroke();
            }
          }
        }
      }

      requestAnimationFrame(animate);
    }

    animate();
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

    if (els.btnSwitchAccount) {
      els.btnSwitchAccount.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to log out and switch your LinkedIn account? This will clear the saved browser session so you can log into your alternative account.")) {
          return;
        }
        sfx.click();
        try {
          const res = await fetch("/api/logout", { method: "POST" });
          const data = await res.json();
          if (res.ok) {
            sfx.success();
            showToast("Session cleared! Next run will open a fresh login page for your alternative account.");
            appendLog("warning", "LinkedIn session cleared. Enter alternative account credentials on next run.");
            loadStatus();
          } else {
            showToast(data.error || "Logout failed", "error");
          }
        } catch (err) {
          showToast(`Error: ${err.message}`, "error");
        }
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
  }

  // ── Lifecycle Boot ────────────────────────────────────────────────
  function init() {
    initListeners();
    init3DParticleCanvas();
    init3DTiltPhysics();
    initSSE();
    loadStatus();

    setInterval(loadStatus, 10000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
