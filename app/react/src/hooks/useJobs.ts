import { useState, useCallback } from 'react';
import { apiCreateJob, apiFetchJobDetail } from '../lib/api';

interface JobState {
  jobId: string | null;
  status: string | null;
  loading: boolean;
  error: string | null;
}

export function useJobs() {
  const [state, setState] = useState<JobState>({
    jobId: null,
    status: null,
    loading: false,
    error: null,
  });

  const createJob = useCallback(async (type: string, payload: Record<string, unknown>) => {
    setState({ jobId: null, status: null, loading: true, error: null });
    try {
      const res = await apiCreateJob(type, payload);
      if (res.error) {
        setState({ jobId: null, status: null, loading: false, error: res.error.message });
        return null;
      }
      setState({ jobId: res.data.job_id, status: res.data.status, loading: false, error: null });
      return res.data.job_id;
    } catch {
      setState({ jobId: null, status: null, loading: false, error: 'Job 생성 실패' });
      return null;
    }
  }, []);

  const pollJob = useCallback(async (jobId: string) => {
    try {
      const res = await apiFetchJobDetail(jobId);
      if (res.data) {
        setState((s) => ({ ...s, status: res.data.status }));
      }
      return res.data?.status ?? null;
    } catch {
      return null;
    }
  }, []);

  return { ...state, createJob, pollJob };
}
