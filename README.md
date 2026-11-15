# 🤖 AutoBot v2.3 — Real-World Job Discovery & Intelligent Matching

AutoBot is an enterprise-grade autonomous job discovery, fit evaluation, and application preparation platform powered by **LangGraph**, **Qdrant**, **Playwright**, and **aiohttp**.

It features multi-tenant data isolation, fail-closed authentication, public ATS job discovery (Greenhouse, Lever, Ashby) protected by SSRF guards, company board registry with concurrency semaphores, job freshness & expiration tracking, explainable personalized keyword expansion, deterministic 5-component qualification scoring with a 60-pair evaluation benchmark, truthful application preparation, and pluggable browser backends.

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
│   ├── benchmarks/                  # 60-pair curated matching quality dataset
│   │   └── matching_eval_dataset.json
│   ├── users/<id>/resumes/          # Isolated, tenant-partitioned candidate resumes (0700)
│   ├── obscura_profiles/            # Ephemeral isolated browser sessions (auto-wiped)
│   └── session/                     # Browser session state storage
├── logs/
│   ├── autobot.db                   # SQLite multi-tenant transactional database
│   └── autobot_YYYYMMDD.log         # Rich diagnostics log file
└── src/
    ├── discovery/                   # Public Job Discovery Engine & SSRF Protection
    │   ├── models.py                # NormalizedJob, JobSourceConfig schemas
    │   ├── security.py              # SSRF guard, domain whitelisting, RFC 6052 NAT64 support, size capping
    │   ├── board_registry.py        # Configurable ATS board registry & concurrency control
    │   ├── registry.py              # Discovery orchestrator, freshness & expiration tracking
    │   └── adapters/                # Greenhouse, Lever, Ashby, and Manual adapters
    ├── matching/                    # Deterministic Scoring & Personalized Search
    │   ├── scorer.py                # 5-component weighted formula (0–100)
    │   ├── eligibility.py           # Country, location, and employment type gates
    │   ├── evaluator.py             # Match breakdown with negation and alias handling
    │   ├── keyword_expansion.py     # Skill taxonomy, explainable expansion & tenant search
    │   └── benchmark.py             # Automated 60-pair benchmark harness (100% reproducible)
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
    │   └── migrations.py            # Backward-compatible 14-table schema migrations
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

### 2. Real ATS Discovery, SSRF Protection & Board Registry
- **Public ATS Adapters**: Integrates with live public APIs for **Greenhouse**, **Lever**, and **Ashby**.
- **Comprehensive SSRF Defense**: Enforces HTTPS schemes, strict domain whitelisting, regex validation on slugs, 10MB response size capping, and DNS resolution egress checks blocking private IPs (RFC 1918), loopback, link-local, AWS/GCP cloud metadata (`169.254.169.254`), with RFC 6052 NAT64 / DNS64 translation verification.
- **Company Board Registry**: Persistent SQLite management of company boards (`job_sources`), sync intervals, failure tracking, and concurrency semaphores.
- **Freshness & Expiration Tracking**: Tracks `discovered_at`, `source_updated_at`, and `last_verified_at`. Detects expired vacancies on legitimate removal while guaranteeing network failures NEVER trigger false deletions.

### 3. Personalized Keyword Expansion & Search
- **Curated Skill & Role Taxonomy**: Expands skills (e.g., Python $\rightarrow$ FastAPI, PyTorch; AI $\rightarrow$ LLM, LangChain; Java $\rightarrow$ Spring Boot) into related frameworks and industry titles.
- **Employment & Tier Isolation**: Distinguishes internships, full-time, part-time, and contract vacancies; tenant-isolated search queries.
- **Explainable & Transparent**: Provides human-readable justifications for every synonym and allows manual candidate keyword additions.

### 4. Deterministic Fit Scoring & 60-Pair Benchmark Suite
Calculated in pure Python using transparent mathematical formulas:
$$\text{Fit Score} = 0.35 \times \text{ReqSkills} + 0.25 \times \text{Responsibilities} + 0.15 \times \text{TargetRole} + 0.15 \times \text{ExpEdu} + 0.10 \times \text{PrefSkills}$$
- Canonical skill aliases (e.g., `k8s` $\leftrightarrow$ `kubernetes`, `py` $\leftrightarrow$ `python`).
- Negation guards: detects "no python required", "strictly not used", and "without java".
- **60-Pair Curated Benchmark**: 100% mathematical reproducibility, 0 false positives, 0 false negatives, and explicit identification of cases where candidate has high technical fit but is strictly `INELIGIBLE` due to country or visa constraints.
- **Disclaimer**: Strictly disclaims hiring probabilities; provides transparent explanations and missing requirements.

### 5. Pluggable Browser Backends (Chromium Default + Obscura CDP)
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
- **Mission Control**: Live SSE telemetry terminal, metrics cards, real-time browser health pill.
- **Job Discovery Cockpit**: Source health cards with sync timestamps, vacancy counts, keyword expansion tags, and status/score/workplace filters.
- **Applications Board**: Filterable search, status tracking, and pagination.
- **Candidate Profile**: Document upload with magic byte verification (`%PDF`), structured skills, and experience viewer.
- **Settings**: Preference configuration and Administrator Browser Engine controls.

### 2. Run Comprehensive Test Suite
```bash
.venv/bin/pytest -v -m "not live_integration"
```
**184 passed, 3 deselected, 21 warnings** across 26 test suites covering:
- Unit & integration tests for agent graphs, discovery adapters, and memory models.
- Multi-tenant security, token revocation, IDOR prevention, and data privacy.
- Browser provider abstraction, Obscura CDP lifecycle, process cleanup, and fallback.
- SSRF protection, response capping, expiration tracking, and tenant-isolated keyword search.
- 60-pair matching quality benchmark with 100% mathematical reproducibility.

To run opt-in live integration tests against actual public ATS boards:
```bash
.venv/bin/pytest -v -m live_integration
```
