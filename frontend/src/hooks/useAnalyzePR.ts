import { useState, useCallback } from "react";
import { useSWRConfig } from "swr";
import { analyzePR } from "../services/api";
import type { AnalysisRequest, TaskResponse } from "../types/api";
import { buildTasksKey } from "./useTasks";

export interface UseAnalyzePRResult {
  submit: (request: AnalysisRequest) => Promise<void>;
  isSubmitting: boolean;
  error: Error | null;
  data: TaskResponse | null;
}

export function useAnalyzePR(): UseAnalyzePRResult {
  const { mutate } = useSWRConfig();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [data, setData] = useState<TaskResponse | null>(null);

  const submit = useCallback(
    async (request: AnalysisRequest): Promise<void> => {
      setIsSubmitting(true);
      setError(null);
      setData(null);

      try {
        const response = await analyzePR(request);
        setData(response);

        // Revalidate every cached task list so the new task appears.
        await mutate(
          (key) => Array.isArray(key) && key[0] === buildTasksKey(0, 0)[0],
        );
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsSubmitting(false);
      }
    },
    [mutate],
  );

  return {
    submit,
    isSubmitting,
    error,
    data,
  };
}
