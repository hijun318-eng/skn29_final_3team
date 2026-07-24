import { useState, useEffect, useCallback } from 'react';
import { apiFetchVocs, type VOCEntity } from '../lib/api';

interface VOCState {
  vocs: VOCEntity[];
  loading: boolean;
  error: string | null;
  total: number;
}

export function useVocs(pollInterval?: number) {
  const [state, setState] = useState<VOCState>({
    vocs: [],
    loading: true,
    error: null,
    total: 0,
  });

  const fetchVocs = useCallback(async () => {
    try {
      const res = await apiFetchVocs({ page: 1, limit: 50 });
      if (res.error) {
        setState({ vocs: [], loading: false, error: res.error.message, total: 0 });
        return;
      }
      setState({ vocs: res.data, loading: false, error: null, total: res.meta.total ?? res.data.length });
    } catch {
      setState((s) => ({ ...s, loading: false, error: 'VOC 조회 실패' }));
    }
  }, []);

  useEffect(() => {
    fetchVocs();
    if (pollInterval) {
      const id = setInterval(fetchVocs, pollInterval);
      return () => clearInterval(id);
    }
  }, [fetchVocs, pollInterval]);

  return { ...state, refetch: fetchVocs };
}
