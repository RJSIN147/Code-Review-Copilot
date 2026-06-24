"""
LLM Service for AI-powered Code Analysis

Handles all interactions with the Large Language Model (LLM) provider,
including prompt formatting, API calls, and response parsing/validation.
"""

import json
from typing import Any, Dict, List, Optional


from openai import AsyncOpenAI
import instructor
from pydantic import BaseModel, Field, field_validator

from app.agents.tools.review_tools import (
    ReviewToolbox,
    build_tool_specs,
    preview_result,
)
from app.config.settings import get_settings
from app.models.database import IssueType, IssueSeverity
from app.utils.diff_parser import get_new_file_lines
from app.utils.logger import logger
from app.utils.language_detection import LanguageDetector


# How many lines of surrounding context to include around each changed region
# when building the per-file review prompt. This keeps large files from bloating
# the context window — the model can still pull more via the tools.
DIFF_CONTEXT_LINES = 30


def _relevant_code_window(
    code_content: str,
    file_diff: Optional[str],
    context_lines: int = DIFF_CONTEXT_LINES,
) -> str:
    """Return only the changed regions of a file plus surrounding context.

    Uses the diff to find which new-file lines changed, expands each by
    ``context_lines`` on both sides, merges overlapping ranges, and renders a
    line-numbered excerpt with ``...`` markers for the elided gaps. Falls back to
    the full content when there is no usable diff or the windows already cover
    most of the file.
    """
    lines = code_content.splitlines()
    if not lines:
        return code_content

    changed = get_new_file_lines(file_diff) if file_diff else set()
    if not changed:
        return code_content

    keep: set[int] = set()
    for ln in changed:
        start = max(1, ln - context_lines)
        end = min(len(lines), ln + context_lines)
        keep.update(range(start, end + 1))

    # If the windows already cover (almost) the whole file, don't bother slicing.
    if len(keep) >= len(lines):
        return code_content

    out: List[str] = []
    prev: Optional[int] = None
    for i in sorted(keep):
        if prev is not None and i != prev + 1:
            out.append("         ...")
        out.append(f"{i:>6}  {lines[i - 1]}")
        prev = i
    return "\n".join(out)


# Pydantic models for structured output from LLM
class AIAnalysisIssue(BaseModel):
    """Validated issue structure for AI analysis"""

    type: IssueType = Field(..., description="The type of the issue.")
    severity: IssueSeverity = Field(..., description="The severity of the issue.")
    line: int = Field(..., description="The line number where the issue occurs.")
    description: str = Field(..., description="A description of the issue.")
    suggestion: str = Field(..., description="A suggestion to fix the issue.")
    production_impact: str = Field(
        default="",
        description=(
            "A 1-2 sentence plain-English explanation of what could go wrong "
            "in a live production system if this issue is not fixed. "
            "Written for a junior developer with no assumed context."
        ),
    )
    should_report: bool = Field(
        default=True,
        description=(
            "Whether to actually report this issue. Set false to skip duplicates "
            "of existing comments, low-confidence guesses, nitpicks, or "
            "out-of-scope items."
        ),
    )
    skip_reason: Optional[str] = Field(
        default=None,
        description=(
            "When should_report is false, one of: 'duplicate', 'low_confidence', "
            "'nitpick', 'out_of_scope'."
        ),
    )

    @field_validator("type", mode="before")
    def validate_issue_type(cls, v):
        try:
            return IssueType(v.lower())
        except ValueError:
            logger.warning(f"Invalid issue type '{v}', defaulting to 'best_practice'.")
            return IssueType.BEST_PRACTICE

    @field_validator("severity", mode="before")
    def validate_issue_severity(cls, v):
        try:
            return IssueSeverity(v.lower())
        except ValueError:
            logger.warning(f"Invalid issue severity '{v}', defaulting to 'low'.")
            return IssueSeverity.LOW


class AIAnalysisResult(BaseModel):
    """Structured analysis result from the AI model"""

    issues: List[AIAnalysisIssue] = Field(
        ..., description="A list of issues found in the code."
    )


class LLMService:
    """
    Service for interacting with an OpenAI-compatible LLM.
    """

    # Max rounds the model may call context tools before producing findings.
    MAX_TOOL_ITERATIONS = 4

    def __init__(self):
        """Initialize the LLM service."""
        self.settings = get_settings()
        if not self.settings.llm.provider:
            raise ValueError("LLM provider not configured in settings")

        logger.info(
            f"Initializing LLM service for provider: {self.settings.llm.provider}"
        )

        # A raw client drives the agentic tool-calling loop; an instructor-wrapped
        # client produces the final structured (JSON-mode) findings.
        #
        # JSON mode (rather than the default TOOLS mode) is used for the structured
        # output because several OpenAI-compatible providers return the result as
        # JSON content rather than a tool call, which makes TOOLS mode raise
        # "does not support multiple tool calls".
        self.raw_client = AsyncOpenAI(
            api_key=self.settings.llm.openai_api_key,
            base_url=self.settings.llm.base_url,
            # Bound each request so a hung/stalled call fails fast and the file is
            # skipped, instead of stalling on the OpenAI client's 600s default.
            timeout=90.0,
        )
        self.client = instructor.from_openai(self.raw_client, mode=instructor.Mode.JSON)
        self.model = self.settings.llm.model
        logger.info(
            f"LLM Service initialized with model: {self.model} (base_url: {self.settings.llm.base_url})"
        )

    async def analyze_code(
        self,
        file_path: str,
        code_content: str,
        analysis_type: str,
        file_diff: Optional[str] = None,
        pr_context: Optional[Dict[str, Any]] = None,
        toolbox: Optional[ReviewToolbox] = None,
    ) -> List[Dict[str, Any]]:
        """
        Analyze the changes to a file using the configured LLM.

        When a ``toolbox`` is supplied, the model may first call context tools
        (other files' diffs, existing PR comments) before producing its findings.

        Args:
            file_path: The path of the file being analyzed.
            code_content: The full file content (reference context).
            analysis_type: The type of analysis to perform.
            file_diff: The unified diff (patch) for this file, if available.
            pr_context: Pull request intent, e.g. {"title": ..., "body": ...}.
            toolbox: Optional ReviewToolbox enabling agentic context gathering.

        Returns:
            A list of validated issues found in the changes.
        """
        system_prompt = (
            "You are a focused code reviewer assigned to ONE file in a pull "
            "request. Review its changes deeply and report only high-signal, "
            "novel findings.\n\n"
            "TOOLS (read-only context): get_existing_comments() — comments already "
            "on this PR from humans and other review bots; list_changed_files(); "
            "get_file_diff(path); search_code(query, path?); "
            "read_file_range(path, start, end) (<=100 lines). Batch your tool calls "
            "and stop once you have what you need.\n\n"
            "WHAT TO REPORT: review the CHANGES (the diff) against the PR's intent. "
            "Only report issues CAUSED or EXPOSED by the changes — not unrelated, "
            "pre-existing code. Follow a changed symbol into other files when the "
            "change affects them.\n\n"
            "DEDUPLICATION & SIGNAL — for EVERY finding, check it against the "
            "existing comments and set should_report=false with a skip_reason when "
            "it is a 'duplicate' (the same or substantially similar issue is "
            "already raised by an existing comment — yours from a prior run or "
            "another bot like CodeRabbit/Copilot/Sourcery — even at a nearby line), "
            "'low_confidence', a 'nitpick', or 'out_of_scope'. Set "
            "should_report=true ONLY for novel, confident, meaningful issues. When "
            "unsure whether it duplicates an existing comment, prefer "
            "should_report=false. Silence beats noise.\n\n"
            "For every issue populate: type, severity, line, description, "
            "suggestion, production_impact, should_report, and skip_reason."
        )
        user_prompt = self._create_prompt(
            file_path, code_content, analysis_type, file_diff, pr_context
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            if toolbox is not None:
                messages = await self._run_tool_loop(file_path, messages, toolbox)

            # Final structured (JSON-mode) output.
            response: AIAnalysisResult = await self.client.chat.completions.create(
                model=self.model,
                response_model=AIAnalysisResult,
                messages=messages,
                max_retries=2,
                max_completion_tokens=8192,
                temperature=0.0,
            )

            validated_issues = [issue.model_dump() for issue in response.issues]
            logger.opt(colors=True).success(
                "      <green>✓ sub-agent</green> <yellow>{}</yellow> finished — "
                "<cyan>{}</cyan> issue(s)",
                file_path,
                len(validated_issues),
            )
            return validated_issues

        except Exception as e:
            # Surface the failure instead of returning an empty list, which would
            # be indistinguishable from a clean file that genuinely has no issues.
            logger.error(f"Error during LLM API call for {file_path}: {e}")
            raise

    async def _run_tool_loop(
        self,
        file_path: str,
        messages: List[Dict[str, Any]],
        toolbox: ReviewToolbox,
    ) -> List[Dict[str, Any]]:
        """Let the model call context tools before it produces findings.

        Returns the augmented message list (assistant tool calls + tool results)
        to feed into the final structured-output request.
        """
        tools = build_tool_specs()

        for round_num in range(1, self.MAX_TOOL_ITERATIONS + 1):
            completion = await self.raw_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_completion_tokens=8192,
            )
            message = completion.choices[0].message

            if not message.tool_calls:
                break  # the model is done gathering context

            sub_tool_names = [tc.function.name for tc in message.tool_calls]
            logger.opt(colors=True).info(
                "      <green>🔧 sub-agent</green> <yellow>{}</yellow> round {} — "
                "called <cyan>{}</cyan>",
                file_path,
                round_num,
                ", ".join(sub_tool_names),
            )

            # Record the assistant's tool-call turn explicitly (portable across
            # providers), followed by the result of each requested tool call.
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
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = toolbox.execute(tc.function.name, arguments)
                logger.opt(colors=True).info(
                    "        <blue>↳ {}</blue>({})",
                    tc.function.name,
                    ", ".join(f"{k}={v}" for k, v in arguments.items()),
                )
                logger.opt(colors=True).info(
                    "          <dim>← {}</dim>", preview_result(result)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

        return messages

    def _create_prompt(
        self,
        file_path: str,
        code_content: str,
        analysis_type: str,
        file_diff: Optional[str] = None,
        pr_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a diff-first, intent-aware review prompt.
        """
        lang = LanguageDetector.detect_language_from_filename(file_path) or "code"
        pr_context = pr_context or {}
        title = pr_context.get("title") or "(no title)"
        body = (pr_context.get("body") or "").strip() or "(no description provided)"

        if file_diff:
            diff_section = (
                f"**Diff (the changes to review):**\n```diff\n{file_diff}\n```"
            )
            relevant_code = _relevant_code_window(code_content, file_diff)
            code_section = (
                "**Relevant code (changed regions + surrounding context, "
                f"line-numbered):**\n```{lang}\n{relevant_code}\n```"
            )
        else:
            diff_section = "**Diff:** (no diff available — review the file as a whole)"
            code_section = f"**Full file (reference/context only):**\n```{lang}\n{code_content}\n```"

        issue_types = ", ".join([e.value for e in IssueType])
        severities = ", ".join([e.value for e in IssueSeverity])

        return f"""You are reviewing changes to `{file_path}` ({lang}) in a pull request.

**Pull request intent**
- Title: {title}
- Description: {body}

{diff_section}

{code_section}

**Instructions**
1. Review the **changes in the diff**, judged against the pull request's intent — not the whole file. The code excerpt is line-numbered and shows the changed regions plus surrounding context; use it as supporting context only.
2. If a change here affects or depends on another changed file, call `get_file_diff` to inspect it; call `get_existing_comments` to avoid repeating feedback already raised.
3. For each issue provide:
   - `line`: the line number in the file (use the numbers shown in the code excerpt)
   - `type`: one of {issue_types}
   - `severity`: one of {severities}
   - `description`: a concise description of the problem
   - `suggestion`: a concrete, actionable fix
   - `production_impact`: 1-2 sentences on what could go wrong in production if left unfixed, written for a junior developer.
4. Only report issues caused or exposed by the changes. If there are none, return an empty list.
"""


__all__ = ["LLMService"]
