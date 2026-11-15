# 🤖 AutoBot v2.2.1 — Multi-Tenant Autonomous Career Platform & Discovery Engine

AutoBot is an enterprise-grade autonomous job discovery, fit evaluation, and application preparation platform powered by **LangGraph**, **Qdrant**, **Playwright**, and **aiohttp**.

It features multi-tenant data isolation, fail-closed authentication, public ATS job discovery (Greenhouse, Lever, Ashby), deterministic 5-component qualification scoring, truthful application preparation, and pluggable browser backends with automatic Chromium fallback.

---

## 🏗 Architecture & Engineering Stack

```
AutoBot/
├── main.py                          # CLI & Web Server Entry point (--ui, --ingest-only, --dry-run)
├── config.yaml                      # System search preferences, answers, and thresholds
├── .env                             # Credentials & Environment Variables
├── docker-compose.yml               # Local Qdrant vector database container
├── setup.sh                         # Environment setup script
├── bin/                             # Headless browser binaries (obscura, obscura-worker)
├── data/
│   ├── users/<id>/resumes/          # Isolated, tenant-partitioned candidate resumes (0700)
│   ├── obscura_profiles/            # Ephemeral isolated browser sessions (auto-wiped)
│   └── session/                     # Browser session state storage
├── logs/
│   ├── autobot.db                   # SQLite multi-tenant transactional database
│   └── autobot_YYYYMMDD.log         # Rich diagnostics log file
└── src/
    ├── discovery/                   # Public Job Discovery Engine
    │   ├── models.py                # NormalizedJob, JobSourceConfig schemas
    │   ├── registry.py              # Discovery orchestrator & SHA-256 deduplication
    │   └── adapters/                # Greenhouse, Lever, Ashby, and Manual adapters
    ├── matching/                    # Deterministic Scoring & Eligibility
    │   ├── scorer.py                # 5-component weighted formula (0–100)
    │   ├── eligibility.py           # Country, location, and employment type gates
    │   └── evaluator.py             # Match breakdown with transparent explanation
    ├── application/                 # Application Materials Preparation
    │   ├── preparation.py           # Truthful tailored summaries, cover letters, Q&A drafts
    │   └── workflows.py             # Compliance gates & user-approval requirements
    ├── browser/                     # Pluggable Browser Automation & CDP Abstraction
    │   ├── base_backend.py          # BrowserBackend base interface
    │   ├── backends/
    │   │   ├── chromium_backend.py  # Production default Playwright Chromium & fallback target
    │   │   └── obscura_backend.py   # Experimental Obscura v0.2.7 CDP headless engine
    │   ├── manager.py               # Session manager with automatic startup fallback
    │   └── external_apply_actuator.py# Third-party ATS portal form assistant
    ├── storage/                     # Multi-Tenant Persistence & Security
    │   ├── db.py                    # Multi-tenant SQLite repository with hard test isolation
    │   ├── auth.py                  # JWT session tokens, bcrypt hashing, brute-force limits
    │   └── migrations.py            # Backward-compatible 12-table schema migrations
    ├── web/                         # Mission Control Web Cockpit
    │   ├── server.py                # aiohttp web server & auth middleware
    │   ├── routes.py                # REST endpoints, SSE stream, browser health telemetry
    │   └── static/                  # Responsive WCAG AA dashboard (HTML/CSS/JS)
    └── utils/
        ├── security.py              # PII redaction, secret masking, GDPR data erasure
        ├── config.py                # Pydantic typed configuration loader
        └── logger.py                # Rich console & file logger
```

---

## 🎯 Core Features & Innovations

### 1. Multi-Tenant Architecture & Fail-Closed Security
- **Strict Tenant Boundary**: Resumes, profiles, preferences, evaluations, and tracker events are partitioned per `user_id` with 0700 file system permissions.
- **Fail-Closed Authentication**: Cryptographically signed bearer tokens, instant session revocation, and brute-force protection.
- **Audit Logging**: Cryptographically chained SHA-256 audit logs with user anonymity on account deletion (GDPR Right to Erasure).

### 2. Multi-Source Job Discovery & Deduplication
- Integrates directly with official public APIs for **Greenhouse**, **Lever**, and **Ashby**, plus manual job import.
- Handles rate-limiting (HTTP 429) and transient errors (500/502/503) with exponential backoff.
- Multi-tier deduplication: exact `stable_id` matching + canonical content SHA-256 fingerprinting.

### 3. Deterministic 0–100 Resume Fit Scoring
Calculated in pure Python using transparent mathematical formulas:
$$\text{Fit Score} = 0.35 \times \text{ReqSkills} + 0.25 \times \text{Responsibilities} + 0.15 \times \text{TargetRole} + 0.15 \times \text{ExpEdu} + 0.10 \times \text{PrefSkills}$$
- Canonical skill aliases (e.g., `k8s` $\leftrightarrow$ `kubernetes`, `py` $\leftrightarrow$ `python`).
- Disclaims hiring probabilities; provides transparent explanations and missing requirements.

### 4. Pluggable Browser Backends (Chromium Default + Obscura CDP)
- **ChromiumBackend (Default)**: Production-hardened Playwright persistent context.
- **ObscuraBackend (Experimental v0.2.7)**: Lightweight headless runner connected via Chrome DevTools Protocol (CDP) over loopback `127.0.0.1`.
- **Automatic Fallback**: If Obscura fails startup or health checks, BrowserManager falls back seamlessly to Chromium prior to application actions.
- **Zero Stealth**: Anti-detection evasion (`--stealth`) is strictly forbidden.
- **Compliance & Safety**: Automated browser interaction on LinkedIn is strictly prohibited. Halts immediately on CAPTCHA, Cloudflare, or MFA challenges.
- **Admin Locking**: Engine configuration is restricted to system administrators and locked during active application runs.

---

## 🚀 Quick Start Guide

### 1. Launch Mission Control Dashboard
```bash
python main.py --ui --port 8000
```
Navigate to `http://127.0.0.1:8000`:
- **Mission Control**: Live SSE telemetry terminal, metrics cards, and real-time browser health pill.
- **Applications Board**: Filterable search, status tracking, and pagination.
- **Candidate Profile**: Document upload with magic byte verification (`%PDF`), structured skills, and experience viewer.
- **Discovery**: On-demand sync across Greenhouse, Lever, Ashby, and manual URLs.
- **Settings**: Preference configuration and Administrator Browser Engine controls.

### 2. Run Comprehensive Test Suite
```bash
.venv/bin/pytest -v
```
**176 passed, 1 skipped** across 24 test suites covering:
- Unit & integration tests for agent graphs, discovery adapters, and memory models.
- Multi-tenant security, token revocation, IDOR prevention, and data privacy.
- Browser provider abstraction, Obscura CDP lifecycle, process cleanup, and fallback.
- End-to-end two-user isolated journey and Mission Control telemetry UI.
