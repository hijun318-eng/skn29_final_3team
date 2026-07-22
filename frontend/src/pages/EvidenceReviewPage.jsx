import { useState } from "react";
import { Activity, Clock3, Database, MessageSquareHeart, Smartphone, Star, UserRound } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import "../styles/evidence-review.css";

const CHANNELS = [
  {
    id: "satisfaction",
    label: "고객 만족도",
    icon: MessageSquareHeart,
    url: "/feedback?facility=breakfast",
    timing: "부대 시설",
    description: "시설별 만족도, 선택 사유, 자유 의견을 수집합니다.",
    fields: ["시설", "만족도 5단계", "사유 복수 선택", "추가 의견"],
    analysis: "시설별 불편 요인과 시간대별 만족도 변화 분석",
  },
  {
    id: "guest-guide",
    label: "투숙객 안내",
    icon: UserRound,
    url: "/guest-guide?name=Guest%20Name",
    timing: "체크인 후",
    description: "시설 안내 및 AI 추천에 대한 당일 경험 피드백을 수집합니다.",
    fields: ["추천 노출", "당일 만족도", "즉시 의견", "이용 시점"],
    analysis: "투숙 중 불편 조기 감지와 서비스 회복 기회 탐색",
  },
  {
    id: "stay-review",
    label: "숙박 리뷰",
    icon: Star,
    url: "/stay-review?room=1208&from=2026.08.07&to=2026.08.10&hotel=Grand%20SENSE%20PLACE%20Seoul",
    timing: "체크아웃 후",
    description: "숙박 전체 평가와 시설별 별점, 불편 항목을 수집합니다.",
    fields: ["전체 만족도", "시설별 별점", "불편 항목", "서술형 리뷰"],
    analysis: "전체 여정의 핵심 만족·불만 요인과 재방문 저해 요인 분석",
  },
];

export function EvidenceReviewPage() {
  const [activeId, setActiveId] = useState(CHANNELS[0].id);
  const [collapsed, setCollapsed] = useState(false);
  const active = CHANNELS.find((channel) => channel.id === activeId);
  const ActiveIcon = active.icon;

  return <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
    <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
    <div className="workspace"><main className="evidence-review-page">
    <header className="evidence-review-header">
      <div><p>REAL-TIME VOC CHANNEL</p><h1>리뷰 데이터</h1><span>고객 여정의 세 접점에서 수집되는 VOC 화면과 분석 활용 항목을 검토합니다.</span></div>
      <div className="collection-status"><i /><span><b>수집 채널 설계</b><small>Frontend Mockup · API 연동 전</small></span></div>
    </header>

    <section className="voc-flow-summary">
      <div><Activity size={18} /><span><b>3개 고객 접점</b><small>이용 직후 · 투숙 중 · 체크아웃</small></span></div>
      <div><Database size={18} /><span><b>통합 VOC Schema</b><small>채널·시설·시점·평가·의견</small></span></div>
      <div><Clock3 size={18} /><span><b>실시간 분석 지향</b><small>저장 API 연결 후 스트림 반영</small></span></div>
    </section>

    <nav className="voc-channel-tabs" aria-label="VOC 수집 화면">
      {CHANNELS.map((channel) => { const Icon = channel.icon; return <button key={channel.id} type="button" className={activeId === channel.id ? "is-active" : ""} onClick={() => setActiveId(channel.id)}><Icon size={17} /><span>{channel.label}</span><small>{channel.timing}</small></button>; })}
    </nav>

    <section className="channel-workspace">
      <aside className="channel-contract">
        <div className="channel-contract__heading"><span><ActiveIcon size={19} /></span><div><p>COLLECTION CONTRACT</p><h2>{active.label}</h2></div></div>
        <p className="channel-description">{active.description}</p>
        <div className="contract-block"><h3>수집 예정 항목</h3><ul>{active.fields.map((field) => <li key={field}>{field}</li>)}</ul></div>
        <div className="analysis-use"><Activity size={16} /><div><span>분석 활용</span><p>{active.analysis}</p></div></div>
        <p className="mockup-notice">현재 화면은 수집 UX 검증용 목업입니다. 실시간 데이터 적재는 백엔드 저장 API와 통합 VOC schema 연결 후 활성화됩니다.</p>
      </aside>
      <div className="mobile-preview-panel">
        <div className="preview-toolbar"><span><Smartphone size={14} /> MOBILE PREVIEW</span><a href={active.url} target="_blank" rel="noreferrer">새 화면에서 보기</a></div>
        <div className="phone-frame"><div className="phone-speaker" /><iframe key={active.id} src={active.url} title={`${active.label} 모바일 화면`} /></div>
      </div>
    </section>
    </main></div>
  </div>;
}
