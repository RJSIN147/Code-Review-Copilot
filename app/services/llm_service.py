"""
LLM Service for AI-powered Code Analysis

Handles all interactions with the Large Language Model (LLM) provider,
including prompt formatting, API calls, and response parsing/validation.
"""

from typing import Any, Dict, List


from openai import AsyncOpenAI
import instructor
from pydantic import BaseModel, Field, field_validator

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

    def __init__(self):
        """Initialize the LLM service."""
        self.settings = get_settings()
        if not self.settings.llm.provider:
            raise ValueError("LLM provider not configured in settings")

        logger.info(
            f"Initializing LLM service for provider: {self.settings.llm.provider}"
        )

        # Configure the OpenAI client.
        # JSON mode (rather than the default TOOLS mode) is used because several
        # OpenAI-compatible providers / open models return the structured result
        # as JSON content instead of a proper tool call, which makes TOOLS mode
        # raise "does not support multiple tool calls".
        self.client = instructor.patch(
            AsyncOpenAI(
                api_key=self.settings.llm.openai_api_key,
                base_url=self.settings.llm.base_url,
                # Bound each request so a hung/stalled call fails fast and the
                # file is skipped, instead of stalling the whole analysis on the
                # OpenAI client's 600s default timeout.
                timeout=90.0,
            ),
            mode=instructor.Mode.JSON,
        )
        self.model = self.settings.llm.model
        logger.info(
            f"LLM Service initialized with model: {self.model} (base_url: {self.settings.llm.base_url})"
        )

    async def analyze_code(
        self, file_path: str, code_content: str, analysis_type: str
    ) -> List[Dict[str, Any]]:
        """
        Analyze code content using the configured LLM.

        Args:
            file_path: The path of the file being analyzed.
            code_content: The content of the code to analyze.
            analysis_type: The type of analysis to perform (e.g., 'bug', 'performance').

        Returns:
            A list of validated issues found in the code.
        """
        prompt = self._create_prompt(file_path, code_content, analysis_type)

        try:
            logger.debug(
                f"Sending request to LLM for {analysis_type} analysis of {file_path}"
            )

            # Use instructor to get structured output
            response: AIAnalysisResult = await self.client.chat.completions.create(
                model=self.model,
                response_model=AIAnalysisResult,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert code reviewer. Analyze the provided code and identify issues. "
                            "Keep your reasoning extremely brief (under 100 words) before generating the final JSON response. "
                            "For each issue, you MUST populate every single required field: 'type', 'severity', 'line', 'description', 'suggestion', and 'production_impact'."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_retries=2,
                max_completion_tokens=4096,
                temperature=0.0,
            )

            # Convert Pydantic models to dictionaries for consistent output
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

    def _create_prompt(
        self, file_path: str, code_content: str, analysis_type: str
    ) -> str:
        """
        Create a detailed prompt for the LLM.
        """
        lang = LanguageDetector.detect_language_from_filename(file_path) or "code"
        return f"""
Analyze the following {lang} code from the file `{file_path}` for **{analysis_type.upper()}** issues.

**Code:**
```{lang}
{code_content}
```

**Instructions:**
1.  Focus on identifying issues related to **{analysis_type}**.
2.  For each issue provide:
    - `line`: the exact line number in the code above
    - `type`: one of {", ".join([e.value for e in IssueType])}
    - `severity`: one of {", ".join([e.value for e in IssueSeverity])}
    - `description`: a concise description of the problem
    - `suggestion`: a concrete, actionable fix
    - `production_impact`: 1-2 sentences explaining what could go wrong in a live
      production system if this is left unfixed. Write this for a junior developer
      who does not yet know why the issue matters — no jargon, just consequences.
3.  If no issues are found, return an empty list.
"""


__all__ = ["LLMService"]
