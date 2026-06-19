import { mutate } from "swr";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Badge } from "./ui/Badge";
import { useTaskStatus } from "../hooks/useTaskStatus";
import { cancelTask } from "../services/api";
import { buildTaskStatusKey } from "../hooks/useTaskStatus";
import type { TaskStatus } from "../types/api";

interface TaskStatusCardProps {
  taskId: string;
}

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function statusToBadgeVariant(status: TaskStatus): Parameters<typeof Badge>[0]["variant"] {
  return status as Parameters<typeof Badge>[0]["variant"];
}

export function TaskStatusCard({ taskId }: TaskStatusCardProps) {
  const { task, isLoading, error } = useTaskStatus(taskId);

  if (!taskId) {
    return (
      <EmptyState
        title="No Task Selected"
        message="Select or submit a task to view its status."
      />
    );
  }

  if (isLoading && !task) {
    return (
      <Card header="Task Status">
        <div className="flex items-center gap-3 py-4">
          <div className="h-1 w-full bg-surface-raised rounded-sm overflow-hidden">
            <div className="h-full bg-info/60 animate-pulse rounded-sm" style={{ width: "0%" }} />
          </div>
          <span className="text-xs text-text-dim font-mono">Loading…</span>
        </div>
      </Card>
    );
  }

  if (error || !task) {
    return (
      <EmptyState
        title="Task Not Found"
        message={`No task found with ID ${taskId}.`}
      />
    );
  }

  const isActive = task.status === "pending" || task.status === "processing";

  const handleCancel = async () => {
    try {
      await cancelTask(taskId);
      await mutate(buildTaskStatusKey(taskId));
    } catch {
      // SWR will retry on its own; surface is unchanged
    }
  };

  return (
    <Card
      header={
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-text">Task Status</span>
          <Badge variant={statusToBadgeVariant(task.status)}>
            {task.status}
          </Badge>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Task ID */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-dim font-mono">ID</span>
          <span className="text-xs text-text-muted font-mono truncate">
            {task.task_id}
          </span>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-text-dim">Progress</span>
            <span className="text-xs text-text-muted font-mono">
              {task.progress.toFixed(1)}%
            </span>
          </div>
          <div className="h-2 w-full bg-surface-raised rounded-sm overflow-hidden">
            <div
              className={[
                "h-full rounded-sm transition-all duration-500",
                task.status === "failed"
                  ? "bg-danger"
                  : task.status === "completed"
                    ? "bg-success"
                    : task.status === "cancelled"
                      ? "bg-text-dim"
                      : "bg-info",
              ].join(" ")}
              style={{ width: `${Math.min(task.progress, 100)}%` }}
            />
          </div>
          {task.status_message && (
            <p className="mt-2 text-xs text-text-dim font-mono truncate">
              {task.status_message}
            </p>
          )}
        </div>

        {/* Timestamps */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <span className="text-xs text-text-dim block">Created</span>
            <span className="text-xs text-text-muted font-mono">
              {formatTimestamp(task.created_at)}
            </span>
          </div>
          <div>
            <span className="text-xs text-text-dim block">Started</span>
            <span className="text-xs text-text-muted font-mono">
              {formatTimestamp(task.started_at)}
            </span>
          </div>
          <div>
            <span className="text-xs text-text-dim block">Completed</span>
            <span className="text-xs text-text-muted font-mono">
              {formatTimestamp(task.completed_at)}
            </span>
          </div>
        </div>

        {/* Retry count */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-dim">Retries</span>
          <span className="text-xs text-text-muted font-mono">
            {task.retry_count}
          </span>
        </div>

        {/* Error message */}
        {task.error_message && (
          <div className="rounded-sm border border-danger/30 bg-danger/5 p-3">
            <span className="text-xs text-danger font-mono block">
              {task.error_message}
            </span>
          </div>
        )}

        {/* Cancel button */}
        {isActive && (
          <div className="flex justify-end pt-1">
            <Button variant="secondary" size="sm" onClick={handleCancel}>
              Cancel
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
