/**
 * API type definitions for the Code Review Copilot backend.
 *
 * These interfaces mirror the Pydantic schemas in
 * `app/models/schemas.py` and the SQLModel enums in
 * `app/models/database.py`. The backend is mounted at `/api/v1`.
 */

// ---------------------------------------------------------------------------
// Enums (string literal unions + runtime const objects)
//
// `erasableSyntaxOnly` is enabled in tsconfig, so native `enum` is not
// available. The pattern below gives the same surface area: a const object
// for runtime iteration and a derived union type for compile-time checks.
// ---------------------------------------------------------------------------

export const TaskStatus = {
  PENDING: "pending",
  PROCESSING: "processing",
  COMPLETED: "completed",
  FAILED: "failed",
  CANCELLED: "cancelled",
} as const;
export type TaskStatus = (typeof TaskStatus)[keyof typeof TaskStatus];

export const IssueType = {
  STYLE: "style",
  BUG: "bug",
  PERFORMANCE: "performance",
  SECURITY: "security",
  MAINTAINABILITY: "maintainability",
  BEST_PRACTICE: "best_practice",
} as const;
export type IssueType = (typeof IssueType)[keyof typeof IssueType];

export const IssueSeverity = {
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
} as const;
export type IssueSeverity = (typeof IssueSeverity)[keyof typeof IssueSeverity];

// ---------------------------------------------------------------------------
// Request models
// ---------------------------------------------------------------------------

/** Body for `POST /api/v1/analyze-pr`. */
export interface AnalysisRequest {
  repo_url: string;
  pr_number: number;
  github_token?: string | null;
}

/** Body for `DELETE /api/v1/tasks/{task_id}`. */
export interface TaskCancelRequest {
  reason?: string | null;
}

// ---------------------------------------------------------------------------
// Response models
// ---------------------------------------------------------------------------

/** Generic task response returned from analyze and cancel endpoints. */
export interface TaskResponse {
  task_id: string;
  status: TaskStatus;
  message: string;
}

/** Detailed status response from `GET /api/v1/status/{task_id}`. */
export interface TaskStatusResponse {
  task_id: string;
  status: TaskStatus;
  progress: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  retry_count: number;
}

/** A single code issue attached to a file result. */
export interface Issue {
  type: IssueType;
  severity: IssueSeverity;
  line: number;
  description: string;
  suggestion: string;
  confidence: number;
}

/** File-level analysis result, embedded in `AnalysisResponse.files`. */
export interface FileResult {
  name: string;
  path: string;
  language: string | null;
  size: number;
  issues: Issue[];
}

/** Aggregate metrics for a finished analysis. */
export interface AnalysisSummary {
  total_files: number;
  total_issues: number;
  critical_issues: number;
  high_issues: number;
  medium_issues: number;
  low_issues: number;
  style_issues: number;
  bug_issues: number;
  performance_issues: number;
  security_issues: number;
  maintainability_issues: number;
  best_practice_issues: number;
  code_quality_score: number;
  maintainability_score: number;
}

/** Full result payload from `GET /api/v1/results/{task_id}`. */
export interface AnalysisResponse {
  task_id: string;
  status: TaskStatus;
  progress: number;
  files: FileResult[];
  summary: AnalysisSummary | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  analysis_duration?: number | null;
  error_message?: string | null;
}

/** Response shape for `GET /api/v1/results/{task_id}/summary`. */
export type AnalysisSummaryResponse = AnalysisSummary;

/** Single entry in the list-tasks response. */
export interface TaskListItem {
  task_id: string;
  repo_url: string;
  pr_number: number;
  status: TaskStatus;
  progress: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** Response shape for `GET /api/v1/tasks`. */
export interface TaskListResponse {
  tasks: TaskListItem[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** Generic error envelope returned by the backend. */
export interface ErrorResponse {
  error: string;
  detail?: string | null;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Query parameter shapes (consumed by the typed client)
// ---------------------------------------------------------------------------

export interface ListTasksParams {
  limit?: number;
  offset?: number;
  status_filter?: TaskStatus | string;
}
