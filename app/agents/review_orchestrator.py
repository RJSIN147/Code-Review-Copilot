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
    "You are the lead reviewer orchestrating a code review of a pull request. "
    "You are given the PR's intent and a manifest of the changed files (names + "
    "line counts) — nothing else up front. Decide how to review each file: "
    "review small or simple files yourself using get_file_diff, search_code and "
    "read_file_range; delegate large or complex files to a dedicated sub-agent "
    "with spawn_file_reviewer (it has its own context window and returns a "
    "summary of what it found). Call get_existing_comments to avoid repeating "
    "feedback already raised. When every file worth reviewing has been handled "
    "(by you or a sub-agent), stop calling tools. Then report ONLY the issues "
    "you found directly — issues from sub-agents are recorded separately, so do "
    "not repeat them. Only report issues caused or exposed by the changes."
)


class ReviewOrchestrator:
    """Runs the model-driven, delegating review of a pull request."""

    # --- caps -------------------------------------------------------------
    ORCHESTRATOR_MAX_ROUNDS = 12  # tool-calling rounds before forcing a finish

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
            except Exception as e:
                logger.error(f"Sub-agent for {file_path} failed: {e}")
                return f"Sub-agent for {file_path} failed: {e}"

            for issue in issues:
                issue["file"] = file_path
                collected.append(issue)

            completed += 1
            if progress_callback is not None:
                try:
                    await progress_callback(completed, total_files, file_path)
                except Exception as cb_error:
                    logger.warning(f"Progress callback failed: {cb_error}")
            return f"Sub-agent reviewed {file_path}: found {len(issues)} issue(s)."

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _ORCHESTRATOR_SYSTEM},
            {"role": "user", "content": self._build_manifest(pr_data, files_data)},
        ]
        tools = build_orchestrator_tool_specs()

        finished = False
        rounds_used = 0
        for round_num in range(1, self.ORCHESTRATOR_MAX_ROUNDS + 1):
            rounds_used = round_num
            completion = await self.llm.raw_client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_completion_tokens=4096,
            )
            message = completion.choices[0].message
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
                self.ORCHESTRATOR_MAX_ROUNDS,
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
        all_issues = collected + direct
        return self._group_by_file(all_issues)

    async def _final_findings(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        messages = messages + [
            {
                "role": "user",
                "content": (
                    "Report ONLY the issues you found directly (not those handled "
                    "by sub-agents) as the structured list. Each issue needs file, "
                    "type, severity, line, description, suggestion, production_impact."
                    " If you found none yourself, return an empty list."
                ),
            }
        ]
        try:
            review: OrchestratorReview = await self.llm.client.chat.completions.create(
                model=self.llm.model,
                response_model=OrchestratorReview,
                messages=messages,
                max_retries=2,
                max_completion_tokens=4096,
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
