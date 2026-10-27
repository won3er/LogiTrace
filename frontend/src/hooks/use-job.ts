"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { JobSchema, type Job } from "@/lib/types";

/** Acompanha uma tarefa assíncrona do backend até concluir (sucesso ou falha). */
export function useJob(jobId: number | null | undefined) {
  return useQuery<Job>({
    queryKey: ["job", jobId],
    queryFn: () => api(`/jobs/${jobId}`, { schema: JobSchema }),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "success" || s === "failed" ? false : 1000;
    },
  });
}
