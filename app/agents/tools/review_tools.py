"""
Agentic context tools for the reviewer.

These let the LLM pull extra context about the pull request *on demand* while it
reviews a file: the diff of any other changed file, the existing review comments,
and the list of changed files. Everything is served from data already fetched via
the GitHub API for this PR — no extra API calls and no repository cloning.
"""

from typing import Any, Dict, List, Optional

from app.utils.logger import logger


def build_tool_specs() -> List[Dict[str, Any]]:
    """OpenAI tool/function schemas the model may call during a review."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_changed_files",
                "description": (
                    "List all files changed in this pull request, with their "
                    "added/deleted line counts. Use this to discover which other "
                    "files you can inspect for cross-file context."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_diff",
                "description": (
                    "Get the diff (patch) of another file changed in this same "
                    "pull request. Use this when the file under review affects, or "
                    "depends on, a change made elsewhere in the PR."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path of the changed file whose diff you want.",
                        }
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_existing_comments",
                "description": (
                    "Get the review and conversation comments already posted on "
                    "this pull request. Use this to avoid repeating feedback that "
                    "has already been raised by others."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


class ReviewToolbox:
    """Executes reviewer tool calls against already-fetched PR data.

    The toolbox never makes network calls — it answers from the PR's changed
    files (which carry their own diffs) and the pre-fetched existing comments.
    """

    def __init__(
        self,
        files_data: List[Dict[str, Any]],
        existing_comments: Optional[List[Dict[str, Any]]],
        current_file: str,
    ):
        self._files = {f.get("filename"): f for f in files_data}
        self._comments = existing_comments or []
        self._current_file = current_file

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """Run a tool by name and return an LLM-readable string result."""
        try:
            if name == "list_changed_files":
                return self._list_changed_files()
            if name == "get_file_diff":
                return self._get_file_diff(arguments.get("file_path", ""))
            if name == "get_existing_comments":
                return self._get_existing_comments()
            return f"Unknown tool '{name}'."
        except Exception as e:  # a tool must never crash the review loop
            logger.warning(f"Review tool '{name}' failed: {e}")
            return f"Tool '{name}' failed: {e}"

    def _list_changed_files(self) -> str:
        if not self._files:
            return "No files changed in this PR."
        lines = []
        for path, f in self._files.items():
            here = " (the file you are reviewing)" if path == self._current_file else ""
            lines.append(
                f"- {path} (+{f.get('additions', 0)}/-{f.get('deletions', 0)}){here}"
            )
        return "Files changed in this PR:\n" + "\n".join(lines)

    def _get_file_diff(self, file_path: str) -> str:
        f = self._files.get(file_path)
        if not f:
            return (
                f"No changed file named '{file_path}' in this PR. "
                "Call list_changed_files to see valid paths."
            )
        patch = f.get("patch") or "(no diff available for this file)"
        return f"Diff for {file_path}:\n```diff\n{patch}\n```"

    def _get_existing_comments(self) -> str:
        if not self._comments:
            return "There are no existing comments on this pull request."
        out = []
        for c in self._comments:
            where = f" on {c.get('path')}:{c.get('line')}" if c.get("path") else ""
            out.append(
                f"[{c.get('kind', 'comment')}] {c.get('author', 'unknown')}{where}: "
                f"{c.get('body', '')}"
            )
        return "Existing comments on this PR:\n" + "\n".join(out)
