import { useEffect, useState } from "react";
import { Activity, Clock3, Radio, ShieldCheck } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import { OperationMapSection } from "../components/map/OperationMapSection";
import { HeaderUtilities } from "../components/layout/Header";
import { facilities } from "../components/map/operationMapData";
import { publishOperationAlerts } from "../services/operationAlerts";
import { apiGet } from "../services/apiClient";
import { getLiveVocEvents } from "../services/liveVoc";

export function MonitoringPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [vocCases, setVocCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [vocSource, setVocSource] = useState("db");

  useEffect(() => {
    const detectedAlerts = facilities.filter((facility) => facility.status !== "normal").map((facility) => ({
      id: `facility-${facility.id}-${facility.status}`,
      facilityId: facility.id,
      severity: facility.status,
      title: `${facility.name} ${facility.statusLabel} 상태 감지`,
      message: `${facility.metric} · 운영 맵에서 현장 상태를 확인하세요.`,
    }));
    publishOperationAlerts(detectedAlerts);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet("/vocs/?limit=50")
      .then((res) => {
        if (cancelled) return;
        if (res && Array.isArray(res.data) && !res.error) {
          const mapped = res.data.map((v) => ({
            id: v.voc_id ?? v.id,
            facilityId: v.service_area_id ?? v.facilityId,
            facilityName: v.service_area_name ?? v.facilityName ?? v.service_area_id,
            zone: v.zone ?? "",
            severity: v.severity ?? "warn",
            rating:
              v.severity === "danger" ? 2 : v.severity === "warn" ? 3 : v.rating ?? 5,
            comment: v.review_text ?? v.comment ?? "",
            category: v.topic_name ?? v.topic_code ?? v.category ?? "",
            sentiment: v.sentiment_label ?? "NEUTRAL",
            createdAt: v.received_at ?? v.createdAt ?? new Date().toISOString(),
            source: "db",
          }));
          setVocCases(mapped);
          setVocSource("db");
          setError(null);
          return;
        }
        // API 응답이 비정상적이면 localStorage fallback
        const fallback = getLiveVocEvents();
        setVocCases(fallback);
        setVocSource("local");
        if (!fallback.length) {
          setError(res?.error?.message || "VOC 데이터를 불러오지 못했습니다.");
        }
      })
      .catch((e) => {
        if (cancelled) return;
        // API 호출 실패 시 localStorage fallback
        const fallback = getLiveVocEvents();
        setVocCases(fallback);
        setVocSource("local");
        setError(fallback.length ? null : e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace monitoring-workspace">
        <header className="monitoring-header admin-page-header">
          <div>
            <p>LIVE OPERATION INTELLIGENCE</p>
            <h1>호텔 실시간 운영 모니터링</h1>
            <span>시설 혼잡도와 운영 상태를 실시간으로 확인하고 대응 시나리오를 검토합니다.</span>
          </div>
          <div className="monitoring-header-actions">
            <HeaderUtilities />
          </div>
        </header>

        <main className="monitoring-main">
          <section className="monitoring-summary">
            <article><span><Radio size={18} /></span><div><small>모니터링 시설</small><strong>7개</strong></div></article>
            <article><span><Activity size={18} /></span><div><small>주의 필요</small><strong>2개</strong></div></article>
            <article><span><Clock3 size={18} /></span><div><small>평균 대기시간</small><strong>8분</strong></div></article>
            <article><span><ShieldCheck size={18} /></span><div><small>운영 상태</small><strong>안정</strong></div></article>
          </section>
          <OperationMapSection />

          <section className="monitoring-voc">
            <header className="monitoring-voc-header">
              <h2>최근 VOC</h2>
              <small>
                {loading
                  ? "불러오는 중…"
                  : vocSource === "db"
                    ? `DB 연동 · ${vocCases.length}건`
                    : `로컬 백업 · ${vocCases.length}건`}
              </small>
            </header>
            {error ? (
              <p className="monitoring-voc-error" role="alert">
                {error}
              </p>
            ) : loading ? (
              <p className="monitoring-voc-loading">VOC 데이터를 불러오는 중…</p>
            ) : vocCases.length === 0 ? (
              <p className="monitoring-voc-empty">표시할 VOC 데이터가 없습니다.</p>
            ) : (
              <ul className="monitoring-voc-list">
                {vocCases.slice(0, 10).map((voc) => (
                  <li key={voc.id} className={`monitoring-voc-item monitoring-voc-item--${voc.severity}`}>
                    <div className="monitoring-voc-item-head">
                      <strong>{voc.facilityName}</strong>
                      <span className="monitoring-voc-rating">평점 {voc.rating}</span>
                    </div>
                    {voc.category ? <small>{voc.category}</small> : null}
                    {voc.comment ? <p>{voc.comment}</p> : null}
                    <footer>
                      <span>{voc.sentiment}</span>
                      <time dateTime={voc.createdAt}>{new Date(voc.createdAt).toLocaleString()}</time>
                    </footer>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
