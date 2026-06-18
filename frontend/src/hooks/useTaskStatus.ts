import useSWR from "swr";
import { getTaskStatus } from "../services/api";
import type { TaskStatusResponse, TaskStatus } from "../types/api";

export type TaskStatusHookKey = ["task-status", string];

export interface UseTaskStatusResult {
  task: TaskStatusResponse | undefined;
  isLoading: boolean;
  error: Error | undefined;
}

export function buildTaskStatusKey(taskId: string): TaskStatusHookKey {
  return ["task-status", taskId];
}

export function useTaskStatus(taskId: string | undefined): UseTaskStatusResult {
  const { data, error, isLoading } = useSWR<TaskStatusResponse>(
    taskId ? buildTaskStatusKey(taskId) : null,
    ([, id]: TaskStatusHookKey) => getTaskStatus(id),
    {
      refreshInterval: (data: TaskStatusResponse | undefined) => {
        const status = data?.status as TaskStatus | undefined;
        return status === "pending" || status === "processing" ? 2000 : 0;
      },
      revalidateOnFocus: true,
      refreshWhenHidden: false,
      errorRetryCount: 3,
    },
  );

  return {
    task: data,
    isLoading,
    error,
  };
}
