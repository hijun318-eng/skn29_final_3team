import { useState } from "react";
import { Activity, Clock3, Database, Link2, MessageSquareHeart, ShieldCheck, Smartphone, Star, UserRound } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import { HeaderUtilities } from "../components/layout/Header";
import "../styles/evidence-review.css";

const previewCheckoutAt = new Date(Date.now() - (60 * 60 * 1000)).toISOString();
const previewStayEndAt = new Date(Date.now() + (72 * 60 * 60 * 1000)).toISOString();

const CHANNELS = [
  {
    id: "satisfaction",
    label: "고객 만족도",
    icon: MessageSquareHeart,
    url: "/feedback?facility=breakfast",
    timing: "부대 시설",
    description: "시설별 만족도, 선택 사유, 자유 의견을 수집합니다.",
    fields: ["시설", "만족도 5단계", "사유 복수 선택", "추가 의견", "사진 최대 3장"],
    analysis: "시설별 불편 요인과 시간대별 만족도 변화 분석",
  },
  {
    id: "guest-guide",
    label: "투숙객 안내",
    icon: UserRound,
    url: `/guest-guide?name=Guest%20Name&room=1208&checkoutAt=${encodeURIComponent(previewStayEndAt)}`,
    timing: "체크인 후",
    description: "체크인 객실과 시설 안내를 제공하고 체크아웃 전까지 당일 경험 피드백을 수집합니다.",
    fields: ["객실 번호", "추천 노출", "당일 만족도", "사진 최대 3장", "체크아웃 만료 시각"],
    analysis: "투숙 중 불편 조기 감지와 서비스 회복 기회 탐색",
  },
  {
    id: "stay-review",
    label: "숙박 리뷰",
    icon: Star,
    url: `/stay-review?room=1208&from=2026.08.07&to=2026.08.10&hotel=Grand%20SENSE%20PLACE%20Seoul&checkoutAt=${encodeURIComponent(previewCheckoutAt)}`,
    timing: "체크아웃 후",
    description: "체크아웃 후 24시간 동안 숙박 전체 평가와 시설별 별점, 불편 항목을 수집합니다.",
    fields: ["전체 만족도", "시설별 별점", "불편 항목", "사진 최대 3장", "24시간 만료 시각"],
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
    <div className="workspace">
    <header className="evidence-review-header admin-page-header">
      <div><p>HOTEL DIRECT VOC DATA</p><h1>내부 리뷰 데이터</h1><span>호텔이 고객 여정의 세 접점에서 직접 수집한 VOC 데이터를 통합해 운영 분석에 활용합니다.</span></div>
      <HeaderUtilities />
    </header>
    <main className="evidence-review-page">

    <section className="voc-flow-summary">
      <div><Activity size={18} /><span><b>3개 고객 접점</b><small>이용 직후 · 투숙 중 · 체크아웃</small></span></div>
      <div><Database size={18} /><span><b>통합 VOC Schema</b><small>채널·시설·시점·평가·의견</small></span></div>
      <div><Clock3 size={18} /><span><b>실시간 분석 지향</b><small>저장 API 연결 후 스트림 반영</small></span></div>
    </section>

    <section className="personal-link-strategy">
      <div className="link-strategy-heading">
        <span><Link2 size={19} /></span>
        <div>
          <p>PERSONAL LINK DELIVERY</p>
          <h2>개인 링크 발송 전략</h2>
          <small>예약 1건 = 고유 토큰 1개 · 알림톡/문자에 시설 가이드와 함께 동봉</small>
        </div>
      </div>

      <div className="link-strategy-grid">
        <article className="alimtalk-preview">
          <div className="alimtalk-preview__label">카카오 알림톡 미리보기 <small>체크인 시 발송</small></div>
          <div className="alimtalk-message">
            <strong>SENSE PLACE HOTEL</strong>
            <div>
              <p><b>윤대성님</b>, 체크인을 환영합니다. 🏨</p>
              <p>투숙 기간 동안 아래 링크에서 이용하세요.</p>
              <ul>
                <li>호텔 시설 가이드 · 맞춤 추천 코스</li>
                <li>불편사항 실시간 접수 (로그인 불필요)</li>
              </ul>
              <span className="alimtalk-link"><Link2 size={14} /> senseplace.io/voc/tk_8f3aXq...</span>
            </div>
          </div>
          <p className="alimtalk-fallback">알림톡 실패 시 LMS 문자 폴백 · 객실 QR 카드 병행</p>
        </article>

        <div className="link-strategy-details">
          <article className="link-lifecycle">
            <h3>발송 시점 · 링크 수명주기</h3>
            <dl>
              <div><dt>예약 확정</dt><dd>문자(LMS) — 예약 요약 + 링크 발급 안내</dd></div>
              <div><dt>체크인 시</dt><dd>알림톡 — 가이드·추천 코스 (기본 탭: 투숙 안내)</dd></div>
              <div><dt>투숙 중</dt><dd>같은 링크로 불편 즉시 접수 (탭: 불편 남기기)</dd></div>
              <div><dt>체크아웃 시</dt><dd>알림톡 — “이용은 어떠셨나요?” 마지막 피드백 유도</dd></div>
              <div className="is-expiry"><dt>체크아웃+24h</dt><dd>토큰 자동 만료(410) — 조회·제출 차단, 프런트 안내</dd></div>
            </dl>
          </article>
          <article className="link-policy">
            <h3><ShieldCheck size={16} /> 링크 정책 <small>명세 1.2</small></h3>
            <ul>
              <li>토큰 43자 무작위(secrets) — URL 추측 불가</li>
              <li>로그인 불필요 · 실패 응답에 예약정보 미노출</li>
              <li>재제출 60초 간격 · IP 분당 10회 rate limit</li>
              <li>같은 링크 재방문 시 접수 이력 기반 맞춤 추천 갱신</li>
            </ul>
          </article>
        </div>
      </div>
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
        <p className="mockup-notice">모바일 화면에서 제출한 VOC는 현재 브라우저의 실시간 운영 이벤트로 저장되어 모니터링 지도와 알림에 즉시 반영됩니다. 실제 운영 환경에서는 동일 contract를 백엔드 저장 API와 연결해야 합니다.</p>
      </aside>
      <div className="mobile-preview-panel">
        <div className="preview-toolbar"><span><Smartphone size={14} /> MOBILE PREVIEW</span><a href={active.url} target="_blank" rel="noreferrer">새 화면에서 보기</a></div>
        <div className="phone-frame"><div className="phone-speaker" /><iframe key={active.id} src={active.url} title={`${active.label} 모바일 화면`} /></div>
      </div>
    </section>
    </main></div>
  </div>;
}
