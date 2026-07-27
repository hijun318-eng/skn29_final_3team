/**
 * VOC 데이터 훅 — Django API 호출 + Incident 매핑
 *
 * fact_voc 테이블 데이터를 MonitoringPage의 Incident 인터페이스로 변환.
 * DB에 없는 필드(status, conf, x, y)는 sentiment/severity 기반 추론 사용.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiFetchVocs, type DjangoVocData } from '../lib/api';
import type { Incident } from '../data/mockData';

// zone → 지도 좌표 (목업 v1.2 SVG 좌표계)
const ZONE_COORDS: Record<string, { x: number; y: number }> = {
  '객실동': { x: 180, y: 150 },
  '다이닝': { x: 340, y: 250 },
  '레저·웰니스': { x: 520, y: 180 },
  'MICE·엔터': { x: 340, y: 410 },
  '인프라': { x: 600, y: 420 },
};

const SENT_MAP: Record<string, string> = {
  NEGATIVE: '부정',
  NEUTRAL: '중립',
  POSITIVE: '긍정',
};

// DB에 status 정보가 없으므로 sentiment/severity 기반 추론
function inferStatus(severity: string): Incident['status'] {
  if (severity === 'danger') return 'prog';
  if (severity === 'warn') return 'check';
  return 'done';
}

function toIncident(v: DjangoVocData, idx: number): Incident {
  const coords = ZONE_COORDS[v.zone] || { x: 400, y: 260 };
  const received = v.received_at ? new Date(v.received_at) : new Date();
  const now = new Date();
  const elapsedMin = Math.max(0, Math.round((now.getTime() - received.getTime()) / 60000));
  // 같은 zone 내 시설 겹침 방지용 미세 오프셋
  const jitter = (idx % 5) * 12;

  return {
    id: v.voc_id,
    fac: v.service_area_name,
    zone: v.zone,
    x: coords.x + jitter,
    y: coords.y + jitter,
    sev: v.severity,
    status: inferStatus(v.severity),
    open: v.severity === 'danger' ? 1 : 0,
    text: v.review_text,
    sent: SENT_MAP[v.sentiment_label] || '중립',
    conf: v.severity === 'danger' ? 0.9 : v.severity === 'warn' ? 0.7 : 0.5,
    cat: v.topic_name,
    ago: elapsedMin < 60 ? `${elapsedMin}분 전` : `${Math.floor(elapsedMin / 60)}시간 전`,
    elapsed: elapsedMin,
    hist: [],
  };
}

export interface VocKpi {
  todayVoc: number;
  unresolved: number;
  avgProcess: number;
  dangerUnhandled: number;
}

interface VOCState {
  incidents: Incident[];
  loading: boolean;
  error: string | null;
  total: number;
  kpi: VocKpi;
}

export function useVocs(pollInterval?: number) {
  const [state, setState] = useState<VOCState>({
    incidents: [],
    loading: true,
    error: null,
    total: 0,
    kpi: { todayVoc: 0, unresolved: 0, avgProcess: 41, dangerUnhandled: 0 },
  });

  const fetchVocs = useCallback(async () => {
    try {
      const res = await apiFetchVocs({ page: 1, limit: 50 });
      if (res.error) {
        setState((s) => ({ ...s, loading: false, error: res.error.message }));
        return;
      }
      const incidents = res.data.map((v, i) => toIncident(v, i));
      const kpi: VocKpi = {
        todayVoc: incidents.length,
        unresolved: incidents.filter((i) => i.status !== 'done').length,
        avgProcess: 41,
        dangerUnhandled: incidents.filter((i) => i.sev === 'danger' && i.status !== 'done').length,
      };
      setState({ incidents, loading: false, error: null, total: res.meta.total ?? incidents.length, kpi });
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
