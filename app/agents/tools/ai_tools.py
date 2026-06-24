"""
AI-Powered Analysis Tools

This module defines the tools that the intelligent AI agent can use to
perform a deep, AI-driven analysis of code files.
"""

from typing import Any, Dict, List, Optional


from app.agents.tools.review_tools import ReviewToolbox
from app.services.llm_service import LLMService
from app.utils.logger import logger


async def analyze_code_with_ai(
    llm_service: LLMService,
    file_path: str,
    code_content: str,
    file_diff: Optional[str] = None,
    pr_context: Optional[Dict[str, Any]] = None,
    toolbox: Optional[ReviewToolbox] = None,
) -> List[Dict[str, Any]]:
    """
    A tool that uses an AI model to analyze the changes to a code file.

    Args:
        llm_service: An active instance of the LLMService.
        file_path: The path of the file to analyze.
        code_content: The full content of the file (reference context).
        file_diff: The unified diff (patch) for this file, if available.
        pr_context: Pull request intent ({"title": ..., "body": ...}).
        toolbox: Optional ReviewToolbox enabling agentic context gathering.

    Returns:
        A list of issues found by the AI model, validated against the required schema.
    """
    analysis_type = "comprehensive"  # Defaulting to comprehensive for now
    logger.info(f"Executing AI-powered analysis for {file_path}")
    try:
        issues = await llm_service.analyze_code(
            file_path,
            code_content,
            analysis_type,
            file_diff=file_diff,
            pr_context=pr_context,
            toolbox=toolbox,
        )
        logger.info(
            f"AI analysis for {file_path} completed, found {len(issues)} issues."
        )
        return issues
    except Exception as e:
        # Propagate so the workflow can record this file as failed rather than
        # silently treating an LLM/API error as "no issues found".
        logger.error(
            f"An error occurred in the AI code analyzer tool for {file_path}: {e}"
        )
        raise
