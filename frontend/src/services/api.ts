/**
 * Typed fetch client for the Code Review Copilot backend.
 *
 * All requests are prefixed with `/api/v1` and go through the `apiFetch`
 * wrapper. In dev, Vite proxies `/api` to the backend at
 * `http://localhost:8000`. In production, the same prefix is expected to
 * be served behind the same origin.
 */

import type {
  AnalysisRequest,
  AnalysisResponse,
  AnalysisSummaryResponse,
  ListTasksParams,
  TaskCancelRequest,
  TaskListResponse,
  TaskResponse,
  TaskStatusResponse,
} from "../types/api";

const API_PREFIX = "/api/v1";

/**
 * Thrown for any non-2xx response from the backend. Carries the HTTP
 * status and the parsed body (best-effort: may be `null` if the body
 * was empty or not valid JSON).
 */
export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface ApiFetchOptions {
  method?: "GET" | "POST" | "DELETE" | "PUT" | "PATCH";
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: ApiFetchOptions["query"]): string {
  const base = path.startsWith(API_PREFIX) ? path : `${API_PREFIX}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs.length > 0 ? `${base}?${qs}` : base;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * Internal fetch wrapper. Sets JSON headers, parses the response, and
 * throws a typed `ApiError` on any non-2xx status.
 */
export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { method = "GET", query, body, signal } = options;
  const url = buildUrl(path, query);

  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  let payload: BodyInit | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const response = await fetch(url, {
    method,
    headers,
    body: payload,
    signal,
  });

  const parsed = await parseBody(response);

  if (!response.ok) {
    const message =
      parsed &&
      typeof parsed === "object" &&
      "detail" in parsed &&
      typeof (parsed as { detail: unknown }).detail === "string"
        ? ((parsed as { detail: string }).detail)
        : response.statusText || `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, parsed);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Endpoint functions
// ---------------------------------------------------------------------------

/**
 * `POST /api/v1/analyze-pr` — submit a GitHub PR for analysis.
 * Returns 202 with a `TaskResponse` on success.
 */
export function analyzePR(
  request: AnalysisRequest,
  options: { signal?: AbortSignal } = {},
): Promise<TaskResponse> {
  return apiFetch<TaskResponse>("/analyze-pr", {
    method: "POST",
    body: request,
    signal: options.signal,
  });
}

/**
 * `DELETE /api/v1/tasks/{task_id}` — cancel a pending or running task.
 */
export function cancelTask(
  taskId: string,
  request: TaskCancelRequest = {},
  options: { signal?: AbortSignal } = {},
): Promise<TaskResponse> {
  return apiFetch<TaskResponse>(`/tasks/${taskId}`, {
    method: "DELETE",
    body: request,
    signal: options.signal,
  });
}

/**
 * `GET /api/v1/tasks` — list recent analysis tasks with optional filtering.
 */
export function listTasks(
  params: ListTasksParams = {},
  options: { signal?: AbortSignal } = {},
): Promise<TaskListResponse> {
  return apiFetch<TaskListResponse>("/tasks", {
    method: "GET",
    query: {
      limit: params.limit,
      offset: params.offset,
      status_filter: params.status_filter as string | undefined,
    },
    signal: options.signal,
  });
}

/**
 * `GET /api/v1/status/{task_id}` — fetch task status and progress.
 */
export function getTaskStatus(
  taskId: string,
  options: { signal?: AbortSignal } = {},
): Promise<TaskStatusResponse> {
  return apiFetch<TaskStatusResponse>(`/status/${taskId}`, {
    method: "GET",
    signal: options.signal,
  });
}

/**
 * `GET /api/v1/results/{task_id}` — fetch the full analysis results.
 */
export function getResults(
  taskId: string,
  options: { signal?: AbortSignal } = {},
): Promise<AnalysisResponse> {
  return apiFetch<AnalysisResponse>(`/results/${taskId}`, {
    method: "GET",
    signal: options.signal,
  });
}

/**
 * `GET /api/v1/results/{task_id}/summary` — fetch just the summary metrics.
 */
export function getSummary(
  taskId: string,
  options: { signal?: AbortSignal } = {},
): Promise<AnalysisSummaryResponse> {
  return apiFetch<AnalysisSummaryResponse>(`/results/${taskId}/summary`, {
    method: "GET",
    signal: options.signal,
  });
}
