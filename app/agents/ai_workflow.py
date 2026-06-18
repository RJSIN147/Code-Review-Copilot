"""
Intelligent AI-Driven Code Analysis Workflow

This module defines a sophisticated LangGraph workflow where an AI agent
makes  decisions about how to analyze a pull request.
"""

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.review_orchestrator import ReviewOrchestrator
from app.config.settings import get_settings
from app.services.llm_service import LLMService
from app.utils.language_detection import LanguageDetector
from app.utils.logger import logger


class FileAnalysis(TypedDict):
    """Represents the analysis results for a single file."""

    file_path: str
    issues: List[Dict[str, Any]]


class AIAnalysisState(TypedDict):
    """
    Represents the state of the intelligent analysis workflow.
    """

    pr_data: Dict[str, Any]
    files_data: List[Dict[str, Any]]
    critical_files: List[str]
    current_file_path: Optional[str]
    analysis_results: List[FileAnalysis]
    final_summary: Dict[str, Any]
    llm_service: LLMService
    # Optional async callback invoked as each file finishes:
    # await progress_callback(completed: int, total: int, file_path: str)
    progress_callback: Optional[Any]


class AIWorkflow:
    """
    Orchestrates an AI agent's decision-making process for code review.
    """

    def __init__(self):
        self.graph = self._build_graph()
        logger.info("AI Agent analysis workflow initialized")

    def _build_graph(self) -> StateGraph:
        """
        Builds the LangGraph workflow for the AI agent.
        """
        workflow = StateGraph(AIAnalysisState)

        # Add nodes
        workflow.add_node("triage_pr", self.triage_pr_node)
        workflow.add_node("review_pr", self.review_node)
        workflow.add_node("synthesize_report", self.synthesize_report_node)

        # Define the flow. Triage filters to reviewable (code) files, then a
        # single orchestrator agent reviews them — deciding, per file, whether to
        # review it directly or delegate it to a dedicated sub-agent.
        workflow.set_entry_point("triage_pr")
        workflow.add_edge("triage_pr", "review_pr")
        workflow.add_edge("review_pr", "synthesize_report")
        workflow.add_edge("synthesize_report", END)

        return workflow.compile()

    async def run(
        self,
        pr_data: Dict[str, Any],
        files_data: List[Dict[str, Any]],
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Run the intelligent analysis workflow.

        ``progress_callback`` is an optional async callable invoked as each file
        finishes analysis: ``await progress_callback(completed, total, file_path)``.
        """
        logger.opt(colors=True).info(
            "<cyan><bold>LangGraph flow:</bold></cyan> START → triage_pr → "
            "<magenta>review_pr (orchestrator)</magenta> → synthesize_report → END"
        )
        llm_service = LLMService()

        initial_state: AIAnalysisState = {
            "pr_data": pr_data,
            "files_data": files_data,
            "critical_files": [],
            "current_file_path": None,
            "analysis_results": [],
            "final_summary": {},
            "llm_service": llm_service,
            "progress_callback": progress_callback,
        }
        final_state = await self.graph.ainvoke(initial_state)
        return self._format_output(final_state)

    async def triage_pr_node(self, state: AIAnalysisState) -> AIAnalysisState:
        """
        AI agent examines the PR to identify critical files for review.

        Uses the configured analysis_languages from settings and the
        LanguageDetector extension map to decide which files to analyze.
        """
        settings = get_settings()
        configured_languages = {
            lang.lower() for lang in settings.agent.analysis_languages
        }

        supported_extensions: set[str] = set()
        for ext, lang in LanguageDetector.EXTENSION_MAP.items():
            if lang.lower() in configured_languages:
                supported_extensions.add(ext)

        state["critical_files"] = []
        for f in state["files_data"]:
            filename = f.get("filename", "")
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in supported_extensions:
                state["critical_files"].append(filename)
            else:
                detected = f.get("language", "")
                if detected and detected.lower() in configured_languages:
                    state["critical_files"].append(filename)

        logger.info(
            f"AI triage identified {len(state['critical_files'])} critical files."
        )
        return state

    async def review_node(self, state: AIAnalysisState) -> AIAnalysisState:
        """
        Run the model-driven review orchestrator over the triaged files.

        A single orchestrator agent is seeded with the PR intent and the manifest
        of reviewable files, then decides — per file — whether to review it
        directly via tools or delegate it to a dedicated sub-agent. Findings are
        returned already grouped per file.
        """
        critical = set(state["critical_files"])
        files = [
            f
            for f in state["files_data"]
            if f.get("filename") in critical and f.get("content")
        ]
        if not files:
            state["analysis_results"] = []
            return state

        orchestrator = ReviewOrchestrator(state["llm_service"])
        state["analysis_results"] = await orchestrator.run(
            pr_data=state["pr_data"],
            files_data=files,
            existing_comments=state["pr_data"].get("existing_comments"),
            progress_callback=state.get("progress_callback"),
        )
        return state

    async def synthesize_report_node(self, state: AIAnalysisState) -> AIAnalysisState:
        """
        Synthesizes all findings into a final report.
        """
        logger.info("AI is synthesizing the final report.")
        analysis_results = state["analysis_results"]
        total_issues = sum(len(res.get("issues", [])) for res in analysis_results)
        total_files = len(analysis_results)

        severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        type_breakdown = {}

        for result in analysis_results:
            for issue in result.get("issues", []):
                severity = issue.get("severity", "low")
                issue_type = issue.get("type", "style")
                if severity in severity_breakdown:
                    severity_breakdown[severity] += 1
                type_breakdown[issue_type] = type_breakdown.get(issue_type, 0) + 1

        summary = {
            "total_files_analyzed": total_files,
            "total_issues": total_issues,
            "severity_breakdown": severity_breakdown,
            "issue_type_breakdown": type_breakdown,
            "overall_summary": f"AI analysis complete. Found {total_issues} issues across {total_files} files.",
        }

        state["final_summary"] = summary
        logger.info("AI has synthesized the final report.")
        return state

    def _format_output(self, final_state: AIAnalysisState) -> Dict[str, Any]:
        """
        Formats the final state into the required output structure for database saving.
        """
        files_by_path = {
            f.get("filename"): f for f in final_state.get("files_data", [])
        }

        formatted_files = {}
        for file_analysis in final_state.get("analysis_results", []):
            file_path = file_analysis["file_path"]
            source = files_by_path.get(file_path, {})
            content = source.get("content") or ""
            formatted_files[file_path] = {
                "language": source.get("language") or "unknown",
                "size": len(content.encode("utf-8")),
                "issues": file_analysis["issues"],
            }

        return {
            "summary": final_state.get("final_summary", {}),
            "files": formatted_files,
        }
