import { useState } from "react";
import { ExternalLink, LayoutDashboard, List, Sparkles, Star } from "lucide-react";
import { Header } from "../components/layout/Header";
import { Sidebar } from "../components/layout/Sidebar";

const REVIEW_PLATFORMS = [
  { id: "yeogi", name: "여기어때", mark: "여", count: 428, rating: 4.42, negative: 18.7, color: "#de3d55", reviews: ["체크인이 빠르고 객실 전망이 좋았습니다.", "주말 조식 대기가 길어 개선이 필요합니다."] },
  { id: "google", name: "구글", mark: "G", count: 834, rating: 4.38, negative: 19.4, color: "#4285f4", reviews: ["직원 응대가 친절하고 위치가 편리했습니다.", "레스토랑 예약 절차가 조금 복잡했습니다."] },
  { id: "tripadvisor", name: "트립어드바이저", mark: "TA", count: 587, rating: 4.47, negative: 16.8, color: "#34a853", reviews: ["서울 여행 중 머물기 좋은 호텔이었습니다.", "조식 피크 시간에는 좌석 안내가 더 필요합니다."] },
  { id: "trip", name: "트립닷컴", mark: "T", count: 372, rating: 4.51, negative: 15.9, color: "#287dfa", reviews: ["강변 전망과 침구 컨디션이 만족스러웠습니다.", "엘리베이터 대기시간이 다소 길었습니다."] },
  { id: "agoda", name: "아고다", mark: "A", count: 691, rating: 4.31, negative: 23.1, color: "#5a2ca0", reviews: ["가격 대비 객실 크기와 위치가 좋았습니다.", "체크인 피크 시간 로비가 매우 혼잡했습니다."] },
  { id: "myrealtrip", name: "마이리얼트립", mark: "M", count: 264, rating: 4.58, negative: 13.6, color: "#2b96ed", reviews: ["도심 호캉스로 추천할 만한 호텔입니다.", "부대시설 운영시간 안내가 더 명확하면 좋겠습니다."] },
];

export function DashboardPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [selectedPlatformId, setSelectedPlatformId] = useState("yeogi");
  const [viewMode, setViewMode] = useState("list");
  const [period, setPeriod] = useState("주");
  const selectedPlatform = REVIEW_PLATFORMS.find((platform) => platform.id === selectedPlatformId);

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <div className="workspace">
        <Header description="OTA와 여행 플랫폼의 고객 리뷰를 채널별로 비교하고 운영 이슈를 확인합니다." />
        <main className="dashboard">
          <section className="external-review-card card">
            <header><div><p>CHANNEL REVIEW MONITOR</p><h2>외부 리뷰 통합 관리</h2><span>플랫폼별 리뷰와 감성 현황을 같은 기준으로 확인합니다.</span></div><small>외부 API 연동 예정 · synthetic schema v1.0</small></header>
            <div className="review-management-toolbar">
              <div className="review-view-switch"><button type="button" className={viewMode === "list" ? "is-active" : ""} onClick={() => setViewMode("list")}><List size={14} />목록</button><button type="button" className={viewMode === "dashboard" ? "is-active" : ""} onClick={() => setViewMode("dashboard")}><LayoutDashboard size={14} />대시보드</button></div>
              <div className="review-period-switch">{["주", "월", "분기"].map((item) => <button type="button" className={period === item ? "is-active" : ""} onClick={() => setPeriod(item)} key={item}>{item}간</button>)}</div>
            </div>
            <div className="review-platform-tabs" role="tablist" aria-label="외부 리뷰 플랫폼">{REVIEW_PLATFORMS.map((platform) => <button type="button" role="tab" aria-selected={selectedPlatformId === platform.id} className={selectedPlatformId === platform.id ? "is-active" : ""} onClick={() => setSelectedPlatformId(platform.id)} key={platform.id}><i style={{ background: platform.color }}>{platform.mark}</i><span><b>{platform.name}</b><small>리뷰 {platform.count.toLocaleString()}건</small></span><strong><Star size={12} fill="currentColor" />{platform.rating}</strong></button>)}</div>
            <div className="review-ai-insight"><Sparkles size={17} /><div><b>LLM 자동 제안</b><p><strong>{selectedPlatform.name}</strong> 리뷰에서 조식 대기와 안내 관련 의견이 함께 증가했습니다. 운영 시간대와 현장 대응 기록을 교차 확인하세요.</p></div></div>
            {viewMode === "list" ? <div className="review-list-workspace">
              <aside className="review-sentiment-card"><h3>감성 분포</h3><div className="sentiment-donut" style={{ "--negative": `${selectedPlatform.negative * 3.6}deg` }}><span><b>{selectedPlatform.count}</b><small>총 리뷰</small></span></div><ul><li><i className="positive" />긍정 <b>{Math.round(100 - selectedPlatform.negative - 18)}%</b></li><li><i className="neutral" />중립 <b>18%</b></li><li><i className="negative" />부정 <b>{selectedPlatform.negative}%</b></li></ul><div className="review-mini-kpis"><span><small>평균 평점</small><b>{selectedPlatform.rating}★</b></span><span><small>{period}간 위험 알림</small><b>{Math.max(1, Math.round(selectedPlatform.negative / 8))}건</b></span></div></aside>
              <div className="review-list-column"><div className="review-list-heading"><h3>리뷰 목록 <span>{selectedPlatform.count.toLocaleString()}건</span></h3><small>다음 수집 15:00 · 1시간 주기</small></div><div className="platform-review-list">{selectedPlatform.reviews.map((review, index) => <article key={`${selectedPlatform.id}-${index}`}><div><i style={{ color: selectedPlatform.color }}>● {selectedPlatform.name}</i><Star size={13} fill="currentColor" /><b>{index === 0 ? "긍정" : "개선 의견"}</b><small>{index === 0 ? "오늘 09:24" : "어제 21:16"}</small></div><p>{review}</p><button type="button">원문 확인 <ExternalLink size={12} /></button></article>)}</div></div>
            </div> : <div className="review-dashboard-workspace"><div className="review-platform-overview">{REVIEW_PLATFORMS.map((platform) => <article key={platform.id}><header><i style={{ color: platform.color }}>●</i><b>{platform.name}</b><em>{platform.negative >= 20 ? "▲ 주의" : "▼ 안정"}</em></header><dl><div><dt>리뷰</dt><dd>{platform.count}</dd></div><div><dt>평점</dt><dd>{platform.rating}★</dd></div><div><dt>부정률</dt><dd>{platform.negative}%</dd></div></dl><span><i style={{ width: `${100 - platform.negative}%` }} /></span></article>)}</div><section className="review-category-card"><h3>부정 리뷰 카테고리 TOP 5</h3>{[["대기·혼잡", 92], ["예약·안내", 74], ["가격·결제", 58], ["청결·위생", 44], ["직원 서비스", 36]].map(([label, value]) => <div key={label}><span>{label}</span><i><b style={{ width: `${value}%` }} /></i><strong>{value}건</strong></div>)}</section></div>}
          </section>

        </main>
      </div>
    </div>
  );
}
