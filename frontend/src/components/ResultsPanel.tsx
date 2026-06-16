import { useState } from "react";
import useSWR from "swr";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Badge } from "./ui/Badge";
import { useTaskStatus } from "../hooks/useTaskStatus";
import { getResults } from "../services/api";
import type { AnalysisResponse, FileResult, Issue, IssueType, IssueSeverity } from "../types/api";

interface ResultsPanelProps {
  taskId: string;
}

interface FileRowProps {
  file: FileResult;
  index: number;
}

function issueTypeToLabel(type: IssueType): string {
  const labels: Record<IssueType, string> = {
    style: "Style",
    bug: "Bug",
    performance: "Performance",
    security: "Security",
    maintainability: "Maintainability",
    best_practice: "Best Practice",
  };
  return labels[type];
}

function severityToBadgeVariant(severity: IssueSeverity): Parameters<typeof Badge>[0]["variant"] {
  return severity as Parameters<typeof Badge>[0]["variant"];
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function IssueItem({ issue }: { issue: Issue }) {
  return (
    <div className="border-l-2 border-border pl-4 py-3 space-y-2">
      {/* Badges + line */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={issue.type as Parameters<typeof Badge>[0]["variant"]}>
          {issueTypeToLabel(issue.type)}
        </Badge>
        <Badge variant={severityToBadgeVariant(issue.severity)}>
          {issue.severity}
        </Badge>
        <span className="text-xs text-text-dim font-mono">
          Line {issue.line}
        </span>
        <span className="text-xs text-text-dim font-mono ml-auto">
          {(issue.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      {/* Description */}
      <p className="text-sm text-text">{issue.description}</p>

      {/* Suggestion */}
      {issue.suggestion && (
        <div className="rounded-sm bg-surface-raised/60 p-2 border border-border">
          <span className="text-xs text-text-dim block mb-0.5">Suggestion</span>
          <span className="text-xs text-text-muted font-mono">
            {issue.suggestion}
          </span>
        </div>
      )}
    </div>
  );
}

function FileRow({ file, index }: FileRowProps) {
  const [expanded, setExpanded] = useState(false);
  const hasIssues = file.issues.length > 0;

  return (
    <div className={index > 0 ? "border-t border-border" : ""}>
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-raised/30 transition-colors duration-150"
        onClick={() => hasIssues && setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-sm text-text font-mono truncate">
            {file.name}
          </span>
          {file.language && (
            <span className="text-xs text-text-dim font-mono bg-surface-raised px-1.5 py-0.5 rounded-sm">
              {file.language}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-text-dim font-mono">
            {formatFileSize(file.size)}
          </span>
          {hasIssues && (
            <Badge variant="high">
              {file.issues.length} issue{file.issues.length !== 1 ? "s" : ""}
            </Badge>
          )}
          {hasIssues && (
            <span
              className={[
                "text-xs text-text-dim transition-transform duration-200",
                expanded ? "rotate-90" : "",
              ].join(" ")}
            >
              ▶
            </span>
          )}
        </div>
      </button>

      {/* Collapsible issues */}
      {expanded && hasIssues && (
        <div className="px-4 pb-3 space-y-1">
          {file.issues.map((issue, i) => (
            <IssueItem key={i} issue={issue} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ResultsPanel({ taskId }: ResultsPanelProps) {
  const { task } = useTaskStatus(taskId);
  const isCompleted = task?.status === "completed";
  const isFailed = task?.status === "failed";

  const { data: results, isLoading } = useSWR<AnalysisResponse>(
    isCompleted ? ["results", taskId] : null,
    () => getResults(taskId),
    { revalidateOnFocus: false },
  );

  if (!taskId) {
    return (
      <EmptyState
        title="No Task Selected"
        message="Select a task to view analysis results."
      />
    );
  }

  if (isFailed) {
    return (
      <Card header="Analysis Results">
        <div className="rounded-sm border border-danger/30 bg-danger/5 p-4">
          <span className="text-sm text-danger font-mono block">
            {task?.error_message || "Analysis failed with an unknown error."}
          </span>
        </div>
      </Card>
    );
  }

  if (!isCompleted) {
    return (
      <EmptyState
        title="Results Not Available"
        message="Results are available only for completed tasks."
      />
    );
  }

  if (isLoading) {
    return (
      <Card header="Analysis Results">
        <div className="py-6 text-center">
          <span className="text-xs text-text-dim font-mono">Loading results…</span>
        </div>
      </Card>
    );
  }

  if (!results || results.files.length === 0) {
    return (
      <EmptyState
        title="No Results"
        message="No files were analyzed for this task."
      />
    );
  }

  return (
    <Card header="Analysis Results" padded={false}>
      <div className="divide-y divide-border">
        {results.files.map((file, index) => (
          <FileRow key={file.path} file={file} index={index} />
        ))}
      </div>
    </Card>
  );
}
