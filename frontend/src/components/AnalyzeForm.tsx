import { useCallback, useEffect, useState } from "react";
import { useAnalyzePR } from "../hooks/useAnalyzePR";
import type { AnalysisRequest } from "../types/api";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { Card } from "./ui/Card";

const REPO_URL_PATTERN = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

interface FormErrors {
  repo_url?: string;
  pr_number?: string;
}

interface AnalyzeFormProps {
  onSuccess?: (taskId: string) => void;
}

export function AnalyzeForm({ onSuccess }: AnalyzeFormProps) {
  const { submit, isSubmitting, error: submitError, data } = useAnalyzePR();

  useEffect(() => {
    if (data?.task_id) {
      onSuccess?.(data.task_id);
    }
  }, [data, onSuccess]);

  const [repoUrl, setRepoUrl] = useState("");
  const [prNumber, setPrNumber] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [formErrors, setFormErrors] = useState<FormErrors>({});

  const validate = useCallback((): boolean => {
    const errors: FormErrors = {};

    if (!repoUrl.trim()) {
      errors.repo_url = "Repository URL is required";
    } else if (!REPO_URL_PATTERN.test(repoUrl.trim())) {
      errors.repo_url = "Must match https://github.com/owner/repo";
    }

    const num = Number(prNumber);
    if (!prNumber.trim()) {
      errors.pr_number = "PR number is required";
    } else if (!Number.isInteger(num) || num < 1) {
      errors.pr_number = "PR number must be a positive integer";
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  }, [repoUrl, prNumber]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!validate()) return;

      const request: AnalysisRequest = {
        repo_url: repoUrl.trim(),
        pr_number: Number(prNumber),
        github_token: githubToken.trim() || undefined,
      };

      try {
        await submit(request);
      } catch {
        // Error is captured by useAnalyzePR; nothing extra to do.
      }
    },
    [repoUrl, prNumber, githubToken, validate, submit],
  );

  const handleReset = useCallback(() => {
    setRepoUrl("");
    setPrNumber("");
    setGithubToken("");
    setFormErrors({});
  }, []);

  // Extract a human-readable error string, including 422 detail from the backend.
  const displayError = submitError
    ? submitError.message
    : null;

  return (
    <Card header="Submit PR for Analysis">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Repository URL"
          type="text"
          placeholder="https://github.com/owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          error={formErrors.repo_url}
          disabled={isSubmitting}
        />

        <Input
          label="PR Number"
          type="number"
          placeholder="42"
          min={1}
          value={prNumber}
          onChange={(e) => setPrNumber(e.target.value)}
          error={formErrors.pr_number}
          disabled={isSubmitting}
        />

        <Input
          label="GitHub Token (optional)"
          type="password"
          placeholder="ghp_..."
          value={githubToken}
          onChange={(e) => setGithubToken(e.target.value)}
          hint="Required for private repositories"
          disabled={isSubmitting}
        />

        {displayError && (
          <div
            className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger font-mono"
            role="alert"
          >
            {displayError}
          </div>
        )}

        {data && (
          <div
            className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-sm font-mono"
            role="status"
          >
            <span className="text-success font-semibold">Task queued — </span>
            <span className="text-text-muted">
              ID: <span className="text-text">{data.task_id}</span>
            </span>
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <Button type="submit" variant="primary" disabled={isSubmitting}>
            {isSubmitting ? "Submitting…" : "Analyze PR"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={handleReset}
            disabled={isSubmitting}
          >
            Reset
          </Button>
        </div>
      </form>
    </Card>
  );
}
