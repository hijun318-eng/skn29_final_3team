import { useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  ChevronRight,
  CloudCog,
  KeyRound,
  MessageSquareText,
  Search,
  Sparkles,
} from "lucide-react";
import { MetaStrip, SectionTitle, StatusBadge } from "../components/common/EnterpriseUi";
import { customers } from "../data/enterpriseDemoData";

const CUSTOMER_JOURNEY = [
  [CalendarDays, "예약", "06.14", "River View"],
  [KeyRound, "체크인", "07.16", "15:04"],
  [CloudCog, "POS 구매", "07.17", "₩186,000"],
  [MessageSquareText, "VOC", "07.18", "조식 대기"],
];

const PREFERENCES = [
  ["객실", 88],
  ["조식", 72],
  ["라운지", 54],
  ["스파", 31],
];

export function Customer360Page() {
  const [selectedId, setSelectedId] = useState(customers[0].id);
  const customer = customers.find((item) => item.id === selectedId) || customers[0];

  const metrics = [
    ["총 투숙", `${customer.stays}회`],
    ["누적 객실 매출", customer.revenue],
    ["최근 감성", customer.sentiment],
    ["선호 객실", customer.room],
  ];

  return (
    <div className="page-content">
      <MetaStrip />
      <div className="customer-layout">
        <aside className="customer-list card">
          <div className="search-box">
            <Search size={15} />
            <input placeholder="마스킹 ID 또는 고객 검색" />
          </div>
          {customers.map((item) => (
            <button
              className={selectedId === item.id ? "active" : ""}
              onClick={() => setSelectedId(item.id)}
              key={item.id}
            >
              <span>{item.name.slice(0, 1)}</span>
              <div>
                <b>{item.name}<em>{item.tier}</em></b>
                <small>{item.id} · 최근 {item.last}</small>
              </div>
              <ChevronRight size={15} />
            </button>
          ))}
        </aside>

        <main className="customer-main">
          <section className="card customer-profile">
            <div className="customer-identity">
              <span>{customer.name.slice(0, 1)}</span>
              <div>
                <p>CUSTOMER GOLDEN PROFILE</p>
                <h2>{customer.name} <em>{customer.tier}</em></h2>
                <small>{customer.id} · 개인정보 마스킹 적용</small>
              </div>
            </div>
            <div className="revisit-score">
              <small>재방문 예측</small>
              <strong>{customer.revisit}%</strong>
              <StatusBadge status="healthy" />
            </div>
          </section>

          <section className="customer-kpis">
            {metrics.map(([label, value]) => (
              <article className="card" key={label}><small>{label}</small><strong>{value}</strong></article>
            ))}
          </section>

          <section className="card journey-card">
            <SectionTitle
              eyebrow="CUSTOMER JOURNEY"
              title="통합 행동 타임라인"
              description="CRM · PMS · POS · VOC 연합 조회"
            />
            <div className="journey-line">
              {CUSTOMER_JOURNEY.map(([Icon, label, date, detail]) => (
                <article key={label}>
                  <span><Icon size={17} /></span>
                  <small>{date}</small>
                  <b>{label}</b>
                  <p>{detail}</p>
                </article>
              ))}
            </div>
          </section>

          <div className="customer-detail-grid">
            <section className="card">
              <SectionTitle eyebrow="BEHAVIOR" title="구매·선호 패턴" />
              <div className="preference-bars">
                {PREFERENCES.map(([label, value]) => (
                  <div key={label}>
                    <span>{label}<b>{value}%</b></span>
                    <i><em style={{ width: `${value}%` }} /></i>
                  </div>
                ))}
              </div>
            </section>
            <section className="card customer-chat">
              <SectionTitle eyebrow="CUSTOMER COPILOT" title="고객 전용 챗" />
              <div className="mini-chat">
                <p>이 고객의 재방문 가능성을 높일 전략은?</p>
                <div>
                  <Sparkles size={15} />
                  <span>
                    선호 객실의 강변 전망을 보장하고 조식 혼잡이 낮은 시간대를 사전 안내하는 전략을 권장합니다.
                    <small>예측 · 관리자 검토 필요</small>
                  </span>
                </div>
              </div>
              <button>후속 질문하기 <ArrowRight size={14} /></button>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
