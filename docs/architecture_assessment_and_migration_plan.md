# AutoBot v2: Architecture Assessment & Migration Plan

## 1. Executive Summary & Repository Audit
The existing AutoBot codebase was initially constructed as a personal, single-tenant automation tool. It features:
- **LangGraph Agent Workflow** (`src/agent/`): A directed cyclic state graph (`START -> search -> filter -> evaluate -> apply -> record -> advance`).
- **Memory & Ingestion** (`src/ingestion/`, `src/memory/`): PDF parsing via `pdfplumber`, regex section detection, and embedding storage in Qdrant with `FormRAG`, `JobMatcher`, and `CoverLetterGenerator`.
- **Browser Automation** (`src/browser/`): Playwright-based actuators for LinkedIn search, Easy Apply modal forms, and external application links.
- **Persistence** (`src/storage/db.py`): A single-tenant SQLite database (`logs/autobot.db`) with tables `applications` and `sessions`.
- **Web Dashboard** (`src/web/`): An `aiohttp` web server providing REST endpoints and Server-Sent Events (SSE) log streaming to a static single-page application (`index.html`, `app.js`, `app.css`).
- **Gateway Integration** (`src/utils/llm_factory.py`): Orbit AI Gateway support via `OrbitCleanChatAnthropic` on `http://localhost:4981`, plus OpenAI and Gemini providers.
- **Existing Test Suite**: 73 passing unit tests spanning agent graph, browser mocks, vector embedder, scrapers, memory, pipeline, resume parser, and web routes.

## 2. Identified Gaps & Architectural Constraints
1. **Single-Tenant Assumption**:
   - `logs/autobot.db` has no `user_id` or tenant partitioning.
   - `config.yaml` is global; modifying configuration affects all runs.
   - Resumes are placed in a shared single path (`data/resume/resume.pdf`).
   - Qdrant collection is single-tenant (`autobot_profile`).
2. **LinkedIn Compliance & Automation Risk**:
   - The original code included LinkedIn automated browser scraping, login automation, and Easy Apply form actuation.
   - The mandated scope strictly forbids automated browser control, Playwright, CDP, DOM extraction, or credential storage for LinkedIn.
   - LinkedIn applications must transition to a user-assisted workflow: AutoBot prepares materials, answers, and checklists; the candidate applies and confirms directly.
3. **External Job Discovery**:
   - The original tool only had LinkedIn job search via Playwright.
   - Needs official/public API adapters for Greenhouse, Lever, Ashby, and user-supplied descriptions, with deduplication and normalization.
4. **Deterministic Fit Scoring**:
   - Original scoring relied directly on raw LLM prompt responses or basic cosine similarity.
   - Required scoring: strict deterministic mathematical formula (Required Skills 35%, Responsibilities 25%, Target Role 15%, Experience/Education 15%, Preferred Skills 10%) calculated in Python, using LLM strictly for requirement/evidence extraction.
5. **Security & Privacy**:
   - Need user authentication, secure session handling, audit logging, tenant-scoped file storage, credential/PII redaction in logs/SSE, and non-destructive SQLite schema migrations.

## 3. Migration Plan
- **Phase 1 (Milestone 1)**: Database migrations and multi-user models (`users`, `candidate_profiles`, `resume_versions`, `resume_evidence`, `job_preferences`, `job_sources`, `jobs`, `job_requirements`, `match_evaluations`, `application_packs`, `application_events`, `audit_logs`). Backward-compatible migration preserving existing `applications` and `sessions`.
- **Phase 2 (Milestone 2)**: Candidate onboarding, multi-user resume storage, structured parser with manual correction APIs, and configurable preference models.
- **Phase 3 (Milestone 3)**: Job discovery engine with adapters for Greenhouse, Lever, Ashby, and manual import. Stable deduplication IDs.
- **Phase 4 (Milestone 4)**: Eligibility rules engine (internship/full-time, country eligibility) and deterministic 0–100 Resume Fit Scorer.
- **Phase 5 (Milestone 5)**: Application preparation engine creating tailored resume variants, truthful experience descriptions, cover letters, and Q&A checklists.
- **Phase 6 (Milestone 6)**: LinkedIn manual workflow and authorized external ATS workflow with human review and anti-bot challenge stops.
- **Phase 7 (Milestone 7)**: Mission Control web dashboard upgrade supporting multi-tenant views, candidate profiles, discovery, match breakdown, and workflow progression.
- **Phase 8 (Milestone 8)**: Security hardening, tenant isolation enforcement, audit trails, PII/credential sanitization, and data deletion/export.
- **Phase 9 (Milestone 9)**: Verification: all 73 legacy tests must pass, plus comprehensive new test suites covering multi-tenancy, scoring, discovery, security, and compliance.
