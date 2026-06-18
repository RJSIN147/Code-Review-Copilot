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
