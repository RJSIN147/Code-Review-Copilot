# Architecture & Codebase Map

This document describes how **Code Review Copilot** is structured and how a pull
request flows through it. It complements the high-level overview in the
[README](../README.md) with an implementation-accurate map of the code.

> Reviewed against the codebase on 2026-06-26. If you change the review engine,
> the API surface, or the task pipeline, update this file in the same PR.

---

## 1. What it is

An autonomous AI code-review service. You submit a GitHub PR; it fetches the PR
(metadata, changed files + diffs, existing comments) via the GitHub API,
runs a **multi-agent LLM review** over the changed files, stores the findings,
and (optionally) posts them back as an inline GitHub review.

Everything the reviewer needs is fetched **once** from the GitHub API up front.
The review agents never clone the repo and never make per-tool network calls —
their tools answer purely from data already in memory.

---

## 2. Request lifecycle

```
HTTP                          Celery worker (one persistent event loop)
────                          ─────────────────────────────────────────
POST /api/v1/analyze-pr
  └─ insert AnalysisTask (PENDING)
  └─ analyze_pr_task.delay(...)  ───────────►  analyze_pr_task()  [app/tasks/analyze_tasks.py]
       returns 202 + task_id                     1. status → PROCESSING
                                                  2. GitHubService.get_pull_request_metadata()
                                                  3. + get_pull_request_comments()  (for dedup)
                                                  4. get_pull_request_files()  (diffs)
                                                  5. per file: fetch content from head repo@sha
                                                     (skip binary / >1000 changed lines)
                                                  6. LangGraphAnalyzer.analyze_pr(...)  ◄── AI engine
                                                  7. save AnalysisResult + AnalysisSummary
                                                  8. if post_comments + token:
                                                       GitHubReviewService.build_review/post_review
                                                  9. status → COMPLETED (100%)

GET /api/v1/status/{id}     ◄─ polled by the frontend (SWR) while PROCESSING
GET /api/v1/results/{id}    ◄─ full findings once COMPLETED
```

Progress is written to the `AnalysisTask` row in bands: 0–30% fetch metadata/files,
30–60% collect file contents, 60–95% AI analysis (advanced per file via a
progress callback), 95–100% save + post.

### Async-on-Celery detail
Celery prefork workers are synchronous, but almost everything here is `async`
(asyncpg, the LLM client). `run_async_in_celery()` runs every coroutine on a
**single persistent event loop owned by the worker process**, so asyncpg
connections stay bound to one loop across the many awaits in a task. Don't
replace this with `asyncio.run()` per call — that reintroduces cross-loop errors.

---

## 3. Component map (the codebase)

```
app/
├── main.py                     FastAPI app factory, CORS, lifespan, /health, /
├── api/v1/
│   ├── router.py               mounts /api/v1 (analyze + status routers)
│   └── endpoints/
│       ├── analyze.py          POST /analyze-pr · DELETE /tasks/{id} · GET /tasks
│       └── status.py           GET /status/{id} · /results/{id} · /results/{id}/summary
│
├── agents/                     ◄── THE AI REVIEW ENGINE (see §4)
│   ├── analyzer.py             LangGraphAnalyzer — thin public entrypoint
│   ├── ai_workflow.py          LangGraph state machine: triage → review → synthesize
│   ├── review_orchestrator.py  Orchestrator agent: delegates/decides + consolidates
│   └── tools/
│       ├── review_tools.py     ReviewToolbox (read-only PR-data tools) + tool specs
│       ├── ai_tools.py         ⚠ legacy/unused (see §8)
│       └── python_tools.py     ⚠ legacy/unused, ~380 lines (see §8)
│
├── services/
│   ├── github.py               GitHubService — PyGithub wrapper, rate-limit tracking,
│   │                           repo/PR/file fetch, Redis cache of repo lookups
│   ├── github_review.py        GitHubReviewService — build + POST inline PR review
│   └── llm_service.py          LLMService — per-file sub-agent (tool loop + structured out)
│
├── tasks/
│   ├── celery_app.py           Celery config (Redis broker/back end, time limits)
│   └── analyze_tasks.py        analyze_pr_task — the end-to-end orchestration glue
│
├── models/
│   ├── database.py             SQLModel tables + enums (TaskStatus/IssueType/IssueSeverity)
│   └── schemas.py              Pydantic request/response DTOs
│
├── config/
│   ├── settings.py             TOML + $ENV substitution → nested Pydantic Settings (cached)
│   └── database.py             async engine / session manager
│
└── utils/
    ├── diff_parser.py          patch → visible new-file line numbers (for inline comments)
    ├── language_detection.py   filename/content → language
    ├── logger.py               Loguru setup
    ├── redis_client.py         sync Redis client factory
    └── exceptions.py           domain exceptions + FastAPI handlers

frontend/   React 19 + TS + Vite + Tailwind v4 + SWR (submit form, task list, results)
tests/      unit (diff parser, language detection, github services, models, config)
            + integration (status endpoints)
migrations/ Alembic
```

---

## 4. The AI review engine

Three layers wrap a hand-rolled **orchestrator/worker** tool-calling loop. The
LangGraph layer is intentionally thin — the real logic is in the orchestrator.

### 4.1 `AIWorkflow` (`ai_workflow.py`) — LangGraph
A linear 3-node graph: `triage_pr → review_pr → synthesize_report → END`.
- **triage_pr**: keep only files whose language is in `agent.analysis_languages`.
- **review_pr**: run the `ReviewOrchestrator` over the kept files.
- **synthesize_report**: tally severity/type counts into a summary.

### 4.2 `ReviewOrchestrator` (`review_orchestrator.py`) — the orchestrator agent
A single LLM tool-calling loop, seeded with **only** the PR title/description and
a *manifest* of changed files (name + `+added/-deleted`) — **not** the file
contents. Each round the model may:
- call read-only **data tools** to review trivial files itself, or
- call **`spawn_file_reviewer(path)`** to delegate a file to a sub-agent.

Key mechanics:
- Delegations issued in one turn run **concurrently** (`asyncio.gather`), bounded
  by a semaphore of `agent.max_concurrent_analyses`. Data-tool calls run inline.
- Round budget scales with PR size: `max(12, n_files + 8)`.
- After the loop, a final structured-output call collects the orchestrator's own
  direct findings; sub-agent findings were collected as they completed.
- `_consolidate()` is the deterministic dedup backstop (see §4.5).

### 4.3 `LLMService.analyze_code` (`llm_service.py`) — the sub-agent
One per delegated file, with its **own isolated context window**. Runs its own
bounded tool loop (`MAX_TOOL_ITERATIONS = 4`), then emits structured findings.
Sub-agents get **data tools only** (no `spawn_file_reviewer`) → delegation is
exactly **one level deep**, never recursive.

Two OpenAI clients are used:
- `raw_client` (`AsyncOpenAI`, 90s timeout) drives the tool-calling loop.
- `client` (`instructor`-wrapped, **JSON mode**) produces the final
  Pydantic-validated findings. JSON mode (not TOOLS mode) is deliberate: several
  OpenAI-compatible providers return structured output as JSON content, which
  breaks instructor's TOOLS mode.

### 4.4 Tools (`review_tools.py`)
All served from already-fetched PR data — no network, no cloning:

| Tool | Who | Purpose |
|---|---|---|
| `get_existing_comments` | both | comments already on the PR (humans + bots) → dedup |
| `list_changed_files` | both | changed files with ± line counts |
| `get_file_diff(path)` | both | unified diff of a changed file |
| `search_code(query, path?)` | both | case-insensitive substring search (≤50 hits) |
| `read_file_range(path, a, b)` | both | line-numbered slice (≤100 lines) |
| `spawn_file_reviewer(path)` | **orchestrator only** | delegate a file to a sub-agent |

`spawn_file_reviewer` is **not** a `ReviewToolbox` method — the orchestrator loop
intercepts it because it launches another agent rather than returning stored data.

### 4.5 Deduplication — the "skip" mechanism
The defining concern: **never re-post a comment that already exists** (across
re-runs, and across other bots like CodeRabbit / Copilot / Sourcery). Two layers:

1. **Model judgment (prompt-driven):** every finding carries `should_report` and
   a `skip_reason` (`duplicate` | `low_confidence` | `nitpick` | `out_of_scope`).
   The prompt tells the model to suppress anything already raised.
2. **Deterministic guard (`_consolidate`):** drops model-skipped findings, plus
   anything within `NEAR_LINES = 3` of an existing comment, plus within-run
   duplicates. Every drop is logged with its reason.

Only survivors are saved and posted.

---

## 5. Posting back (`github_review.py`)

`build_review()` turns findings into a `PRReview`:
- An issue becomes an **inline comment** only if its line is visible in the diff
  (computed by `diff_parser.get_new_file_lines` → `build_patch_index`). Lines
  outside the diff are folded into the summary body table instead.
- Event = `REQUEST_CHANGES` if any critical/high finding, else `COMMENT`.
- `post_review()` handles the GitHub 422 "can't request changes on your own PR"
  by retrying with `event=COMMENT`.

Posting is gated on `github.post_comments` **and** a request-supplied token.

---

## 6. Data model (`models/database.py`)

- **`AnalysisTask`** — one per submitted PR: status, progress, timestamps,
  `celery_task_id`, and the submitted `github_token` (stored as-is — see §8).
- **`AnalysisResult`** — one per analyzed file: `issues` as a JSON column.
- **`AnalysisSummary`** — one per task: severity/type counts + score fields.

Enums: `TaskStatus` (`pending|processing|completed|failed|cancelled`),
`IssueType` (`style|bug|performance|security|maintainability|best_practice`),
`IssueSeverity` (`low|medium|high|critical`).

---

## 7. Configuration

`config.toml` + `.env` (via `$ENV` substitution), parsed into a cached nested
Pydantic `Settings`. Notable knobs:
- `llm.provider/base_url/model` — provider-agnostic OpenAI-compatible API.
  **Default ships pointed at OpenRouter** (`openai/gpt-oss-120b:free`).
- `github.post_comments` — master switch for posting reviews back.
- `agent.max_concurrent_analyses` — sub-agent parallelism semaphore.
- `agent.analysis_languages` — triage allow-list.

---

## 8. Known drift & dead code (read before extending)

These are flagged here so future readers don't mistake them for live wiring; see
the improvements list for remediation.

- **`app/agents/tools/ai_tools.py`** — `analyze_code_with_ai` has no callers.
- **`app/agents/tools/python_tools.py`** — ~380 lines, no callers (pre-agentic
  AST analysis).
- **`LangGraphAnalyzer._create_empty_analysis`** — defined, never called.
- **`confidence`** — surfaced in API responses but the LLM never sets it; it is
  always the `0.8` default.
- **Unused settings** — `agent.max_analysis_time`, `agent.retry_attempts`,
  `cache.ttl_*` / `cache.max_cache_size_mb`, and the `api.rate_limit_*` values
  are defined but not enforced.
- **`github_token` is stored in plaintext** in the `analysis_tasks` table.
- **README JSON examples drift** in field names (`message` vs `status_message`,
  an `estimated_duration` that isn't returned) and status value (`in_progress`
  vs the real `processing`).
