# Code Review Copilot — v2 Design Plan

> **Status:** Draft for iteration · **Scope:** Python repos only (initially) · **Target:** Hosted multi-tenant (SaaS)
>
> This document is the north-star design for turning the reviewer from a "linter with an LLM stapled on" into something that reviews like a **senior engineer who has worked in your codebase for a year**. It synthesises the architecture, the knowledge base (KB), the tool suite, the review pipeline, the security model, and a staged build order.

---

## 1. The North Star: a senior reviewer's mental model

A great human reviewer does **not** review text. They review *a change inside a system they understand*. Before commenting they:

1. Read the PR's **intent** (title, description, linked issue).
2. Skim the whole diff to build a **map** of the change and its blast radius.
3. For each change, **follow symbols** — pull the definition, find the callers, check the contract still holds, read the tests.
4. Judge the change against the **codebase's conventions and invariants**, not just generic style.
5. **Zoom out and *question* the change itself** — does this need to exist? is it the simplest form? would it confuse a fresh reader? is it over-engineered? — instead of rationalising whatever is written.
6. Hold the **whole change-set** in their head — cross-file consistency.
7. **Verify their own doubts** before commenting (don't cry wolf).
8. Surface the **vital few** issues, prioritised, with actionable, line-anchored feedback.

Everything in this plan exists to reproduce one of those behaviours — and behaviour 5 (§1.3) is the one almost no current tool does, which makes it the differentiator.

### 1.1 The six-layer knowledge model

What an engineer carries in their head is not one thing. It is layered, and crucially, **only the first two layers live in the source code**:

| Layer | Contains | In the code? | Why a reviewer needs it |
|---|---|---|---|
| **1. Structural** | architecture pattern, services & responsibilities, how things connect, data model, wiring | ✅ mostly | Does this change *belong* here / respect boundaries? |
| **2. Behavioral** | control flow, critical paths, concurrency model, state machines & lifecycles, async/queue flows, idempotency | ⚠️ partially | Races, ordering bugs, state corruption — what static analysis can't see |
| **3. Normative** | conventions & idioms, invariants & contracts, **anti-patterns ("what we never do")** | ❌ rarely explicit | **This is the reviewer's rubric** — consistency & contract-respect |
| **4. Rationale** | design decisions & tradeoffs, rejected alternatives, history/migration state, **scars (past incidents, fragile code)** | ❌ not in code | Catching changes that **violate a deliberate decision** — the senior move |
| **5. Operational/Boundary** | external dependency quirks (rate limits, 429 behaviour), failure modes & blast radius, security/trust boundaries, perf characteristics, config/flags | ❌ scattered | Integration correctness, robustness, "this won't scale", "this leaks a secret" |
| **6. Social** | ownership (CODEOWNERS), who decided what, where it was discussed | ❌ external | Routing, tracing rationale to a source |

**The defining insight:** the most valuable layers (3–6) are **not recoverable from static analysis**. They live in **PR descriptions, review comments, commit messages, issues, ADRs, docs — and people's heads.** Therefore the KB must **mine the conversation around the code**, not just the code, and must **learn from its own review feedback loop over time**. A pure code-index produces a competent intern; mining layers 3–6 produces a teammate who remembers *why*.

### 1.2 The questions the KB must be able to answer

The KB is "done enough" when an agent can get grounded answers to these, mapped to the layer and the mechanism that serves them:

| Reviewer question | Layer | Served by |
|---|---|---|
| "What is this service responsible for? What calls it?" | 1 | code graph + `find_refs` |
| "Where does this value come from / go to?" | 1–2 | code graph + `grep`/`ast-grep` |
| "What runs concurrently with this? Any race?" | 2 | behavioral notes + code graph |
| "What's the lifecycle/state machine of this entity?" | 2 | behavioral notes (mined + curated) |
| "How does this repo do error handling / logging / tests?" | 3 | convention profile (LLM-extracted + mined) |
| "Is there an invariant this change breaks?" | 3 | invariant store + contracts |
| "Do we deliberately *not* do X here?" | 3–4 | anti-pattern store + PR/issue mining |
| "Why is this built this way? What did we reject?" | 4 | PR/commit/ADR mining |
| "Has this area caused incidents / is it fragile?" | 4 | scar store (mined + annotated) |
| "What are this dependency's quirks/limits?" | 5 | operational notes + **web search** |
| "Was a similar issue raised before — accepted or dismissed?" | all | review memory (feedback loop) |
| "Does this even need to exist? Is it the simplest form?" | 1,3,4 | **judgment pass (§8.1)** + graph usage-counts |
| "Would a fresh reader be confused here? Is it over-engineered?" | 2,3 | judgment pass — understand-then-friction |
| "Does this duplicate something the repo already has?" | 1,3 | grep / `find_refs` + `kb_search` |

### 1.3 The questioning gap — why current reviewers feel hollow

**The thesis this project exists to prove:** review quality is bottlenecked by the **harness** — context, grounding, and reviewer *cognition* — **not by the model.** The sharpest evidence is what every current tool fails to do: **ask the core questions.**

Current reviewers flag defects but never *question*. They don't stop and ask "is this confusing? over-engineered? could this be simpler? does this even need to exist?" Worse, they **rationalise** — given any code, they explain why it's fine. Two root causes:

1. **They run in *defect mode*, never *judgment mode*.** "Find issues in this code" accepts the code's existence as a *premise* and hunts for flaws *within its frame*. It never questions the frame itself. The single most valuable senior move — challenging whether the change should exist *as written* — is structurally excluded.

2. **An AI never gets confused — and confusion is the best readability signal.** When a human reads tangled or over-engineered code, they *struggle*, and the struggle **is** the finding. An LLM parses spaghetti as fluently as clean code, so it never feels the friction, never flags it — and because it *can* explain what the code does, it concludes the code is *clear* ("I understand it, therefore it's fine"). It confuses *"I can parse this"* with *"this is good."* That fluency is exactly what masks over-engineering and unclarity.

So the model isn't weak — the harness never asks the questions, and the model's fluency actively hides the thing a human's confusion would reveal. Fixing this is the **differentiator**: see the judgment pass (§8.1).

---

## 2. Current state & the gap

**Today (one-shot, pull-based):** `POST /analyze-pr` with `repo_url + pr_number` → Celery task fetches PR metadata + changed files **via the GitHub API** (no checkout) → a LangGraph workflow loops file-by-file → **one LLM call per *whole file*** → aggregate → save → optionally post inline comments.

Why it feels dumb:
- **No diff awareness in the brain.** The LLM gets the *entire file content* and no patch — it reviews the whole file as if it were new code. The diff is used only *afterward* to position comments (`github_review.py`).
- **No PR intent.** Title/description never reach the model.
- **No cross-file context.** Each file call is blind to the others and to the rest of the repo (no grep, no graph — there's no checkout to search).
- **Sequential.** The graph pops one file per iteration; ~50s × N files back-to-back.
- **LangGraph is overkill for what it does** — `filter → map → reduce` with no real routing/agency.
- **Known bugs surfaced during review** (track and fix as M0):
  - `LLMService.analyze_code` swallows *all* exceptions and returns `[]` → API/rate-limit failures look identical to "clean code"; tasks fake-succeed with 0 issues.
  - `code_quality_score` is never computed (always 0).
  - ~~Read/write schema drift: empty `suggestion`/`line=0` → `/results` 500~~ **(fixed)** — hardened `_convert_issues_to_details`.

---

## 3. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Languages | **Python only** at first | Do one language *excellently* (precise code graph) before going wide. |
| Deployment | **Hosted multi-tenant (SaaS)** | Drives the security model — we run **untrusted code**. |
| KB storage | **FTS-first → pgvector → (dedicated only at scale)** | See §5.4. Lean start, single secured datastore, swappable behind `kb_search()`. |
| Workspace | **Ephemeral sandbox per review + cached per-repo snapshot** | Disposable execution = security boundary; snapshot = warm start. |
| Orchestration | **LangGraph** (`Send` fan-out + `ToolNode` + checkpointer + `interrupt`) | Finally earns its keep once there are tool loops + parallel agents + resumable long runs. |
| System prompt | **Dynamically assembled per review** | Inject repo profile + PR intent + change map + per-lens instructions. |
| Queue (Celery→TaskIQ) | **Deferred / orthogonal** | Not required by any of the above; the file-parallelism win works on Celery today. Revisit only if the async/sync bridge becomes a maintenance pain. |

---

## 4. System architecture

SaaS multi-tenant means we execute linters/tools over **other people's code** — i.e. untrusted code. The CodeRabbit→RCE→1M-repos breach (attacker `.rubocop.yml` `require:` executed in an env holding the GitHub App private key) dictates a **two-plane** split.

```
┌──────────────────── CONTROL PLANE (trusted — never runs PR code) ────────────────────┐
│  • Crown jewels: GitHub App PRIVATE KEY, LLM keys, Postgres, the KB                    │
│  • All git/GitHub I/O: clone, mint short-lived least-scope tokens, POST comments       │
│  • Orchestration (LangGraph), LLM calls, KB read/write, PR-lifecycle webhooks          │
│  • Hands the sandbox ONLY: read-only code mount + a narrow tool-RPC endpoint            │
└───────────────────────────────┬───────────────────────────────────────────────────────┘
                                 │  code in ─→  ←─ structured tool-results out
                                 │  (NO secrets ever cross this line)
┌───────────────────────────────▼──── EXECUTION SANDBOX (disposable, hostile-code) ──────┐
│  • Runs ripgrep / ast-grep / ruff / mypy / (pytest) over the checkout                   │
│  • ZERO production secrets · default-DENY network egress                                 │
│  • gVisor or Firecracker microVM · non-root · read-only rootfs · dropped caps · seccomp │
│  • CPU/mem/PID/disk/wall-clock limits · DESTROYED after the review                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**Granularity:** the sandbox is **per review run** (ephemeral, destroyed after — that disposability *is* the isolation). What is **per repo** is a cached **base snapshot** (clone + built index) so we don't re-clone/re-index every time (Greptile's "clone once, snapshot, resume"). → *Per-repo snapshot = data, reused. Per-review sandbox = compute, disposable.*

**Components:**
- **API / webhook receiver** (control plane) — accepts PR events + manual submits; enqueues reviews.
- **Orchestrator** (control plane) — LangGraph; owns the LLM, the KB, secrets; drives the sandbox via tool-RPC.
- **Workspace manager** (control plane) — clones, manages per-repo snapshots + base/head worktrees, hydrates sandboxes.
- **Sandbox runtime** — isolated executor exposing the tool layer over the checkout.
- **KB service** (control plane) — indexing pipeline + retrieval (`kb_search`), tenant-isolated.
- **Indexer** — builds/updates the code graph + chunk index + convention profile.
- **GitHub gateway** (control plane) — token minting, comment posting, PR-lifecycle ingestion.

---

## 5. The Knowledge Base

### 5.1 Two tiers (not two datastores)
- **Global/persistent repo KB** — built from the **merged/main** state. The "truth": code graph + chunk index (+ embeddings) + convention profile + accumulated **review memory**.
- **Review-scoped context** — per-PR working memory (diff, comprehend brief, retrieved context, this run's findings). **This is mostly in-run state, *not* a second KB engine.** Build one persistent KB + ephemeral run state — don't over-build.

### 5.2 How the KB is built initially (the de-blackboxed pipeline)
Runs once when a repo connects, then incrementally on push/merge:

```
clone default branch
   │
   ├─ 1. STRUCTURAL PASS   walk *.py → tree-sitter / LSP parse →
   │       extract symbols (defs, classes, funcs), refs, imports →
   │       build CODE GRAPH (who defines / calls / imports what)
   │
   ├─ 2. CHUNK PASS        split by semantic unit (function/class, NOT fixed lines) →
   │       each chunk = one retrieval unit, tagged {path, symbol, line range}
   │
   ├─ 3. EMBED PASS        embed each chunk → vectors   (deferred to the pgvector phase;
   │       (skippable while FTS-first)                    FTS + symbol index work without it)
   │
   ├─ 4. CONVENTION PASS   LLM samples the repo → "uses X error handling, Y naming,
   │       Z patterns, never does W" → repo profile (feeds the dynamic prompt)
   │
   ├─ 5. KNOWLEDGE MINING  ingest merged PR threads + review comments + commit messages +
   │       issues + ADRs/docs → extract layers 3–6 (rationale, invariants, scars, conventions)
   │
   └─ 6. INDEX             FTS/GIN + (vector HNSW) + symbol lookup tables
```

- **Incremental re-index:** on push/merge, reparse/re-embed **only changed files** — never rebuild from scratch (the expensive part is the initial full index; this is why we snapshot).

### 5.3 Ingestion sources (the part that makes it a *teammate*)
Because layers 3–6 aren't in the code, the KB pulls from:
- **Code** → structural + behavioral (graph, AST, call-flow).
- **Merged PR threads + review comments** → conventions, rationale, invariants (where these actually get *stated*).
- **Commit messages + issues + ADRs/docs** → rationale, history, scars.
- **The review feedback loop** → every accepted/dismissed finding teaches a convention or invariant (see §5.5).
- **Web search** (tool) → external/operational knowledge the repo can't contain: library behaviour, API semantics, CVEs, rate-limit docs, best practices. This is how the **behavioral/operational layers get filled for third-party deps**.

### 5.4 Storage: FTS-first → pgvector → dedicated (pros/cons)

| | **A. pgvector on existing Postgres** | **B. Dedicated vector DB** (Qdrant/Weaviate) | **C. Postgres FTS first** |
|---|---|---|---|
| Ops | ✅ no new service | ❌ another stateful service to run/secure/back up | ✅✅ leanest, no embedding pipeline |
| Consistency | ✅ KB + findings + tasks one DB, joins, transactional | ❌ split brain (metadata PG / vectors elsewhere) | ✅ all in PG |
| Filtering (per-repo, status, recency) | ✅ SQL `WHERE` fits the access pattern | ⚠️ payload filters, less flexible | ✅ SQL |
| Semantic recall | ✅ HNSW | ✅✅ best at scale | ❌ lexical only |
| Scale ceiling | ⚠️ ~1–10M vectors | ✅✅ 100M+, sharding/quantization | ✅ FTS scales (but not semantic) |
| Security surface (SaaS) | ✅ one store + RLS | ❌ extra surface + extra tenant isolation | ✅ smallest |

**Decision: C → A, B only if scale forces it.** Start with **C** (FTS + code graph + ripgrep — for *code*, lexical + AST + graph already covers a huge fraction). Validate review quality, skip the embedding pipeline. Add **A** by flipping on `pgvector` in the *same* Postgres when semantic recall is needed (zero migration). Reach for **B** only when many large tenants / tens of millions of vectors starve the OLTP DB. **Put all access behind a single `kb_search()` tool interface so the backend is swappable.**

### 5.5 Promotion-on-merge + the feedback loop (needs new plumbing)
The intended loop: a PR's *learnings* fold into the global KB **when it merges** — (a) re-index changed files (main moved), (b) promote **review outcomes** (accepted finding → reinforce the rule; dismissed → suppress that pattern next time). Closed-without-merge → discard or keep as weak negative signal.

**We don't have this today.** The system is one-shot pull-based; it snapshots `pr.state`/`merged_at` *at analysis time* (`github.py:363-367`) but has **no webhooks, no merge-event handling, no PR-lifecycle tracking**. `AnalysisTask.status` is the *job's* lifecycle, not the PR's. → **New capability required: PR-lifecycle ingestion via GitHub App webhooks** (opened/synchronize/closed/merged), and a `review_memory` store keyed to outcomes.

### 5.6 Multi-tenant isolation (applies to every storage choice)
One repo's conventions/findings leaking into another's review is both a **data leak** and a **prompt-injection vector** (poison repo A → influence repo B). Enforce `tenant_id`/`repo_id` on everything + row/collection-level isolation. The KB lives in the **control plane only** — the sandbox never holds it; it gets KB context injected by the orchestrator or via the narrow tool-RPC.

---

## 6. The tool suite (and why each exists)

Tools run **in the sandbox over the checkout**; results return structured to the orchestrator. Layered by escalating precision. Each tool maps to a knowledge-gathering behaviour.

| Tool | Backed by | Why / what it answers | Layer |
|---|---|---|---|
| `grep(pattern, path?, glob?, -t py, -i, -w, multiline?)` | **real ripgrep** (`--json`→structured, `-n`, `-C2`, capped+truncation) | The workhorse. find def (`^\s*(def\|class)\s+Foo`), find callers (`\bfoo\s*\(`), usages, config keys, similar code. Most investigation reduces to search. | 1–3 |
| `ast_grep(rule)` | ast-grep (tree-sitter) | **Structural** match — `except $E: return []`, `requests.get($U)` missing `timeout=`. No false matches in comments/strings. The precision layer between grep and LSP. | 1–3 |
| `read_file(path, start?, end?)` | fs (returns numbered lines) | Pull a *window* around a hit instead of dumping a 2000-line file. Token discipline. | all |
| `read_base(path, start?, end?)` | base worktree | Old-vs-new — review the **change**, not just new code. | 1–2 |
| `read_symbol(path, "Class.method")` | code graph | Grab a whole function without knowing line numbers. | 1 |
| `find_defs / find_refs(symbol)` | LSP (pyright/jedi) or ast-grep | Precise "go to definition / find all callers" — IDE-grade, beats regex when it's too blunt. | 1 |
| `git_blame(path, lines) / git_log(path)` | git | Who/when/why a line exists → rationale + scars. | 4,6 |
| `run_linter(ruff\|mypy)` | sandbox exec | Ground-truth static signal; cheap correctness/style. **(hostile-config aware — §7)** | 3 |
| `get_tests_for(symbol)` | code graph + grep | Is the change tested? Do tests still hold? | 2–3 |
| `kb_search(query, layer?)` | KB service (FTS→pgvector) | Conventions, invariants, rationale, scars, **past findings (accepted/dismissed)**. | 3–6 |
| `web_search(query)` | external | Library behaviour, API semantics, CVEs, rate-limit docs — the **operational/behavioral knowledge of third-party deps** that's in no repo. | 5 |

Design notes: grep/ast-grep return `file:line` → agent `read_file`s the window. All tools return paths the other tools accept. Read-only tools are the default; **executing** code (`run_linter`, `pytest`) is the dangerous tier and is gated by the sandbox.

---

## 7. Security model (derived from the CodeRabbit breach)

Two lessons define everything:
1. **Config files in a PR are executable.** Linters (`rubocop require`, eslint plugins), `conftest.py` (runs on pytest collection), `setup.py`, custom ruff/mypy plugins, pre-commit hooks. **Treat the whole checkout as hostile.**
2. **A secret in the sandbox is a breached secret.** Blast radius = whatever the execution env can see.

Non-negotiables:
- **GitHub App private key NEVER enters the sandbox.** Token minting is control-plane; ideally the sandbox gets *no* token (orchestrator clones; sandbox sees read-only fs). If unavoidable: short-lived, single-repo, least-scope installation token.
- **Default-deny egress** on the sandbox — no phone-home/exfil, no SSRF to metadata/internal services. Whitelist nothing.
- **Hostile-config aware tooling** — run linters/tests only in the sandbox; disable plugin/`require`/custom-rule loading where possible. Prefer read-only analysis; gate execution (`pytest`) deliberately.
- **Resource caps** — CPU/mem/PID/disk/wall-clock; kill on overrun (fork bombs, miners, OOM).
- **Hard isolation** — gVisor or Firecracker microVM, non-root, read-only rootfs, dropped caps, seccomp, ephemeral.
- **Tenant isolation** for the KB (§5.6).

**Sequencing:** build & validate the review pipeline **single-tenant on our own repos first** (trusted code → skip the heavy sandbox), and **harden the two-plane sandbox *before* onboarding any external repo.** Quality work and isolation work are largely independent — don't block one on the other, but never let external code near the easy version.

---

## 8. The review pipeline

```
                         ┌────────────────────────┐
                         │   REPO INTELLIGENCE     │  base+head worktrees · code graph (LSP) ·
                         │  (queried by all tools) │  types · refs · FTS/(vector) index · KB
                         └───────────┬────────────┘
        ┌─────────┐                  │  tools: grep · ast_grep · read/read_base · find_defs/refs
        │  START  │                  │         git_blame · run_linter · get_tests_for · kb_search · web_search
        └────┬────┘                  │
       ┌─────▼──────────┐            │
       │ 1. COMPREHEND  │  PR title/body/issue + commits + FULL diff →
       │  (strong model)│  review BRIEF: intent, per-file summary, risk areas, change-dependency map
       └─────┬──────────┘
       ┌─────▼─────────────────┐
       │ 2. DESIGN JUDGMENT     │  ZOOM-OUT (whole PR, §8.1): should this exist? right approach?
       │   (questioning pass)   │  simplest form? complexity proportional to value?
       └─────┬─────────────────┘  burden-of-proof flip · independent-expectation compare
             │  Send fan-out  (changes × lenses)   [bounded by max_concurrency]
   ┌─────────┼────────┬──────────┬─────────┬─────────┬─────────────┐
┌──▼──────┐┌─▼──────┐┌─▼──────┐┌─▼─────┐┌──▼─────┐┌───▼─────────┐
│correct- ││contract││security││ perf/ ││ tests  ││  JUDGMENT   │  defect lenses + a per-change
│ness     ││/consist││        ││ scale ││ cover. ││ (clarity /  │  QUESTIONING lens (understand-
│+ logic  ││        ││        ││       ││        ││ simplicity) │  then-friction · over-eng tells)
└──┬──────┘└─┬──────┘└─┬──────┘└──┬────┘└───┬────┘└─────┬───────┘
   │  each = AGENTIC react loop (ToolNode): diff-first · grounded · cites file:line
   └─────────┴────────┴──────────┴─────────┴──────────┴───────────┘
                            │  join (reducer: Annotated[list, operator.add])
                  ┌─────────▼────────────┐
                  │ 3. GLOBAL CONSISTENCY │ ALL hunks + findings: signature↔caller,
                  │    (strong model)     │ schema↔model drift, "changed X, forgot Y", dedup
                  └─────────┬────────────┘
                            │  Send fan-out: a verifier squad per candidate finding
                  ┌─────────▼──────────┐
                  │ 4. ADVERSARIAL      │ skeptics tasked to REFUTE each claim against the real
                  │    VERIFY (refute)  │ code; unsubstantiated / majority-refute → killed
                  └─────────┬──────────┘
                  ┌─────────▼──────────┐
                  │ 5. SYNTHESIZE       │ severity, cluster, vital few; QUESTIONS-TO-AUTHOR kept
                  │    + PRIORITIZE     │ distinct from defects; grounded inline comments
                  └─────────┬──────────┘
                       ┌────▼────┐
                       │   END   │ → post via existing github_review path → KB promotion on merge
                       └─────────┘
```

Mapping to the human behaviours (§1):
1. **Comprehend** = read the description + skim everything first → every downstream agent reviews *against intent*.
2. **Design judgment (zoom-out)** = "is this even the right approach?" — questioning the PR's design *before* diving into lines. The senior move current tools skip entirely (§1.3, §8.1).
3. **Specialist fan-out + per-change judgment** = wear multiple hats; each lens reviews the **diff** with the full toolset and *actively investigates* base-vs-head ("reads related functions, builds context"); the judgment lens asks "is this clear / simple / necessary?" per change.
4. **Global consistency** = hold the whole change-set — catches cross-file breakage per-file review *structurally cannot* (e.g., the write/read schema drift that 500'd `/results`).
5. **Adversarial verify** = "don't cry wolf." For a reviewer, false positives destroy trust faster than misses; this kills confident-but-wrong findings.
6. **Synthesize** = senior judgment: the vital few, calibrated, line-anchored, with **questions-to-author** as a first-class output distinct from defect flags.

LangGraph specifics: `Send` for both fan-outs; `ToolNode` + `tools_condition` for the per-agent react loops; **reducer** (`Annotated[list, operator.add]`) on the findings accumulator (mandatory for parallel writes); **checkpointer** because runs are long/expensive/resumable; **`interrupt()`** for "approve before posting to the PR." Concurrency bounded via `config={"max_concurrency": N}` (wire to the existing, currently-unused `max_concurrent_analyses`).

### 8.1 The judgment / questioning pass (the differentiator)

A **first-class stage — not just another defect lens** — whose entire job is the senior questions: **does this need to exist · is it the simplest form · would it confuse a fresh reader · is it over-engineered · what does the repo already do · what's the better version?** It runs at two scopes:

- **Whole-PR zoom-out** (a distinct pass, stage 2): is this the right *approach* at all? a fundamentally simpler design? is the added complexity proportional to the value? — questioning the PR's design, not its lines.
- **Per-change** (a lens in the fan-out): clarity, simplicity, duplication, premature abstraction on each hunk.

Four mechanisms make a *fluent* model genuinely question instead of rationalise:

1. **Understand-then-measure-friction.** Make it first *explain*, plainly, what the code does and *why it's shaped this way* — then flag where that explanation got hard or needed contortions. "Had to trace this three times" / "can't construct a clean reason this abstraction exists" become findings. This forces it to *simulate the confusion* it doesn't naturally feel, turning friction into signal.
2. **Flip the burden of proof.** Not "explain why this is okay" but *"what is the simplest version that works, what does the actual code do beyond that, and is the extra justified?"* The prior is **complexity must be earned by the code, not excused by the reviewer.** This directly kills the rationalisation reflex.
3. **Independent expectation, then compare.** Have it form its own model of the ideal solution *before* reading the implementation deeply, then flag divergence — more files / layers / abstraction than the problem warrants. Divergence from the expected reference class = a question to raise.
4. **Uncertainty as a first-class output.** The finding vocabulary includes *"this confused me," "I'm not sure why this exists," "this seems heavier than the problem," "could this be simpler — is there a reason it isn't?"* — phrased as **questions to the author**, not verdicts. It may conclude "this is fine" **only after genuinely arguing it shouldn't exist.**

**Structural over-engineering tells** feed this pass cheaply via the code graph: an abstraction with one implementation, a parameter never varied, a config flag never flipped, an interface with one caller, a layer that just forwards. *Structure finds the smell; the model asks the question* ("this protocol has exactly one implementer — why the indirection?").

**Judgment needs the KB.** The questions are unanswerable without inferring from surroundings: "this duplicates a util two files over" (graph + search), "inconsistent with how the repo does X" (convention layer), "added an abstraction but the PR introduces only one user of it" (change-set + graph), "this file caused an incident — scrutinise harder" (scar layer). **The connections *are* the judgment** — which is the real reason the KB and tools exist: not to ground bug-flags, but to give the reviewer enough context to *have an opinion about the design.*

### 8.2 Dynamic system prompt
Assembled per review, per lens — not a static string:
```
[ base reviewer persona ]
+ [ repo profile from KB: conventions, stack, invariants, "never do W" ]   ← dynamic
+ [ THIS PR: title, body, linked issue, commit messages ]                  ← dynamic
+ [ change map + comprehend brief ]                                        ← dynamic
+ [ tool catalog + when to use which ]
+ [ judgment prior: complexity must be earned by the code, not excused ]   ← dynamic
+ [ per-lens instructions (security / perf / tests / …) ]                  ← dynamic
```
So the security agent and the tests agent get *different* prompts, and every agent knows the PR's intent and the repo's conventions.

---

## 9. End-to-end request flow

```
GitHub PR event (opened/synchronize)  ──▶  webhook receiver (control plane)
   │  enqueue review {repo, pr, head_sha}
   ▼
Orchestrator picks up
   │  workspace manager: hydrate sandbox from per-repo SNAPSHOT (or cold clone+index on first run)
   │  checkout base + head worktrees; KB freshened incrementally on the changed files
   ▼
LangGraph run (control plane drives; tools execute in sandbox via RPC)
   COMPREHEND → fan-out(changes×lenses) → CONSISTENCY → VERIFY → SYNTHESIZE
   │  every finding grounded to file:line, evidence pulled via tools
   ▼
Control plane posts review (summary + prioritized inline comments) via GitHub gateway
   │  sandbox destroyed
   ▼
Later: PR merged  ──▶  webhook  ──▶  KB PROMOTION
   │  re-index changed files into global KB; fold accepted/dismissed findings into review memory
```

---

## 10. Data model additions (sketch)

- **PR lifecycle** — `pull_request` rows tracking `(repo, number, state, head_sha, merged_at)`, updated by webhooks; reviews link to it. (Today only the *job* lifecycle exists.)
- **KB tables** — `code_symbols`, `code_edges` (graph), `code_chunks` (+ optional `embedding vector`), `repo_profile`, `knowledge_notes` (layers 3–6 with source + layer + confidence), `review_memory` (finding → outcome accepted/dismissed → reinforced rule). All `tenant_id`/`repo_id` scoped with RLS.
- **Snapshots** — per-repo snapshot metadata (last indexed sha, image ref).

---

## 11. Staged build order (milestones)

> Principle: **quality work (M0–M4) can run single-tenant on trusted repos; M5 hardens for untrusted multi-tenant before any external onboarding.**

- **M0 — Fix the lies.** `analyze_code` distinguishes errors from "no issues" (fail the task, don't fake-succeed); compute `code_quality_score`. *(Results-serialization bug already fixed.)*
- **M1 — Diff-first + PR brief + first questioning prompt.** Plumb the patch + PR title/body + changed-file list into the prompt; review the *change*, not the whole file. Add a first **questioning prompt** (burden-of-proof flip: "what's the simplest version, is the extra justified, why does this exist?") — the cheapest way to start demonstrating the thesis (§1.3). Parallelize files (`asyncio.gather`, bounded). *(Biggest single quality jump; no new infra; works on Celery today.)*
- **M2 — Ephemeral workspace + tool layer.** Clone base+head into a workspace; ship the **ripgrep grep tool** + `read_file`/`read_base` + `ast_grep`. Agents investigate over a real checkout. *(The keystone — unlocks every tool at once.)*
- **M3 — KB v1 (FTS + code graph).** Indexer: structural pass + chunking + convention profile; `kb_search` over FTS + symbol lookup; LSP-backed `find_defs/find_refs`. Dynamic prompt assembly.
- **M4 — Multi-agent pipeline + the judgment layer.** Comprehend → **design judgment (zoom-out, §8.1)** → specialist fan-out (`Send` + `ToolNode`, incl. the per-change **judgment/clarity lens**, understand-then-friction, and over-engineering tells from the graph) → consistency → **adversarial verify** → synthesize (with **questions-to-author** as a first-class output). On LangGraph with checkpointer. Add `web_search`, `git_blame`, `run_linter` (read-only-safe usage).
- **M5 — Sandbox hardening (multi-tenant gate).** Two-plane split; secrets out of sandbox; default-deny egress; microVM/gVisor; resource caps; hostile-config handling. **Required before onboarding any external repo.**
- **M6 — KB v2 (semantic + mining).** Flip on `pgvector` (embeddings); mine PR/issue/commit history for layers 3–6; review-memory store.
- **M7 — Promotion-on-merge.** GitHub App webhooks for PR lifecycle; KB promotion + feedback loop closes.

---

## 12. Open questions / risks

- **Encoding judgment / taste (the differentiator, §1.3 / §8.1).** Making a *fluent* model genuinely question rather than rationalise — calibrating understand-then-friction so it flags real over-engineering without devolving into nitpicking or sycophancy. Hardest to get right, highest value; needs iteration on real PRs.
- **Code-graph fidelity (Python).** LSP (pyright) vs jedi vs SCIP/tree-sitter+resolver — pick one and validate precision on real PRs before scaling. *This is the hardest core engineering.*
- **Cost & latency.** Dozens of model calls per PR. Checkpointer + caching the graph and base reads are load-bearing. Model tiering (strong model for comprehend/consistency/synthesize; cheaper for verifiers) needs tuning. *(Floor model `gpt-oss-120b:free` is a placeholder, not the target.)*
- **Sandbox runtime choice.** gVisor vs Firecracker vs locked-down container — tradeoff isolation strength vs ops complexity vs cold-start.
- **Mining quality.** Extracting reliable layer 3–6 knowledge from messy PR threads without poisoning the KB (esp. with multi-tenant prompt-injection risk).
- **Snapshot freshness vs cost.** Re-index cadence; incremental correctness after force-pushes/rebases.
- **Grounding discipline.** Enforce that every finding cites a real `file:line` + pulled evidence, or verification drops it.

---

*This is a living document — iterate here, not in chat.*
