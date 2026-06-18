import { useCallback, useState } from "react";
import { useTasks } from "../hooks/useTasks";
import { TaskStatus } from "../types/api";
import type { TaskStatus as TaskStatusType } from "../types/api";
import { Button } from "./ui/Button";
import { Select } from "./ui/Select";
import { Badge } from "./ui/Badge";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";

const STATUS_OPTIONS = [
  "all",
  TaskStatus.PENDING,
  TaskStatus.PROCESSING,
  TaskStatus.COMPLETED,
  TaskStatus.FAILED,
  TaskStatus.CANCELLED,
];

const DEFAULT_LIMIT = 10;

interface TaskListProps {
  selectedTaskId?: string;
  onSelectTask: (id: string) => void;
}

export function TaskList({ selectedTaskId, onSelectTask }: TaskListProps) {
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const activeStatus =
    statusFilter === "all" ? undefined : (statusFilter as TaskStatusType);

  const { tasks, total_count, has_more, isLoading, error } = useTasks(
    DEFAULT_LIMIT,
    offset,
    activeStatus,
  );

  const handlePrev = useCallback(() => {
    setOffset((prev) => Math.max(0, prev - DEFAULT_LIMIT));
  }, []);

  const handleNext = useCallback(() => {
    setOffset((prev) => prev + DEFAULT_LIMIT);
  }, []);

  const handleStatusChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setStatusFilter(e.target.value);
    setOffset(0);
  }, []);

  const formatDate = (iso: string): string => {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const extractOwnerRepo = (url: string): string => {
    // "https://github.com/owner/repo" → "owner/repo"
    try {
      const parts = new URL(url).pathname.split("/").filter(Boolean);
      return parts.slice(0, 2).join("/");
    } catch {
      return url;
    }
  };

  return (
    <Card
      header={
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-text">
            Analysis Tasks
          </span>
          <Select
            label="Filter by status"
            id="status-filter"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={handleStatusChange}
            className="w-40"
          />
        </div>
      }
      padded={false}
    >
      {isLoading && tasks.length === 0 ? (
        <div className="py-12 text-center text-sm text-text-dim font-mono">
          Loading tasks…
        </div>
      ) : error ? (
        <div className="py-12 text-center text-sm text-danger font-mono" role="alert">
          Failed to load tasks: {error.message}
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState
          title="No tasks found"
          message="Submit a PR for analysis to see it here."
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-mono">
              <thead>
                <tr className="border-b border-border bg-surface-raised/30 text-left text-xs text-text-dim uppercase tracking-wider">
                  <th className="px-4 py-2.5 font-medium">Repository</th>
                  <th className="px-4 py-2.5 font-medium">PR</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Created</th>
                  <th className="px-4 py-2.5 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr
                    key={task.task_id}
                    className={[
                      "border-b border-border/50 transition-colors duration-100",
                      "hover:bg-surface-raised/40",
                      selectedTaskId === task.task_id
                        ? "bg-surface-raised/60"
                        : "",
                    ].join(" ")}
                  >
                    <td className="px-4 py-2.5 text-text truncate max-w-[20rem]">
                      {extractOwnerRepo(task.repo_url)}
                    </td>
                    <td className="px-4 py-2.5 text-text-muted">
                      #{task.pr_number}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant={task.status}>
                        {task.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-text-dim whitespace-nowrap">
                      {formatDate(task.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onSelectTask(task.task_id)}
                      >
                        View
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination bar */}
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs font-mono text-text-dim">
            <span>
              Showing {offset + 1}–{offset + tasks.length} of {total_count}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={handlePrev}
                disabled={offset === 0}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleNext}
                disabled={!has_more}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
