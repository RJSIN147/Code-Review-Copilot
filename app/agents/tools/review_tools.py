"""
Agentic context tools for the reviewer.

These let the LLM pull context about the pull request *on demand* while it
reviews: the diff of any changed file, a search across the changed files, a
bounded slice of a file's content, the existing review comments, and the list of
changed files. Everything is served from data already fetched via the GitHub API
for this PR — no extra API calls and no repository cloning.

There are two tool sets:
  * the sub-agent set (data tools only) — what a per-file reviewer can call.
  * the orchestrator set (data tools + ``spawn_file_reviewer``) — the top-level
    agent can additionally delegate a whole file to a dedicated sub-agent.
``spawn_file_reviewer`` is NOT a ReviewToolbox method: it is handled by the
orchestrator loop, because it launches another agent rather than looking up data.
"""

from typing import Any, Dict, List, Optional

from app.utils.logger import logger

# Caps that keep tool output bounded.
MAX_READ_LINES = 100
MAX_SEARCH_RESULTS = 50


def preview_result(text: str, max_chars: int = 160) -> str:
    """A compact, single-line preview of a tool result, for readable logs."""
    text = (text or "").strip()
    if not text:
        return "(empty)"
    n_lines = text.count("\n") + 1
    flat = " ".join(text.split())
    if len(flat) > max_chars:
        flat = flat[:max_chars] + "…"
    return f"{n_lines} line(s) · {flat}"


def _data_tool_specs() -> List[Dict[str, Any]]:
    """The read-only context tools shared by the orchestrator and sub-agents."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_changed_files",
                "description": (
                    "List all files changed in this pull request, with their "
                    "added/deleted line counts. Use this to decide what to review."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_diff",
                "description": (
                    "Get the diff (patch) of a file changed in this pull request."
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
                "name": "search_code",
                "description": (
                    "Case-insensitive substring search across the changed files' "
                    "content. Returns matches as 'path:line: text'. Use it to find "
                    "definitions, call sites, or related code, then read the range."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search for.",
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Optional: restrict the search to this file.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_range",
                "description": (
                    "Read a line range of a changed file's content "
                    f"(at most {MAX_READ_LINES} lines per call). Use after "
                    "search_code or get_file_diff to inspect surrounding code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["file_path", "start_line", "end_line"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_existing_comments",
                "description": (
                    "Get the review and conversation comments already posted on "
                    "this pull request, so you do not repeat feedback."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def _spawn_tool_spec() -> Dict[str, Any]:
    """The delegation tool — orchestrator only."""
    return {
        "type": "function",
        "function": {
            "name": "spawn_file_reviewer",
            "description": (
                "Delegate the full review of one file to a dedicated sub-agent "
                "with its own context window. Use this for large or complex files "
                "so they don't crowd your context. Returns a summary of what the "
                "sub-agent found. Review small/simple files yourself instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the changed file to delegate.",
                    }
                },
                "required": ["file_path"],
            },
        },
    }


def build_subagent_tool_specs() -> List[Dict[str, Any]]:
    """Tools available to a per-file sub-agent (data tools, no delegation)."""
    return _data_tool_specs()


def build_orchestrator_tool_specs() -> List[Dict[str, Any]]:
    """Tools available to the orchestrator (data tools + delegation)."""
    return _data_tool_specs() + [_spawn_tool_spec()]


# Backwards-compatible alias: the per-file reviewer uses the sub-agent tool set.
def build_tool_specs() -> List[Dict[str, Any]]:
    return build_subagent_tool_specs()


class ReviewToolbox:
    """Executes read-only reviewer tool calls against already-fetched PR data.

    The toolbox never makes network calls — it answers from the PR's changed
    files (which carry their diffs and content) and the pre-fetched comments.
    ``spawn_file_reviewer`` is intentionally NOT handled here (the orchestrator
    runs it, since it launches a sub-agent rather than returning stored data).
    """

    def __init__(
        self,
        files_data: List[Dict[str, Any]],
        existing_comments: Optional[List[Dict[str, Any]]],
        current_file: Optional[str] = None,
    ):
        self._files = {f.get("filename"): f for f in files_data}
        self._comments = existing_comments or []
        self._current_file = current_file

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """Run a data tool by name and return an LLM-readable string result."""
        try:
            if name == "list_changed_files":
                return self._list_changed_files()
            if name == "get_file_diff":
                return self._get_file_diff(arguments.get("file_path", ""))
            if name == "search_code":
                return self._search_code(
                    arguments.get("query", ""), arguments.get("file_path")
                )
            if name == "read_file_range":
                return self._read_file_range(
                    arguments.get("file_path", ""),
                    arguments.get("start_line"),
                    arguments.get("end_line"),
                )
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
            here = " (currently reviewing)" if path == self._current_file else ""
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

    def _search_code(self, query: str, file_path: Optional[str] = None) -> str:
        if not query:
            return "search_code requires a non-empty 'query'."
        if file_path:
            f = self._files.get(file_path)
            if not f:
                return f"No changed file named '{file_path}' in this PR."
            if not f.get("content"):
                return (
                    f"'{file_path}' has no searchable content "
                    "(binary, deleted, or too large to fetch)."
                )
            targets = {file_path: f}
        else:
            targets = self._files

        matches: List[str] = []
        needle = query.lower()
        for path, f in targets.items():
            for i, line in enumerate((f.get("content") or "").splitlines(), start=1):
                if needle in line.lower():
                    matches.append(f"{path}:{i}: {line.strip()}")
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        break
            if len(matches) >= MAX_SEARCH_RESULTS:
                break

        if not matches:
            scope = f" in {file_path}" if file_path else " across changed files"
            return f"No matches for '{query}'{scope}."
        scope = f" in {file_path}" if file_path else " across changed files"
        truncated = " (truncated)" if len(matches) >= MAX_SEARCH_RESULTS else ""
        return f"Matches for '{query}'{scope}{truncated}:\n" + "\n".join(matches)

    def _read_file_range(self, file_path: str, start_line: Any, end_line: Any) -> str:
        f = self._files.get(file_path)
        if not f:
            return f"No changed file named '{file_path}' in this PR."
        lines = (f.get("content") or "").splitlines()
        if not lines:
            return f"{file_path} has no readable content."
        try:
            start = max(1, int(start_line))
            end = min(len(lines), int(end_line))
        except (TypeError, ValueError):
            return "read_file_range needs integer 'start_line' and 'end_line'."
        if end < start:
            return "'end_line' must be >= 'start_line'."
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1  # enforce the per-call cap
        body = "\n".join(f"{i:>6}  {lines[i - 1]}" for i in range(start, end + 1))
        return f"{file_path} lines {start}-{end}:\n{body}"

    def _get_existing_comments(self) -> str:
        if not self._comments:
            return "There are no existing comments on this pull request."
        out = []
        for c in self._comments:
            where = f" on {c.get('path')}:{c.get('line')}" if c.get("path") else ""
            body = " ".join((c.get("body") or "").split())  # flatten multi-line bodies
            out.append(
                f"[{c.get('kind', 'comment')}] {c.get('author', 'unknown')}{where}: {body}"
            )
        return "Existing comments on this PR:\n" + "\n".join(out)
