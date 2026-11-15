# 🤖 AutoBot v2 — Autonomous LinkedIn Job Application Agent

AutoBot is a **fully agentic** LinkedIn job application system built from the ground up using **LangGraph**, **LangChain**, **Qdrant**, and **Playwright**.

Feed it your resume PDF, LinkedIn profile, and portfolio URL. AutoBot ingests your background into long-term vector memory, evaluates job postings against your real experience, and autonomously applies to both **Easy Apply** and **external company career portals** with grounded AI form filling.

---

## 🏗 Architecture & Engineering Stack

```
AutoBot/
├── main.py                          # CLI Entry point (--ingest-only, --dry-run, --force)
├── config.yaml                      # User search preferences, answers, and thresholds
├── .env                             # Credentials (OpenAI / Gemini, LinkedIn, Qdrant)
├── docker-compose.yml               # Local Qdrant vector database container
├── setup.sh                         # One-command environment setup script
├── data/
│   ├── resume/resume.pdf            # Candidate resume PDF
│   └── session/linkedin_state.json  # Authenticated Playwright session cache
├── logs/
│   ├── autobot.db                   # SQLite transactional application database
│   └── autobot_YYYYMMDD.log         # Rich diagnostics log file
└── src/
    ├── ingestion/                   # Step 2: Ingestion & Vector Indexing
    │   ├── models.py                # DocumentChunk & IngestionSource schemas
    │   ├── resume_parser.py         # PDF parsing & 7-section extraction (pdfplumber)
    │   ├── linkedin_scraper.py      # Authenticated Playwright profile scraper
    │   ├── portfolio_scraper.py     # DOM-sanitizing web scraper (BeautifulSoup)
    │   ├── embedder.py              # Dynamic vector dimension Qdrant upsert engine
    │   └── pipeline.py              # End-to-end ingestion orchestrator
    ├── memory/                      # Step 3: Long-Term Memory & RAG
    │   ├── models.py                # RetrievedChunk, FormQuestion, FormAnswer, JobMatchEvaluation
    │   ├── retriever.py             # Dense Qdrant vector search with section/source filtering
    │   ├── form_rag.py              # 3-tier form answering engine (Overrides → RAG → Fallback)
    │   ├── job_matcher.py           # Cognitive job evaluation & match scoring (0.0 - 1.0)
    │   └── cover_letter.py          # Grounded cover letter generator
    ├── agent/                       # Step 4: LangGraph State Machine
    │   ├── state.py                 # AgentState, JobPosting, ApplicationOutcome
    │   ├── edges.py                 # should_apply, after_record, and after_advance routers
    │   ├── nodes/
    │   │   ├── search.py            # Job vacancy discovery
    │   │   ├── filter.py            # Deduplication & blacklist fast-path rejection
    │   │   ├── evaluate.py          # Semantic evaluation calling JobMatcher
    │   │   ├── apply.py             # Safe simulation or live form submission
    │   │   ├── record.py            # ACID SQLite persistence
    │   │   └── advance.py           # Multi-page pagination & keyword stepping
    │   └── graph.py                 # StateGraph compilation & session summary renderer
    ├── browser/                     # Step 5: Computer Use & Web Actuators
    │   ├── manager.py               # Playwright Chromium manager with anti-bot stealth
    │   ├── navigator.py             # Login verification, search URL builder, DOM card parsing
    │   ├── easy_apply_actuator.py   # Multi-step LinkedIn modal runner with FormRAG
    │   ├── external_apply_actuator.py# Third-party ATS portal form submitter
    │   └── bridge.py                # Adapter bridging Playwright actuators to LangGraph
    ├── web/                         # Step 6: Mission Control Web Dashboard & Telemetry
    │   ├── server.py                # aiohttp web server application setup
    │   ├── routes.py                # REST API endpoints & SSE live event broadcaster
    │   └── static/                  # Operate-mode frontend design system
    │       ├── index.html           # Single-page mission control cockpit
    │       ├── app.css              # WCAG AA dark-mode stylesheet & design tokens
    │       └── app.js               # Reactive SSE controller & state sync
    └── utils/
        ├── config.py                # Pydantic typed configuration loader
        ├── llm_factory.py           # Pluggable LLM/Embeddings factory (OpenAI ↔ Gemini)
        ├── logger.py                # Rich console & file logger
        └── human_behavior.py        # Anti-detection jitter & human typing simulation
```

---

## 🔄 LangGraph State Machine Flow

```
                      START
                        │
                        ▼
                     [search] ◄───────────────┐
                        │                     │
                        ▼                     │ (pagination / next keyword)
                     [filter] ◄────────┐      │
                        │              │      │
                        ▼              │      │
                    [evaluate]         │      │
                        │              │      │
                (should_apply?)        │      │
                 /            \        │      │
              (yes)          (no)      │      │
               /                \      │      │
           [apply]               │     │      │
               \                /      │      │
                ▼              ▼       │      │
                    [record]           │      │
                        │              │      │
                 (after_record?)       │      │
                 /      |      \       │      │
          (session cap) (queue) (empty)│      │
                /       |        \     │      │
              END       └─────► [advance] ────┘
```

---

## 🚀 Quick Start Guide

### 1. One-Command Setup
```bash
cd /home/vanrajsinh/Projects/AutoBot
bash setup.sh
```

### 2. Configure Credentials (`.env`)
Copy `.env.example` to `.env` and fill in:
```ini
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
LINKEDIN_PROFILE_URL=https://www.linkedin.com/in/your-profile-id

# Choose your AI brain: "openai" or "gemini"
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# Qdrant Vector Database
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=autobot_profile
```

### 3. Add Your Resume
Place your PDF resume at:
```bash
data/resume/resume.pdf
```

### 4. Configure Search Preferences (`config.yaml`)
Customize your target keywords, location, minimum match score, and standard answers:
```yaml
search:
  keywords:
    - "Backend Engineer"
    - "Python Developer"
  location: "India"
  remote: true

apply:
  min_match_score: 0.60
  max_applications: 25
  answers:
    years_of_experience: "4"
    expected_salary: "20 LPA"
    notice_period: "30 days"
```

### 5. Execution Modes

#### Step A: Ingest Profile into Vector Memory
```bash
source .venv/bin/activate
python main.py --ingest-only
```

#### Step B: Dry-Run Inspection (Simulate without applying)
```bash
python main.py --dry-run
```

#### Step C: Full Autonomous Run
```bash
python main.py
```

#### Step D: Mission Control Web Dashboard (Interactive Telemetry Cockpit)
Launch the real-time web dashboard on `http://127.0.0.1:8000`:
```bash
python main.py --ui
```
- **Mission Control**: Live SSE event log feed, LangGraph visual pipeline highlight, and aggregate counters.
- **Applications Board**: Filterable search and pagination over applied, dry-run, skipped, and failed jobs.
- **Candidate Memory & Ingestion**: Vector DB status, extracted chunks, and interactive skill tag cloud.
- **Live Settings Editor**: Real-time two-way editing of search criteria, salary expectations, and match thresholds.

---

## 🧪 Comprehensive Test Suite

Run the full 64-test automated regression suite:
```bash
pytest -v
```

All 64 unit and integration tests pass cleanly with zero network dependencies:
- **Ingestion Suite**: 24 tests
- **Memory & RAG Suite**: 15 tests
- **LangGraph Agent Suite**: 10 tests
- **Browser Automation Suite**: 6 tests
- **Web Mission Control Suite**: 9 tests
