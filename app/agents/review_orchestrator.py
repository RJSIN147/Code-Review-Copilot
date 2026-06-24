"""
Model-driven review orchestrator.

A single top-level agent reviews a pull request. It is seeded only with the PR
intent and a manifest of changed files (names + line counts) — no diffs or
content up front. It then drives the review itself by calling tools:

  * data tools (get_file_diff, search_code, read_file_range, …) to review small
    or simple files directly, and
  * ``spawn_file_reviewer`` to delegate a large/complex file to a dedicated
    sub-agent with its own context window.

The model decides *what* to review and *what* to delegate; this module executes
those decisions. Sub-agents reuse ``LLMService.analyze_code`` (a per-file tool
loop) and do NOT get the delegation tool, so delegation is one level deep.

Caps keep the model-driven loops bounded (see the constants below).
"""

import asyncio
import collections
import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.agents.tools.review_tools import (
    ReviewToolbox,
    build_orchestrator_tool_specs,
    preview_result,
)
from app.config.settings import get_settings
from app.models.database import IssueSeverity, IssueType
from app.utils.logger import logger


class OrchestratorIssue(BaseModel):
    """An issue found directly by the orchestrator (carries its file)."""

    file: str = Field(..., description="Path of the file the issue is in.")
    type: IssueType = Field(..., description="The type of the issue.")
    severity: IssueSeverity = Field(..., description="The severity of the issue.")
    line: int = Field(..., description="The line number where the issue occurs.")
    description: str = Field(..., description="A description of the issue.")
    suggestion: str = Field(..., description="A suggestion to fix the issue.")
    production_impact: str = Field(default="")
    should_report: bool = Field(
        default=True,
        description=(
            "Whether to report this issue. Set false to skip duplicates of "
            "existing comments, low-confidence guesses, nitpicks, or "
            "out-of-scope items."
        ),
    )
    skip_reason: Optional[str] = Field(
        default=None,
        description=(
            "When should_report is false: 'duplicate', 'low_confidence', "
            "'nitpick', or 'out_of_scope'."
        ),
    )

    @field_validator("type", mode="before")
    def _validate_type(cls, v):
        try:
            return IssueType(v.lower())
        except (ValueError, AttributeError):
            return IssueType.BEST_PRACTICE

    @field_validator("severity", mode="before")
    def _validate_severity(cls, v):
        try:
            return IssueSeverity(v.lower())
        except (ValueError, AttributeError):
            return IssueSeverity.LOW


class OrchestratorReview(BaseModel):
    """Issues the orchestrator found directly (not via sub-agents)."""

    issues: List[OrchestratorIssue] = Field(default_factory=list)


_ORCHESTRATOR_SYSTEM = (
    "You are the lead reviewer for a pull request. You coordinate the whole "
    "review: triage the changed files, decide what to review yourself versus "
    "delegate, gather context with tools, and report only high-signal, novel "
    "findings.\n\n"
    "INPUTS: the PR title and description (the intent) and a manifest of changed "
    "files with +added/-deleted counts. Pull anything else with the tools.\n\n"
    "TOOLS:\n"
    "- get_existing_comments(): comments ALREADY on this PR, from humans and other "
    "review bots — ALWAYS call this first.\n"
    "- list_changed_files(); get_file_diff(path); search_code(query, path?); "
    "read_file_range(path, start, end) (<=100 lines).\n"
    "- spawn_file_reviewer(path): hand a whole file to a dedicated sub-agent with "
    "its own context window. Sub-agents run IN PARALLEL; their findings are "
    "recorded automatically and returned to you as a short summary.\n\n"
    "HOW TO WORK — be decisive and batch your work:\n"
    "1. FIRST call get_existing_comments() so you know what was already raised.\n"
    "2. DELEGATE LIBERALLY: spawn_file_reviewer for EVERY non-trivial file (more "
    "than ~15 changed lines, or any logic/security/data/control-flow change). "
    "Sub-agents are parallel and cost you almost nothing — when in doubt, "
    "delegate. Only review trivially small files (a handful of changed lines: "
    "config, constants, docs) yourself.\n"
    "3. BATCH tool calls — issue many in a single turn (spawn all the files you "
    "will delegate at once; fetch several diffs together). Never trickle one tool "
    "per turn.\n"
    "4. You have a limited number of turns: it is far better to delegate every "
    "remaining file than to run out of turns with files unreviewed.\n\n"
    "WHAT TO REPORT: review the CHANGES (the diff) against the PR's intent. Report "
    "ONLY issues CAUSED or EXPOSED by the changes, never unrelated pre-existing "
    "code. Report only issues YOU found directly — sub-agent findings are recorded "
    "separately, so do not repeat them.\n\n"
    "DEDUPLICATION & SIGNAL — for EVERY finding, using the existing comments, set "
    "should_report=false with a skip_reason when it is a 'duplicate' (already "
    "raised by an existing comment — yours from a prior run or another bot like "
    "CodeRabbit/Copilot/Sourcery — even at a nearby line), 'low_confidence', a "
    "'nitpick', or 'out_of_scope'. Set should_report=true ONLY for novel, "
    "confident, meaningful issues. When unsure whether something duplicates an "
    "existing comment, prefer should_report=false. Silence beats noise."
)


class ReviewOrchestrator:
    """Runs the model-driven, delegating review of a pull request."""

    # --- caps -------------------------------------------------------------
    # Floor for orchestrator tool-calling rounds; scaled up with the file count
    # in run() so large PRs get enough turns.
    ORCHESTRATOR_MAX_ROUNDS = 12
    # Two findings within this many lines (same file) count as duplicates. Kept
    # tight so the guard catches exact re-posts without suppressing distinct
    # nearby issues — semantic cross-bot dedup is the model's job (via the prompt).
    NEAR_LINES = 3

    def __init__(self, llm_service):
        self.llm = llm_service

    async def run(
        self,
        pr_data: Dict[str, Any],
        files_data: List[Dict[str, Any]],
        existing_comments: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Review the PR and return results grouped as [{file_path, issues}]."""
        if not files_data:
            return []

        files_by_path = {f.get("filename"): f for f in files_data}
        toolbox = ReviewToolbox(files_data, existing_comments, current_file=None)

        settings = get_settings()
        semaphore = asyncio.Semaphore(max(1, settings.agent.max_concurrent_analyses))
        pr_context = {"title": pr_data.get("title"), "body": pr_data.get("body")}

        total_files = len(files_by_path)
        delegated: set[str] = set()
        completed = 0
        collected: List[Dict[str, Any]] = []  # sub-agent issues (each carries file)

        logger.opt(colors=True).info(
            "<magenta><bold>🧭 ORCHESTRATOR</bold></magenta> reviewing "
            "<cyan>{}</cyan> file(s): {}",
            total_files,
            ", ".join(files_by_path.keys()),
        )

        async def delegate(file_path: str) -> str:
            """Run a sub-agent for one file; collect findings; return a summary."""
            nonlocal completed
            file_data = files_by_path.get(file_path)
            if not file_data:
                return f"No changed file named '{file_path}' to delegate."
            if file_path in delegated:
                return f"{file_path} was already reviewed by a sub-agent."
            delegated.add(file_path)

            sub_toolbox = ReviewToolbox(
                files_data, existing_comments, current_file=file_path
            )
            logger.opt(colors=True).info(
                "   <magenta>⇨ DELEGATE</magenta> → sub-agent for <yellow>{}</yellow>",
                file_path,
            )
            issues: List[Dict[str, Any]] = []
            try:
                async with semaphore:
                    issues = await self.llm.analyze_code(
                        file_path,
                        file_data.get("content") or "",
                        "comprehensive",
                        file_diff=file_data.get("patch"),
                        pr_context=pr_context,
                        toolbox=sub_toolbox,
                    )
                for issue in issues:
                    issue["file"] = file_path
                    collected.append(issue)
                return f"Sub-agent reviewed {file_path}: found {len(issues)} issue(s)."
            except Exception as e:
                logger.error(f"Sub-agent for {file_path} failed: {e}")
                return f"Sub-agent for {file_path} failed: {e}"
            finally:
                # Always report progress, even when the sub-agent fails, so the
                # progress bar can't stall on a single failure.
                completed += 1
                if progress_callback is not None:
                    try:
                        await progress_callback(completed, total_files, file_path)
                    except Exception as cb_error:
                        logger.warning(f"Progress callback failed: {cb_error}")

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _ORCHESTRATOR_SYSTEM},
            {"role": "user", "content": self._build_manifest(pr_data, files_data)},
        ]
        tools = build_orchestrator_tool_specs()

        # Scale the round budget with the number of files so big PRs aren't cut
        # off mid-review.
        max_rounds = max(self.ORCHESTRATOR_MAX_ROUNDS, total_files + 8)
        finished = False
        rounds_used = 0
        for round_num in range(1, max_rounds + 1):
            rounds_used = round_num
            completion = await self.llm.raw_client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_completion_tokens=8192,
            )
            message = completion.choices[0].message
            self.llm._log_context(completion, "   ")
            if not message.tool_calls:
                logger.opt(colors=True).info(
                    "<magenta>🧭 round {}</magenta> — "
                    "<green>orchestrator finished (no more tools)</green>",
                    round_num,
                )
                finished = True
                break

            tool_names = [tc.function.name for tc in message.tool_calls]
            logger.opt(colors=True).info(
                "<magenta>🧭 round {}</magenta> — model called <cyan>{}</cyan> "
                "tool(s): <yellow>{}</yellow>",
                round_num,
                len(tool_names),
                ", ".join(tool_names),
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            # Delegations in this turn run concurrently; data lookups run inline.
            spawn_calls = [
                tc
                for tc in message.tool_calls
                if tc.function.name == "spawn_file_reviewer"
            ]
            data_calls = [
                tc
                for tc in message.tool_calls
                if tc.function.name != "spawn_file_reviewer"
            ]

            results: Dict[str, str] = {}
            for tc in data_calls:
                args = self._parse_args(tc)
                logger.opt(colors=True).info(
                    "   <blue>→ {}</blue>({})", tc.function.name, self._fmt_args(args)
                )
                result = toolbox.execute(tc.function.name, args)
                results[tc.id] = result
                logger.opt(colors=True).info(
                    "     <dim>← {}</dim>", preview_result(result)
                )
            if spawn_calls:
                spawn_outputs = await asyncio.gather(
                    *(
                        delegate(self._parse_args(tc).get("file_path", ""))
                        for tc in spawn_calls
                    )
                )
                for tc, out in zip(spawn_calls, spawn_outputs):
                    results[tc.id] = out

            for tc in message.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": results.get(tc.id, "(no result)"),
                    }
                )

        if not finished:
            logger.opt(colors=True).warning(
                "<red>⚠ orchestrator hit the {}-round cap</red> — review may be "
                "incomplete ({} file(s) delegated so far)",
                max_rounds,
                len(delegated),
            )

        logger.opt(colors=True).info(
            "<magenta><bold>🧭 orchestrator done</bold></magenta> in {} round(s) — "
            "<cyan>{}</cyan> delegated; synthesizing direct findings…",
            rounds_used,
            len(delegated),
        )
        # Final pass: the orchestrator's own (non-delegated) findings.
        direct = await self._final_findings(messages)
        logger.opt(colors=True).success(
            "<magenta>🧭 findings</magenta>: <yellow>{}</yellow> from sub-agents + "
            "<yellow>{}</yellow> direct = <cyan>{}</cyan> total",
            len(collected),
            len(direct),
            len(collected) + len(direct),
        )
        kept = self._consolidate(collected + direct, existing_comments)
        logger.opt(colors=True).success(
            "<magenta>🧭 reporting {}</magenta> finding(s) after dedup", len(kept)
        )
        return self._group_by_file(kept)

    def _consolidate(
        self,
        issues: List[Dict[str, Any]],
        existing_comments: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Drop model-skipped findings and dedup against existing comments and
        within this run. Logs every drop with its reason; returns the kept ones.

        This is the deterministic guard: even if the model forgets to set
        should_report=false, a finding that lands on (or within NEAR_LINES of) an
        existing comment is dropped here.
        """
        # Only comments anchored to a real line participate in line-based dedup;
        # comments with no line (general conversation) must not become a synthetic
        # line 0 that swallows findings whose line is also 0/unknown.
        existing = [
            (c.get("path"), int(c.get("line") or c.get("original_line")))
            for c in (existing_comments or [])
            if c.get("path") and (c.get("line") or c.get("original_line"))
        ]
        kept: List[Dict[str, Any]] = []
        seen: List[tuple] = []
        skipped: collections.Counter = collections.Counter()

        for issue in issues:
            file_path = issue.get("file", "?")
            try:
                line = int(issue.get("line") or 0)
            except (TypeError, ValueError):
                line = 0

            reason = None
            if issue.get("should_report") is False:
                reason = issue.get("skip_reason") or "model_skip"
            elif any(
                p == file_path and abs((ln or 0) - line) <= self.NEAR_LINES
                for p, ln in existing
            ):
                reason = "duplicate_existing"
            elif any(
                f == file_path and abs(ln - line) <= self.NEAR_LINES for f, ln in seen
            ):
                reason = "duplicate_in_run"

            if reason:
                skipped[reason] += 1
                logger.opt(colors=True).info(
                    "   <yellow>⊘ skip</yellow> {}:{} — <dim>{}</dim>",
                    file_path,
                    line,
                    reason,
                )
                continue

            seen.append((file_path, line))
            kept.append(
                {
                    k: v
                    for k, v in issue.items()
                    if k not in ("should_report", "skip_reason")
                }
            )

        if skipped:
            logger.opt(colors=True).warning(
                "<yellow>⊘ skipped {} finding(s)</yellow>: {}",
                sum(skipped.values()),
                dict(skipped),
            )
        return kept

    async def _final_findings(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        messages = messages + [
            {
                "role": "user",
                "content": (
                    "Output the issues you found directly (not those handled by "
                    "sub-agents) as the structured list. For EACH issue set file, "
                    "type, severity, line, description, suggestion, "
                    "production_impact, should_report, and skip_reason. Set "
                    "should_report=false (with skip_reason 'duplicate', "
                    "'low_confidence', 'nitpick', or 'out_of_scope') for anything "
                    "already covered by an existing comment, uncertain, trivial, or "
                    "out of scope. If you found nothing yourself, return an empty "
                    "list."
                ),
            }
        ]
        try:
            review: OrchestratorReview = await self.llm.client.chat.completions.create(
                model=self.llm.model,
                response_model=OrchestratorReview,
                messages=messages,
                max_retries=2,
                max_completion_tokens=8192,
                temperature=0.0,
            )
        except Exception as e:
            logger.error(f"Orchestrator final synthesis failed: {e}")
            return []
        return [issue.model_dump() for issue in review.issues]

    @staticmethod
    def _parse_args(tool_call) -> Dict[str, Any]:
        try:
            return json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _fmt_args(args: Dict[str, Any]) -> str:
        return ", ".join(f"{k}={v}" for k, v in args.items())

    @staticmethod
    def _build_manifest(
        pr_data: Dict[str, Any], files_data: List[Dict[str, Any]]
    ) -> str:
        title = pr_data.get("title") or "(no title)"
        body = (pr_data.get("body") or "").strip() or "(no description provided)"
        manifest = "\n".join(
            f"- {f.get('filename')} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in files_data
        )
        return (
            "Pull request to review.\n\n"
            f"Title: {title}\n"
            f"Description: {body}\n\n"
            f"Changed files ({len(files_data)}):\n{manifest}\n\n"
            "Decide per file whether to review it yourself (small/simple) or "
            "delegate it to a sub-agent (large/complex), then report the issues "
            "you find directly."
        )

    @staticmethod
    def _group_by_file(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for issue in issues:
            file_path = issue.get("file", "unknown")
            cleaned = {k: v for k, v in issue.items() if k != "file"}
            grouped.setdefault(file_path, []).append(cleaned)
        return [
            {"file_path": file_path, "issues": file_issues}
            for file_path, file_issues in grouped.items()
        ]
