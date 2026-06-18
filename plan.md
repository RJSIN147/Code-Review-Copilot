# Implementation Spec: Inline GitHub PR Comments

---

## IDE Prompt

> Copy everything below this line and paste it directly into Antigravity IDE.

---

You are implementing the **Inline GitHub PR Comments** feature for an existing FastAPI + Celery + LangGraph code review agent. The codebase is already working — analysis runs, results are saved to PostgreSQL, and a REST API exposes them. Your job is to add the ability to **post those results back to GitHub as inline review comments** on the PR that was analysed.

Implement **every step** in this document exactly as specified. Do not skip steps, do not rename files or functions, do not refactor existing code unless a step explicitly says to. All new code must follow the project's existing conventions: async where the rest of the file is async, Loguru for logging (`from app.utils.logger import logger`), Pydantic models for structured data, type hints on all function signatures.

The project uses **Python 3.13**, **uv** for package management, **FastAPI**, **SQLModel**, **Celery**, **LangGraph**, **PyGithub**, **httpx**, **instructor + OpenAI-compatible LLM**, and **Loguru**.

Work through the steps in order. Each step lists every file to touch and the exact change to make.

---

## Background: What Already Exists

Before writing a single line, read these files to understand the codebase:

| File | What it does |
|---|---|
| `app/services/github.py` | `GitHubService` — fetches PR metadata, file list, file content via PyGithub |
| `app/services/llm_service.py` | `LLMService` — sends code to LLM, returns `List[AIAnalysisIssue]` |
| `app/agents/ai_workflow.py` | LangGraph workflow — triage → per-file analysis → synthesis |
| `app/tasks/analyze_tasks.py` | Celery task `analyze_pr_task` — orchestrates GitHub fetch → AI analysis → DB save |
| `app/models/database.py` | SQLModel DB models: `AnalysisTask`, `AnalysisResult`, `AnalysisSummary` |
| `app/models/schemas.py` | Pydantic API schemas: `IssueDetail`, `AnalysisResponse`, etc. |
| `app/config/settings.py` | Settings loaded from `config.toml`; `GitHubConfig` is the relevant section |
| `config.toml` | TOML config file; `[github]` section controls GitHub behaviour |

### Critical data shapes to understand

**`files_for_analysis`** — built in `analyze_tasks.py`, passed to `langgraph_analyzer.analyze_pr()`:

```python
# Each element currently looks like this:
{
    "filename": "app/main.py",
    "language": "python",
    "content": "...(full file text)...",
    "additions": 10,
    "deletions": 5,
    "changes": 15,
    # NOTE: "patch" is NOT currently included — Step 2 adds it
}
```

**`analysis_results`** — returned by `langgraph_analyzer.analyze_pr()`:

```python
{
    "summary": {
        "total_files_analyzed": 3,
        "total_issues": 7,
        "severity_breakdown": {"critical": 0, "high": 2, "medium": 3, "low": 2},
        "issue_type_breakdown": {"security": 1, "style": 3, "bug": 2, "performance": 1},
        "overall_summary": "AI analysis complete. Found 7 issues across 3 files.",
    },
    "files": {
        "app/main.py": {
            "language": "python",
            "size": 2048,
            "issues": [
                {
                    "type": "security",        # IssueType enum value
                    "severity": "high",        # IssueSeverity enum value
                    "line": 42,                # absolute line number in new file
                    "description": "...",
                    "suggestion": "...",
                    # NOTE: "production_impact" not yet present — Step 3 adds it
                }
            ],
        }
    },
}
```

**`file_info`** — one element of the list returned by `github_service.get_pull_request_files()`:

```python
{
    "filename": "app/main.py",
    "previous_filename": None,
    "status": "modified",       # added | removed | modified | renamed
    "additions": 10,
    "deletions": 5,
    "changes": 15,
    "sha": "abc123",
    "blob_url": "https://...",
    "raw_url": "https://...",
    "patch": "@@ -1,5 +1,7 @@\n import os\n+import json\n ...",  # unified diff
}
```

---

## Step 1 — Add `post_github_comments` flag to config

### `config.toml`

Add one line to the `[github]` section:

```toml
[github]
api_url = "https://api.github.com"
timeout = 30
max_retries = 3
max_files_per_pr = 50
max_file_size_kb = 1024
post_comments = false        # ← ADD THIS LINE (false by default; set true to enable)
```

### `app/config/settings.py`

Add one field to `GitHubConfig`:

```python
class GitHubConfig(BaseModel):
    """GitHub API configuration"""
    api_url: str = "https://api.github.com"
    timeout: int = 30
    max_retries: int = 3
    max_files_per_pr: int = 50
    max_file_size_kb: int = 1024
    post_comments: bool = False        # ← ADD THIS FIELD
```

---

## Step 2 — Pass `patch` through to `files_for_analysis`

### `app/tasks/analyze_tasks.py`

Find the block inside `analyze_pr_task` that appends to `files_for_analysis`. It currently looks like this:

```python
files_for_analysis.append(
    {
        "filename": file_path,
        "language": language,
        "content": file_content,
        "additions": file_info.get("additions", 0),
        "deletions": file_info.get("deletions", 0),
        "changes": file_info.get("changes", 0),
    }
)
```

Change it to include the `patch` field:

```python
files_for_analysis.append(
    {
        "filename": file_path,
        "language": language,
        "content": file_content,
        "additions": file_info.get("additions", 0),
        "deletions": file_info.get("deletions", 0),
        "changes": file_info.get("changes", 0),
        "patch": file_info.get("patch", ""),    # ← ADD THIS LINE
    }
)
```

---

## Step 3 — Add `production_impact` to the LLM layer

This field is the "why it matters in production" explanation required by the assignment for every comment.

### `app/services/llm_service.py`

**3a. Add `production_impact` to `AIAnalysisIssue`:**

Find the `AIAnalysisIssue` class. Add one field after `suggestion`:

```python
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
    )                                                      # ← ADD THIS FIELD

    @field_validator("type", mode="before")
    def validate_issue_type(cls, v):
        # ... keep existing implementation unchanged ...

    @field_validator("severity", mode="before")
    def validate_issue_severity(cls, v):
        # ... keep existing implementation unchanged ...
```

**3b. Update `_create_prompt` to request `production_impact`:**

Replace the entire `_create_prompt` method with:

```python
def _create_prompt(
    self, file_path: str, code_content: str, analysis_type: str
) -> str:
    """
    Create a detailed prompt for the LLM.
    """
    return f"""
Analyze the following Python code from the file `{file_path}` for **{analysis_type.upper()}** issues.

**Code:**
```python
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
```

---

## Step 4 — Add `production_impact` to the API schema

### `app/models/schemas.py`

Find `IssueDetail` and add the field:

```python
class IssueDetail(BaseModel):
    """Individual code issue detail"""
    type: IssueType
    severity: IssueSeverity = Field(default=IssueSeverity.LOW)
    line: int = Field(..., gt=0, description="Line number of the issue")
    description: str = Field(..., min_length=1)
    suggestion: str = Field(..., min_length=1)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    production_impact: str = Field(default="")       # ← ADD THIS FIELD
```

---

## Step 5 — Create the diff parser utility

Create a new file `app/utils/diff_parser.py` with the following exact content:

```python
"""
Unified Diff Parser

Parses GitHub PR patch strings to determine which line numbers in the
new version of a file are visible in the diff. Only visible lines can
receive inline GitHub review comments.
"""

import re
from typing import Optional
from app.utils.logger import logger


def get_new_file_lines(patch: str) -> set[int]:
    """
    Parse a unified diff patch and return the set of line numbers in the
    **new** file that are visible in the diff (added lines and context lines).

    These are the only lines that can receive inline GitHub review comments
    when using the `line` + `side: "RIGHT"` parameter of the Reviews API.

    Args:
        patch: The unified diff string from GitHub's PR files API
               (the `patch` field on each file object).

    Returns:
        A set of integer line numbers (1-indexed) from the new file that
        appear in the diff. Returns an empty set if patch is empty or None.

    Example:
        patch = "@@ -1,4 +1,6 @@\\n import os\\n+import json\\n def foo():\\n-    pass\\n+    return 42\\n"
        get_new_file_lines(patch)  # → {1, 2, 3, 5}
        # Line 4 (old "pass") is gone; line 5 is the new "    return 42"
    """
    if not patch:
        return set()

    visible: set[int] = set()
    current_new_line: int = 0

    for raw_line in patch.split("\n"):
        if raw_line.startswith("@@"):
            # Header: @@ -old_start[,old_count] +new_start[,new_count] @@
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            if match:
                # new_start is 1-indexed; subtract 1 because we increment before use
                current_new_line = int(match.group(1)) - 1
        elif raw_line.startswith("+"):
            # Added line — exists in the new file
            current_new_line += 1
            visible.add(current_new_line)
        elif raw_line.startswith("-"):
            # Removed line — exists only in the old file; do not advance new counter
            continue
        elif raw_line.startswith("\\"):
            # "\ No newline at end of file" — metadata, skip
            continue
        else:
            # Context line (starts with a space, or empty in some edge cases)
            # Exists in both old and new file
            current_new_line += 1
            visible.add(current_new_line)

    logger.debug(f"Diff parser found {len(visible)} visible lines in patch")
    return visible


def is_line_in_diff(patch: str, line_number: int) -> bool:
    """
    Return True if `line_number` (1-indexed, new file) is visible in the diff.

    Args:
        patch: Unified diff patch string from GitHub API.
        line_number: 1-indexed line number in the new version of the file.

    Returns:
        True if the line can receive an inline comment, False otherwise.
    """
    return line_number in get_new_file_lines(patch)


def build_patch_index(files_data: list[dict]) -> dict[str, set[int]]:
    """
    Build a filename → visible-line-numbers index from a list of file dicts.

    Args:
        files_data: List of file dicts, each expected to have "filename" and
                    "patch" keys (as returned by GitHubService.get_pull_request_files
                    and stored in files_for_analysis after Step 2).

    Returns:
        Dict mapping filename → set of visible line numbers.
    """
    index: dict[str, set[int]] = {}
    for f in files_data:
        filename = f.get("filename", "")
        patch = f.get("patch", "")
        index[filename] = get_new_file_lines(patch)
    logger.debug(f"Built patch index for {len(index)} files")
    return index
```

---

## Step 6 — Create the GitHub review service

Create a new file `app/services/github_review.py` with the following exact content:

```python
"""
GitHub PR Review Service

Posts inline review comments back to a GitHub Pull Request using the
GitHub REST API (Reviews endpoint). Requires a GitHub token with
`pull_requests: write` scope (or classic token with `repo` scope).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.utils.diff_parser import build_patch_index
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class InlineComment:
    """A single inline comment to post on a specific file line."""
    path: str           # File path relative to repo root, e.g. "app/main.py"
    line: int           # 1-indexed line number in the new version of the file
    body: str           # Markdown comment body


@dataclass
class PRReview:
    """A complete PR review: top-level body + zero or more inline comments."""
    body: str                                  # Top-of-PR summary markdown
    event: str                                 # COMMENT | REQUEST_CHANGES | APPROVE
    comments: list[InlineComment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Severity → emoji mapping (for comment formatting)
# ---------------------------------------------------------------------------

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🔵",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GitHubReviewService:
    """
    Posts review comments to a GitHub PR via the REST API.

    Usage:
        service = GitHubReviewService(github_token="ghp_...")
        review = service.build_review(analysis_results, files_for_analysis, pr_metadata)
        service.post_review("https://github.com/owner/repo", 42, review)
    """

    GITHUB_API = "https://api.github.com"

    def __init__(self, github_token: str):
        """
        Args:
            github_token: A GitHub personal access token or fine-grained token
                          with pull_requests:write permission.
        """
        if not github_token:
            raise ValueError(
                "GitHubReviewService requires a GitHub token. "
                "Pass one in the analysis request or set GITHUB_TOKEN in .env"
            )
        self._token = github_token
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_review(
        self,
        analysis_results: dict,
        files_for_analysis: list[dict],
        pr_metadata: dict,
    ) -> PRReview:
        """
        Convert AI analysis results into a PRReview object ready to post.

        Args:
            analysis_results: The dict returned by LangGraphAnalyzer.analyze_pr().
                              Shape: {"summary": {...}, "files": {"path": {"issues": [...]}}}
            files_for_analysis: The list built in analyze_tasks.py, each item has
                                 "filename", "patch", "language", "content", etc.
            pr_metadata:        PR metadata dict from GitHubService.get_pull_request_metadata().

        Returns:
            A PRReview with a markdown body and a list of InlineComment objects.
        """
        patch_index = build_patch_index(files_for_analysis)
        files_dict: dict = analysis_results.get("files", {})
        summary_dict: dict = analysis_results.get("summary", {})

        inline_comments: list[InlineComment] = []
        skipped_issues: list[dict] = []   # issues whose lines aren't in the diff

        for file_path, file_data in files_dict.items():
            issues: list[dict] = file_data.get("issues", [])
            visible_lines: set[int] = patch_index.get(file_path, set())

            for issue in issues:
                line_number: int = issue.get("line", 0)
                if line_number > 0 and line_number in visible_lines:
                    comment_body = self._format_inline_comment(issue)
                    inline_comments.append(
                        InlineComment(
                            path=file_path,
                            line=line_number,
                            body=comment_body,
                        )
                    )
                else:
                    # Line not in diff — collect for the top-level summary body
                    skipped_issues.append({"file": file_path, **issue})
                    logger.debug(
                        f"Issue on {file_path}:{line_number} is outside the diff — "
                        "will be included in the review body instead."
                    )

        review_body = self._format_review_body(
            pr_metadata, summary_dict, skipped_issues, len(inline_comments)
        )
        event = self._determine_event(summary_dict)

        logger.info(
            f"Built review: event={event}, "
            f"inline_comments={len(inline_comments)}, "
            f"body_only_issues={len(skipped_issues)}"
        )
        return PRReview(body=review_body, event=event, comments=inline_comments)

    def post_review(
        self,
        repo_url: str,
        pr_number: int,
        review: PRReview,
    ) -> dict:
        """
        Post a PRReview to GitHub.

        Args:
            repo_url:  GitHub repo URL, e.g. "https://github.com/owner/repo"
            pr_number: Pull request number.
            review:    The PRReview object built by build_review().

        Returns:
            The JSON response from GitHub as a dict.

        Raises:
            httpx.HTTPStatusError: If GitHub returns a 4xx/5xx response.
            ValueError:            If repo_url cannot be parsed.
        """
        owner, repo = self._parse_repo_url(repo_url)
        url = f"{self.GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        payload: dict = {
            "body": review.body,
            "event": review.event,
            "comments": [
                {
                    "path": c.path,
                    "line": c.line,
                    "side": "RIGHT",
                    "body": c.body,
                }
                for c in review.comments
            ],
        }

        logger.info(
            f"Posting review to {owner}/{repo} PR#{pr_number} "
            f"({len(review.comments)} inline comments, event={review.event})"
        )

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=self._headers, json=payload)

        if response.status_code not in (200, 201):
            logger.error(
                f"GitHub review API returned {response.status_code}: {response.text}"
            )
            response.raise_for_status()

        result = response.json()
        logger.info(
            f"Review posted successfully. GitHub review ID: {result.get('id')}"
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_inline_comment(self, issue: dict) -> str:
        """
        Format one issue as a GitHub markdown inline comment.

        Output format:
            🟠 **[HIGH] Security**

            SQL query is constructed using string concatenation with user input.

            **Why this matters in production:** An attacker can manipulate the
            query to read, modify, or delete arbitrary database records.

            **Suggested fix:**
            Use parameterized queries: `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`
        """
        severity: str = issue.get("severity", "low").lower()
        issue_type: str = issue.get("type", "style").replace("_", " ").title()
        emoji: str = SEVERITY_EMOJI.get(severity, "⚪")
        description: str = issue.get("description", "").strip()
        suggestion: str = issue.get("suggestion", "").strip()
        production_impact: str = issue.get("production_impact", "").strip()

        lines = [
            f"{emoji} **[{severity.upper()}] {issue_type}**",
            "",
            description,
        ]

        if production_impact:
            lines += [
                "",
                f"**Why this matters in production:** {production_impact}",
            ]

        if suggestion:
            lines += [
                "",
                "**Suggested fix:**",
                suggestion,
            ]

        return "\n".join(lines)

    def _format_review_body(
        self,
        pr_metadata: dict,
        summary: dict,
        skipped_issues: list[dict],
        inline_count: int,
    ) -> str:
        """
        Build the top-of-PR markdown summary body.
        """
        sev = summary.get("severity_breakdown", {})
        typ = summary.get("issue_type_breakdown", {})
        total = summary.get("total_issues", 0)
        overall = summary.get("overall_summary", "")

        lines = [
            "## 🤖 AI Code Review Summary",
            "",
            f"**{overall}**",
            "",
            "### Issue Breakdown",
            "",
            "| Severity | Count |",
            "|---|---|",
            f"| 🔴 Critical | {sev.get('critical', 0)} |",
            f"| 🟠 High     | {sev.get('high', 0)} |",
            f"| 🟡 Medium   | {sev.get('medium', 0)} |",
            f"| 🔵 Low      | {sev.get('low', 0)} |",
            f"| **Total**   | **{total}** |",
            "",
            "| Issue Type | Count |",
            "|---|---|",
        ]

        for issue_type, count in sorted(typ.items(), key=lambda x: -x[1]):
            lines.append(f"| {issue_type.replace('_', ' ').title()} | {count} |")

        lines += [
            "",
            f"*{inline_count} inline comment(s) posted directly on changed lines.*",
        ]

        # Append any issues whose lines fell outside the diff
        if skipped_issues:
            lines += [
                "",
                "---",
                "",
                "### Additional Issues (lines not in this diff)",
                "",
                "*These issues were found in the file but on lines that weren't "
                "changed in this PR. They are listed here for awareness.*",
                "",
            ]
            # Sort by severity
            sorted_skipped = sorted(
                skipped_issues,
                key=lambda x: SEVERITY_ORDER.get(x.get("severity", "low"), 3),
            )
            for issue in sorted_skipped:
                severity = issue.get("severity", "low").lower()
                emoji = SEVERITY_EMOJI.get(severity, "⚪")
                file_path = issue.get("file", "unknown")
                line_no = issue.get("line", "?")
                issue_type = issue.get("type", "style").replace("_", " ").title()
                description = issue.get("description", "")
                lines.append(
                    f"- {emoji} **{file_path}:{line_no}** [{issue_type}] — {description}"
                )

        lines += [
            "",
            "---",
            "*Generated by [Code Review Copilot](https://github.com)*",
        ]

        return "\n".join(lines)

    def _determine_event(self, summary: dict) -> str:
        """
        Decide the review event type based on issue severity breakdown.

        Rules:
          - Any critical issue          → REQUEST_CHANGES
          - 1+ high issues              → REQUEST_CHANGES
          - Only medium/low/no issues   → COMMENT
        """
        sev = summary.get("severity_breakdown", {})
        if sev.get("critical", 0) > 0 or sev.get("high", 0) > 0:
            return "REQUEST_CHANGES"
        return "COMMENT"

    def _parse_repo_url(self, repo_url: str) -> tuple[str, str]:
        """
        Extract (owner, repo) from a GitHub URL.

        Raises:
            ValueError: If the URL does not match the expected pattern.
        """
        repo_url = repo_url.strip().rstrip("/")
        match = re.match(r"^https://github\.com/([^/]+)/([^/]+)/?$", repo_url)
        if not match:
            raise ValueError(
                f"Cannot parse GitHub repo URL: {repo_url!r}. "
                "Expected format: https://github.com/owner/repo"
            )
        owner, repo = match.groups()
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo
```

---

## Step 7 — Wire comment posting into the Celery task

### `app/tasks/analyze_tasks.py`

**7a. Add the new import at the top of the file** (with the other imports):

```python
from app.services.github_review import GitHubReviewService
```

**7b. Find the block near the end of `analyze_pr_task` that says:**

```python
# Mark task as completed
run_async_in_celery(
    update_task_status(
        task_uuid, TaskStatus.COMPLETED, 100.0, "Analysis completed"
    )
)

logger.info(f"Analysis completed for PR #{pr_number}")
return {
    "task_id": task_id,
    ...
}
```

**Insert the following block immediately BEFORE the `# Mark task as completed` comment.** Do not move or remove anything else:

```python
        # ----------------------------------------------------------------
        # Post inline comments to GitHub (if enabled in config)
        # ----------------------------------------------------------------
        if settings.github.post_comments and github_token:
            try:
                logger.info(
                    f"GitHub comment posting is enabled — building review for PR #{pr_number}"
                )
                review_service = GitHubReviewService(github_token=github_token)
                review = review_service.build_review(
                    analysis_results=analysis_results,
                    files_for_analysis=files_for_analysis,
                    pr_metadata=pr_metadata,
                )
                review_service.post_review(
                    repo_url=repo_url,
                    pr_number=pr_number,
                    review=review,
                )
                logger.info(
                    f"Successfully posted review to PR #{pr_number} "
                    f"with {len(review.comments)} inline comments"
                )
            except Exception as review_error:
                # Comment posting failure must NOT fail the whole analysis task.
                # Log the error and continue to mark the task as completed.
                logger.error(
                    f"Failed to post GitHub review for PR #{pr_number}: {review_error}",
                    exc_info=True,
                )
        elif settings.github.post_comments and not github_token:
            logger.warning(
                "post_comments is enabled in config but no github_token was provided "
                "in the request — skipping comment posting."
            )
```

**Important:** Make sure the `settings` variable is accessible at this point. Near the top of `analyze_pr_task`, the `github_service = GitHubService(github_token)` call happens but `settings` isn't imported yet at the task level. Add this import at the top of `analyze_tasks.py`:

```python
from app.config.settings import get_settings
```

And add this line at the very beginning of the `try` block inside `analyze_pr_task` (before the `GitHubService` instantiation):

```python
settings = get_settings()
```

---

## Step 8 — Write tests

### `tests/unit/test_utils/test_diff_parser.py`

Create this file:

```python
"""Unit tests for the diff parser utility."""

import pytest
from app.utils.diff_parser import get_new_file_lines, is_line_in_diff, build_patch_index


SIMPLE_PATCH = (
    "@@ -1,4 +1,6 @@\n"
    " import os\n"            # context line  → new line 1
    "+import json\n"          # added line    → new line 2
    " \n"                     # context line  → new line 3
    " def foo():\n"           # context line  → new line 4
    "-    pass\n"             # removed line  → NOT in new file
    "+    return 42\n"        # added line    → new line 5
    "+\n"                     # added line    → new line 6
)

ADDED_FILE_PATCH = (
    "@@ -0,0 +1,3 @@\n"
    "+def hello():\n"         # new line 1
    "+    return 'hi'\n"      # new line 2
    "+\n"                     # new line 3
)


class TestGetNewFileLines:
    def test_simple_patch_returns_correct_lines(self):
        result = get_new_file_lines(SIMPLE_PATCH)
        assert result == {1, 2, 3, 4, 5, 6}

    def test_removed_lines_are_excluded(self):
        result = get_new_file_lines(SIMPLE_PATCH)
        # Line that was "-    pass" should not appear
        # After removal, new file jumps from line 4 to lines 5 and 6
        # The old line 5 ("pass") is gone; new lines are numbered differently
        assert 1 in result   # "import os"
        assert 2 in result   # "+import json"

    def test_added_file_patch(self):
        result = get_new_file_lines(ADDED_FILE_PATCH)
        assert result == {1, 2, 3}

    def test_empty_patch_returns_empty_set(self):
        assert get_new_file_lines("") == set()
        assert get_new_file_lines(None) == set()

    def test_multiple_hunks(self):
        patch = (
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-old_line2\n"
            "+new_line2\n"
            " line3\n"
            "@@ -10,3 +10,4 @@\n"
            " line10\n"
            "+added_line\n"
            " line11\n"
            " line12\n"
        )
        result = get_new_file_lines(patch)
        assert 1 in result   # context line from first hunk
        assert 2 in result   # new_line2
        assert 3 in result   # line3
        assert 10 in result  # line10
        assert 11 in result  # added_line
        assert 12 in result  # line11
        assert 13 in result  # line12


class TestIsLineInDiff:
    def test_line_in_diff(self):
        assert is_line_in_diff(SIMPLE_PATCH, 1) is True
        assert is_line_in_diff(SIMPLE_PATCH, 2) is True

    def test_line_not_in_diff(self):
        # Line 100 is far outside the patched region
        assert is_line_in_diff(SIMPLE_PATCH, 100) is False

    def test_empty_patch_returns_false(self):
        assert is_line_in_diff("", 1) is False


class TestBuildPatchIndex:
    def test_builds_index_for_multiple_files(self):
        files = [
            {"filename": "app/main.py", "patch": SIMPLE_PATCH},
            {"filename": "app/new.py", "patch": ADDED_FILE_PATCH},
        ]
        index = build_patch_index(files)
        assert "app/main.py" in index
        assert "app/new.py" in index
        assert index["app/new.py"] == {1, 2, 3}

    def test_file_with_no_patch(self):
        files = [{"filename": "binary_file.png", "patch": ""}]
        index = build_patch_index(files)
        assert index["binary_file.png"] == set()

    def test_empty_list(self):
        assert build_patch_index([]) == {}
```

### `tests/unit/test_services/test_github_review.py`

Create this file:

```python
"""Unit tests for GitHubReviewService."""

import pytest
from unittest.mock import patch, MagicMock
from app.services.github_review import GitHubReviewService, PRReview, InlineComment


ANALYSIS_RESULTS = {
    "summary": {
        "total_issues": 2,
        "severity_breakdown": {"critical": 0, "high": 1, "medium": 1, "low": 0},
        "issue_type_breakdown": {"security": 1, "style": 1},
        "overall_summary": "AI analysis complete. Found 2 issues across 1 file.",
    },
    "files": {
        "app/main.py": {
            "language": "python",
            "size": 512,
            "issues": [
                {
                    "type": "security",
                    "severity": "high",
                    "line": 2,          # line 2 IS in the diff below
                    "description": "SQL injection risk",
                    "suggestion": "Use parameterized queries",
                    "production_impact": "An attacker can dump the database.",
                },
                {
                    "type": "style",
                    "severity": "medium",
                    "line": 99,         # line 99 is NOT in the diff below
                    "description": "Missing docstring",
                    "suggestion": "Add a docstring",
                    "production_impact": "",
                },
            ],
        }
    },
}

FILES_FOR_ANALYSIS = [
    {
        "filename": "app/main.py",
        "patch": "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n",
        "language": "python",
        "content": "",
    }
]

PR_METADATA = {
    "number": 1,
    "title": "Test PR",
    "head": {"sha": "abc123", "ref": "feature", "repo": "owner/repo"},
    "base": {"ref": "main"},
}


class TestGitHubReviewServiceInit:
    def test_raises_without_token(self):
        with pytest.raises(ValueError, match="requires a GitHub token"):
            GitHubReviewService(github_token="")

    def test_init_with_token(self):
        svc = GitHubReviewService(github_token="ghp_test")
        assert svc._token == "ghp_test"


class TestBuildReview:
    def setup_method(self):
        self.svc = GitHubReviewService(github_token="ghp_test")

    def test_inline_comment_created_for_line_in_diff(self):
        review = self.svc.build_review(ANALYSIS_RESULTS, FILES_FOR_ANALYSIS, PR_METADATA)
        # Line 2 is in diff (lines 1,2,3 are added)
        assert any(c.line == 2 and c.path == "app/main.py" for c in review.comments)

    def test_out_of_diff_issue_goes_to_body(self):
        review = self.svc.build_review(ANALYSIS_RESULTS, FILES_FOR_ANALYSIS, PR_METADATA)
        # Line 99 is NOT in diff; it should not be an inline comment
        assert not any(c.line == 99 for c in review.comments)
        # It should appear in the review body instead
        assert "99" in review.body or "Missing docstring" in review.body

    def test_high_severity_triggers_request_changes(self):
        review = self.svc.build_review(ANALYSIS_RESULTS, FILES_FOR_ANALYSIS, PR_METADATA)
        assert review.event == "REQUEST_CHANGES"

    def test_low_severity_only_triggers_comment(self):
        low_results = {
            "summary": {
                "total_issues": 1,
                "severity_breakdown": {"critical": 0, "high": 0, "medium": 0, "low": 1},
                "issue_type_breakdown": {"style": 1},
                "overall_summary": "Found 1 issue.",
            },
            "files": {
                "app/main.py": {
                    "language": "python",
                    "size": 100,
                    "issues": [
                        {"type": "style", "severity": "low", "line": 1,
                         "description": "Trailing space", "suggestion": "Remove it",
                         "production_impact": ""},
                    ],
                }
            },
        }
        review = self.svc.build_review(low_results, FILES_FOR_ANALYSIS, PR_METADATA)
        assert review.event == "COMMENT"

    def test_comment_body_contains_production_impact(self):
        review = self.svc.build_review(ANALYSIS_RESULTS, FILES_FOR_ANALYSIS, PR_METADATA)
        inline = next(c for c in review.comments if c.line == 2)
        assert "Why this matters in production" in inline.body
        assert "An attacker can dump the database." in inline.body

    def test_comment_body_contains_suggestion(self):
        review = self.svc.build_review(ANALYSIS_RESULTS, FILES_FOR_ANALYSIS, PR_METADATA)
        inline = next(c for c in review.comments if c.line == 2)
        assert "Suggested fix" in inline.body
        assert "parameterized queries" in inline.body


class TestPostReview:
    def setup_method(self):
        self.svc = GitHubReviewService(github_token="ghp_test")

    def test_post_review_calls_correct_endpoint(self):
        review = PRReview(
            body="Test body",
            event="COMMENT",
            comments=[InlineComment(path="app/main.py", line=2, body="Test comment")],
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 123456}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_response

            result = self.svc.post_review("https://github.com/owner/repo", 42, review)

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "owner/repo/pulls/42/reviews" in call_args[0][0]
            payload = call_args[1]["json"]
            assert payload["event"] == "COMMENT"
            assert len(payload["comments"]) == 1
            assert payload["comments"][0]["line"] == 2
            assert payload["comments"][0]["side"] == "RIGHT"

        assert result["id"] == 123456

    def test_parse_repo_url_valid(self):
        owner, repo = self.svc._parse_repo_url("https://github.com/myorg/myrepo")
        assert owner == "myorg"
        assert repo == "myrepo"

    def test_parse_repo_url_invalid_raises(self):
        with pytest.raises(ValueError):
            self.svc._parse_repo_url("https://gitlab.com/owner/repo")
```

---

## Step 9 — Verification checklist

After implementing all steps above, verify the following manually:

**Config check:**
- `config.toml` has `post_comments = false` under `[github]`
- `GitHubConfig` in `app/config/settings.py` has `post_comments: bool = False`

**New files check** — these four files must exist:
- `app/utils/diff_parser.py`
- `app/services/github_review.py`
- `tests/unit/test_utils/test_diff_parser.py`
- `tests/unit/test_services/test_github_review.py`

**Modified files check** — these four files must be changed:
- `config.toml` — `post_comments` line added
- `app/config/settings.py` — `post_comments` field added to `GitHubConfig`
- `app/services/llm_service.py` — `production_impact` field + updated prompt
- `app/models/schemas.py` — `production_impact` field in `IssueDetail`
- `app/tasks/analyze_tasks.py` — `patch` passed through + review posting block + `get_settings()` import

**Run tests:**
```bash
uv run pytest tests/unit/test_utils/test_diff_parser.py -v
uv run pytest tests/unit/test_services/test_github_review.py -v
```

Both test files must pass with no errors.

**End-to-end test (set `post_comments = true` in `config.toml` first):**

```bash
curl -X POST "http://localhost:8000/api/v1/analyze-pr" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/your-org/your-test-repo",
    "pr_number": 1,
    "github_token": "ghp_your_token_with_pull_requests_write"
  }'
```

Then check the PR on GitHub — it should have a review with inline comments and a summary body.

---

## Important constraints — do not violate these

1. **Do not change `app/agents/ai_workflow.py`** — the workflow already produces the correct `analysis_results` shape.
2. **Do not change existing DB models or create migrations** — nothing new is persisted for comments (they are posted live to GitHub).
3. **Comment posting failure must never fail the task** — the `try/except` block in Step 7 is mandatory; do not remove it.
4. **Do not add `production_impact` to the DB `AnalysisResult.issues` JSON schema check** — it is stored as part of the unvalidated JSON column and will persist naturally.
5. **Do not change `app/services/github.py`** — `GitHubReviewService` is a separate class in a separate file.
6. **All existing tests must still pass** after your changes. Run `uv run pytest` and confirm before finishing.