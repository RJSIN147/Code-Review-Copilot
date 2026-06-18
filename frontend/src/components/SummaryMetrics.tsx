import useSWR from "swr";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Badge } from "./ui/Badge";
import { useTaskStatus } from "../hooks/useTaskStatus";
import { getSummary } from "../services/api";
import type { AnalysisSummaryResponse } from "../types/api";

interface SummaryMetricsProps {
  taskId: string;
}

interface MetricCardProps {
  label: string;
  value: string | number;
  accent?: boolean;
}

function MetricCard({ label, value, accent }: MetricCardProps) {
  return (
    <div className="rounded-sm border border-border bg-surface-raised/50 p-3">
      <span className="text-xs text-text-dim block mb-1">{label}</span>
      <span
        className={[
          "text-lg font-mono font-semibold",
          accent ? "text-accent" : "text-text",
        ].join(" ")}
      >
        {value}
      </span>
    </div>
  );
}

export function SummaryMetrics({ taskId }: SummaryMetricsProps) {
  const { task } = useTaskStatus(taskId);
  const isCompleted = task?.status === "completed";

  const { data: summary, isLoading } = useSWR<AnalysisSummaryResponse>(
    isCompleted ? ["summary", taskId] : null,
    () => getSummary(taskId),
    { revalidateOnFocus: false },
  );

  if (!taskId) {
    return (
      <EmptyState
        title="No Task Selected"
        message="Select a completed task to view summary metrics."
      />
    );
  }

  if (!isCompleted) {
    return (
      <EmptyState
        title="Task Not Completed"
        message="Summary metrics are available only for completed tasks."
      />
    );
  }

  if (isLoading) {
    return (
      <Card header="Summary Metrics">
        <div className="py-6 text-center">
          <span className="text-xs text-text-dim font-mono">Loading metrics…</span>
        </div>
      </Card>
    );
  }

  if (!summary) {
    return (
      <EmptyState
        title="No Summary Available"
        message="Summary data could not be loaded for this task."
      />
    );
  }

  return (
    <Card header="Summary Metrics">
      <div className="space-y-4">
        {/* Top-level counts */}
        <div className="grid grid-cols-2 gap-3">
          <MetricCard label="Total Files" value={summary.total_files} />
          <MetricCard label="Total Issues" value={summary.total_issues} accent />
        </div>

        {/* Severity breakdown */}
        <div>
          <span className="text-xs text-text-dim block mb-2">Severity Breakdown</span>
          <div className="grid grid-cols-4 gap-2">
            <div className="rounded-sm border border-severity-critical/30 bg-severity-critical/5 p-2 text-center">
              <Badge variant="critical" className="mb-1">
                Critical
              </Badge>
              <span className="text-sm font-mono font-semibold text-severity-critical block">
                {summary.critical_issues}
              </span>
            </div>
            <div className="rounded-sm border border-severity-high/30 bg-severity-high/5 p-2 text-center">
              <Badge variant="high" className="mb-1">
                High
              </Badge>
              <span className="text-sm font-mono font-semibold text-severity-high block">
                {summary.high_issues}
              </span>
            </div>
            <div className="rounded-sm border border-severity-medium/30 bg-severity-medium/5 p-2 text-center">
              <Badge variant="medium" className="mb-1">
                Medium
              </Badge>
              <span className="text-sm font-mono font-semibold text-severity-medium block">
                {summary.medium_issues}
              </span>
            </div>
            <div className="rounded-sm border border-severity-low/30 bg-severity-low/5 p-2 text-center">
              <Badge variant="low" className="mb-1">
                Low
              </Badge>
              <span className="text-sm font-mono font-semibold text-severity-low block">
                {summary.low_issues}
              </span>
            </div>
          </div>
        </div>

        {/* Scores */}
        <div>
          <span className="text-xs text-text-dim block mb-2">Scores</span>
          <div className="grid grid-cols-2 gap-3">
            <MetricCard
              label="Code Quality"
              value={summary.code_quality_score.toFixed(2)}
              accent
            />
            <MetricCard
              label="Maintainability"
              value={summary.maintainability_score.toFixed(2)}
              accent
            />
          </div>
        </div>
      </div>
    </Card>
  );
}
