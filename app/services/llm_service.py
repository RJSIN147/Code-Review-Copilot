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

from app.agents.tools.review_tools import ReviewToolbox, build_tool_specs
from app.config.settings import get_settings
from app.models.database import IssueType, IssueSeverity
from app.utils.logger import logger
from app.utils.language_detection import LanguageDetector


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
            "You are an expert senior code reviewer. You review the CHANGES "
            "introduced by a pull request, not the whole file in isolation. "
            "Before finalizing, you may call the available tools to gather "
            "context: inspect the diffs of other changed files when a change here "
            "affects or depends on them, and check the existing review comments so "
            "you do not repeat feedback already given. Only report issues caused "
            "or exposed by the changes in the diff. For every issue you MUST "
            "populate: 'type', 'severity', 'line', 'description', 'suggestion', "
            "and 'production_impact'."
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
                max_completion_tokens=4096,
                temperature=0.0,
            )

            validated_issues = [issue.model_dump() for issue in response.issues]
            logger.info(
                f"LLM analysis for {file_path} found {len(validated_issues)} issues."
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

        for _ in range(self.MAX_TOOL_ITERATIONS):
            completion = await self.raw_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_completion_tokens=4096,
            )
            message = completion.choices[0].message

            if not message.tool_calls:
                break  # the model is done gathering context

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
                logger.info(f"[{file_path}] tool call: {tc.function.name}({arguments})")
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
        else:
            diff_section = "**Diff:** (no diff available — review the file as a whole)"

        issue_types = ", ".join([e.value for e in IssueType])
        severities = ", ".join([e.value for e in IssueSeverity])

        return f"""You are reviewing changes to `{file_path}` ({lang}) in a pull request.

**Pull request intent**
- Title: {title}
- Description: {body}

{diff_section}

**Full file (reference/context only):**
```{lang}
{code_content}
```

**Instructions**
1. Review the **changes in the diff**, judged against the pull request's intent — not the whole file. Use the file content only as supporting context.
2. If a change here affects or depends on another changed file, call `get_file_diff` to inspect it; call `get_existing_comments` to avoid repeating feedback already raised.
3. For each issue provide:
   - `line`: the line number in the file
   - `type`: one of {issue_types}
   - `severity`: one of {severities}
   - `description`: a concise description of the problem
   - `suggestion`: a concrete, actionable fix
   - `production_impact`: 1-2 sentences on what could go wrong in production if left unfixed, written for a junior developer.
4. Only report issues caused or exposed by the changes. If there are none, return an empty list.
"""


__all__ = ["LLMService"]
