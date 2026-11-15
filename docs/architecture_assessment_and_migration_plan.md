# AutoBot v2.2.1: Architecture Assessment, Migration Plan & Verification Report

## 1. Executive Summary & Repository Audit
AutoBot has transitioned from an initial single-tenant script into an enterprise-grade, multi-tenant career automation platform:
- **LangGraph Agent Workflow** (`src/agent/`): Directed cyclic state graph (`START -> search -> filter -> evaluate -> apply -> record -> advance`).
- **Memory & Ingestion** (`src/ingestion/`, `src/memory/`): Document parsing with `pdfplumber`, regex section extraction, and embedding storage in Qdrant with `FormRAG`, `JobMatcher`, and `CoverLetterGenerator`.
- **Browser Automation & CDP Abstraction** (`src/browser/`): Pluggable backend architecture delegating between **Chromium** (production default) and **Obscura v0.2.7** (experimental CDP engine), enforcing automatic fallback and zero-stealth compliance.
- **Persistence & Multi-Tenancy** (`src/storage/`): ACID SQLite schema with tenant isolation across 12 tables, bcrypt password hashing, fail-closed JWT tokens, session revocation, and cryptographically chained audit trails.
- **Web Mission Control** (`src/web/`): Real-time `aiohttp` dashboard with Server-Sent Events (SSE) telemetry, browser health monitoring, and administrative engine controls.
- **Test Suite Health**: **176 passed, 1 skipped** (177 automated tests), preserving the 148-test baseline with zero regressions.

---

## 2. Completed Milestones (v2.0 -> v2.2.1)

- [x] **Milestone 1 — Multi-Tenant Schema & Migrations**: 12 tables (`users`, `candidate_profiles`, `resume_versions`, `resume_evidence`, `job_preferences`, `job_sources`, `jobs`, `job_requirements`, `match_evaluations`, `application_packs`, `application_events`, `audit_logs`). Backward-compatible migration preserving legacy data.
- [x] **Milestone 2 — Candidate Onboarding & Structured Ingestion**: Multi-user resume document storage with path-traversal protection, magic byte header validation (`%PDF`), and candidate profile correction APIs.
- [x] **Milestone 3 — Public ATS Discovery**: Public API adapters for **Greenhouse**, **Lever**, and **Ashby**, plus manual job import, stable ID generation, and SHA-256 fingerprint deduplication.
- [x] **Milestone 4 — Deterministic Fit Scoring**: 5-component weighted formula (Required Skills 35%, Responsibilities 25%, Target Role 15%, Experience/Education 15%, Preferred Skills 10%) calculated in pure Python.
- [x] **Milestone 5 — Truthful Application Material Preparation**: Application packs featuring tailored summaries, authentic experience highlights, and cover letters strictly grounded in candidate evidence. Enforces human candidate approval before marking ready.
- [x] **Milestone 6 — Compliance & Anti-Bot Halting**: Zero automated browser interaction on LinkedIn. Immediate fail-closed stop on CAPTCHA, Cloudflare Turnstile, and MFA challenges.
- [x] **Milestone 7 — Mission Control UI**: Interactive dashboard supporting multi-tenant views, job discovery, match breakdowns, and real-time SSE telemetry feeds.
- [x] **Milestone 8 — Security & Privacy Hardening**: Fail-closed token authentication, rate limiting/brute force defense, PII sanitization in logs/SSE, and GDPR right-to-erasure account deletion.
- [x] **Milestone 9 — Obscura Browser Backend (v2.2)**: Lightweight headless Obscura v0.2.7 runner via CDP with strict loopback binding and ephemeral profile lifecycle.
- [x] **Milestone 10 — Mission Control Telemetry & Verification (v2.2.1)**: Real-time browser health pill, administrator-only engine controls, and end-to-end verification across two isolated candidate journeys.

---

## 3. Browser Backend Architecture & Security Policies

```
                          ┌─────────────────────────────┐
                          │       BrowserManager        │
                          │   (Default: ChromiumBackend)│
                          └──────────────┬──────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
   ┌───────────────────────────┐                   ┌───────────────────────────┐
   │      ChromiumBackend      │                   │      ObscuraBackend       │
   │   (Production Default)    │                   │   (Experimental v0.2.7)   │
   │                           │                   │                           │
   │ • Playwright Persistent   │                   │ • Headless Obscura binary │
   │   Context                 │                   │ • CDP over 127.0.0.1      │
   │ • Automatic fallback      │                   │ • Ephemeral profile (0700)│
   │   target                  │                   │ • Auto-wiped on close     │
   └───────────────────────────┘                   └───────────────────────────┘
```

### Browser Engine Policies & Guarantees:
1. **Chromium is the Primary Default**: Chromium is always used unless explicitly configured otherwise by an authorized administrator.
2. **Automatic Fallback strictly at Startup**: If Obscura is selected but fails binary check, process launch, or health verification, BrowserManager automatically falls back to Chromium *before* any application actions are initiated.
3. **Mid-Application Switching Strictly Forbidden**: Browser engines cannot be switched while an application workflow is actively in progress (`execution_manager.is_running = True`).
4. **Strict Loopback Binding**: Obscura is bound exclusively to `127.0.0.1` on an ephemeral dynamically assigned port. It is never exposed to public or non-loopback interfaces.
5. **Zero Stealth / Anti-Detection**: The `--stealth` flag is strictly forbidden and never passed to the Obscura CLI.
6. **Fail-Closed LinkedIn Gate**: All browser engines abort network requests to `linkedin.com` and `lnkd.in` at the network routing layer and reject navigation upfront.
7. **Anti-Bot Challenge Circuit Breakers**: If CAPTCHA, Cloudflare, Turnstile, or MFA challenges are detected, execution halts immediately with `AntiBotChallengeDetected` without attempting bypass.

---

## 4. Known Limitations of the Obscura Backend
- **Experimental Status**: Obscura is designated strictly as experimental and is restricted to third-party company ATS career portals (Greenhouse, Lever, Ashby).
- **V8 DOM DataTransfer Limitations**: Some headless DOM operations lack native DataTransfer bindings; file uploads utilize direct CDP `DOM.setFileInputFiles` fallback.
- **Admin Restriction**: Normal candidates cannot select or toggle Obscura; engine switching is restricted to authenticated administrators.
