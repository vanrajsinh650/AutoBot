---
name: autobot-frontend
description: Autonomous Agent Mission Control UI & Telemetry Design. Use when building, modifying, polishing, or extending real-time web dashboards for autonomous agents, LangGraph state machines, browser automation bots, and RAG vector systems.
---

# AutoBot Frontend: Mission Control & Agent Telemetry Architecture

A specialized engineering guide and design system for high-density, real-time autonomous agent control centers.

## 1. Core Design Philosophy: "Operate Mode"

Mission control dashboards for autonomous agents are operational cockpits, not marketing landing pages. They must convey system state with zero ambiguity:

- **Telemetry Density**: Every pixel delivers system information. Avoid card sprawl, empty padding, and gratuitous decorations.
- **No Generic AI Tells**: Strictly eliminate violet/purple card gradients on dark backgrounds, clipped gradient text, neon drop shadows, and oversized decorative icons.
- **WCAG AA Compliance**: High contrast colors ensuring all operational text is legible (body >= 4.5:1, large headings >= 3:1).
- **Tabular Numerals**: Always apply `font-variant-numeric: tabular-nums` to numerical counters, scores, and timestamps to eliminate layout jitter during high-frequency telemetry updates.
- **Semantic State Palette**:
  - `var(--primary)` (`#10b981` Emerald): Active execution, successful apply, passing criteria.
  - `var(--cyan)` (`#06b6d4` Sky): Informational logs, company tags, vector retrieval counts.
  - `var(--dry-run)` (`#8b5cf6` Violet): Simulated dry-run states, mock transitions.
  - `var(--warning)` (`#f59e0b` Amber): Skipped applications, low match scores, manual overrides.
  - `var(--danger)` (`#ef4444` Crimson): Execution failures, missing credentials, cancelled runs.

---

## 2. Real-Time Telemetry Pipeline (Server-Sent Events)

Autonomous agents run asynchronous multi-step execution graphs. The frontend must stream state changes without polling loops:

```
┌─────────────────────────────────┐           SSE Stream (/api/events)
│      LangGraph Execution        │──────────────────────────────────────────┐
│ (search → filter → eval → apply)│                                          │
└─────────────────────────────────┘                                          ▼
                                                          ┌───────────────────────────────────┐
                                                          │   Mission Control Dashboard       │
                                                          │ 1. Active Node Highlight          │
                                                          │ 2. Telemetry Terminal Feed        │
                                                          │ 3. Counter Metrics Increment      │
                                                          └───────────────────────────────────┘
```

### Event Contracts:
- `event: status`: Transmits `{ state: "running" | "idle", node: "<current_node>" }`. Updates sidebar pulse dot, top-bar start/stop buttons, and the LangGraph pipeline visualization chips.
- `event: log`: Transmits `{ level: "info" | "success" | "warning" | "error", message: "...", timestamp: "..." }`. Appends structured log entries to the virtual terminal feed with automatic scrolling.

---

## 3. Four Core Operational Views

### View 1: Mission Control (`#view-mission`)
- **Metric Cards (Grid 4x1)**: Total Applications, Applied (Live), Dry Run (Simulated), Skipped / Low Fit.
- **State Machine Pipeline Visualizer**: Horizontal flow diagram displaying:
  `1. SEARCH` → `2. FILTER` → `3. EVALUATE` → `4. APPLY` → `5. RECORD` → `6. ADVANCE`
  The current node glows with `var(--primary)` and a subtle ambient ring when active.
- **Live Telemetry Terminal**: Dark monospaced console with auto-scroll and 300-entry memory cap.

### View 2: Applications Board (`#view-applications`)
- **Filterable Controls**: 300ms debounced text search (matches role or company) + status dropdown filter.
- **Audit Table**:
  - Columns: ID, Role, Company, Location, Apply Method, Match Score, Status, Timestamp.
  - Match scores are formatted into tiered pills:
    - `>= 80%`: High fit (`.match-pill.high`)
    - `>= 60%`: Mid fit (`.match-pill.mid`)
    - `< 60%`: Low fit (`.match-pill.low`)
  - Server-side offset/limit pagination with live record counting.

### View 3: Candidate Profile & Vector Memory (`#view-profile`)
- **Ingestion Telemetry**: Verifies resume PDF existence on disk, chunk count, and embedding dimensions.
- **Semantic Memory Explorer**:
  - Skills section rendered as interactive tag cloud (`.skill-tag`).
  - Experience and Projects displayed as semantic role chunks (`.chunk-card`).
  - Action trigger: "Sync Ingestion" button to re-parse and upsert into Qdrant vector DB.

### View 4: Agent Settings (`#view-settings`)
- **Interactive Configuration Editor**: Two-way binding with `config.yaml`.
  - Search keywords, target location, max applications per run.
  - Live range slider for minimum match score threshold (`0.0` to `1.0`).
  - Screening overrides: Expected salary, years of experience, work authorization, sponsorship, notice period.
  - Cache-busting save action with receipt toast notification.

---

## 4. Verification Checklist

When building or updating the AutoBot frontend:
1. [ ] **Color Contrast**: Verify all body text achieves >= 4.5:1 contrast against `#080b10` and `#0e131b`.
2. [ ] **No Generic AI Tells**: Ensure cards use solid borders (`#202b3d`) without gratuitous violet gradients.
3. [ ] **Interactive States**: Every button, input, and slider has explicit `:hover`, `:focus`, and `:disabled` styling.
4. [ ] **Tabular Numerals**: Numerical counters, scores, and percentages use `font-variant-numeric: tabular-nums`.
5. [ ] **SSE Resilience**: Disconnections automatically re-establish connection after a 4-second backoff.
6. [ ] **All Tests Pass**: Run `pytest tests/test_web.py` to confirm HTML serving, static assets, and REST endpoints.
