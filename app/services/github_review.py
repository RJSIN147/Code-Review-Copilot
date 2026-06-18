"""
GitHub PR Review Service

Posts inline review comments back to a GitHub Pull Request using the
GitHub REST API (Reviews endpoint). Requires a GitHub token with
`pull_requests: write` scope (or classic token with `repo` scope).
"""

import re
from dataclasses import dataclass, field

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

            # Handle case where user runs analysis on their own PR
            if response.status_code == 422 and "Review Can not request changes on your own pull request" in response.text:
                logger.warning(
                    f"Cannot request changes on own pull request for PR #{pr_number}. "
                    "Retrying review posting with event=COMMENT instead."
                )
                payload["event"] = "COMMENT"
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
