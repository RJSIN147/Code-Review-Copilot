import useSWR from "swr";
import { listTasks } from "../services/api";
import type { TaskListResponse, TaskStatus } from "../types/api";

export type TasksHookKey = ["tasks", number, number, TaskStatus | undefined];

export interface UseTasksOptions {
  limit: number;
  offset: number;
  status_filter?: TaskStatus;
}

export interface UseTasksResult {
  tasks: TaskListResponse["tasks"];
  total_count: number;
  has_more: boolean;
  isLoading: boolean;
  error: Error | undefined;
  mutate: ReturnType<typeof useSWR<TaskListResponse>>["mutate"];
}

export function buildTasksKey(
  limit: number,
  offset: number,
  status_filter?: TaskStatus,
): TasksHookKey {
  return ["tasks", limit, offset, status_filter];
}

export function useTasks(
  limit: number,
  offset: number,
  status_filter?: TaskStatus,
): UseTasksResult {
  const { data, error, isLoading, mutate } = useSWR<TaskListResponse>(
    buildTasksKey(limit, offset, status_filter),
    ([, paramsLimit, paramsOffset, paramsStatus]: TasksHookKey) =>
      listTasks({
        limit: paramsLimit,
        offset: paramsOffset,
        status_filter: paramsStatus,
      }),
    {
      revalidateOnFocus: true,
      refreshWhenHidden: false,
      errorRetryCount: 3,
    },
  );

  return {
    tasks: data?.tasks ?? [],
    total_count: data?.total_count ?? 0,
    has_more: data?.has_more ?? false,
    isLoading,
    error,
    mutate,
  };
}
