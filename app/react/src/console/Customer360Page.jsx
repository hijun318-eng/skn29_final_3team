import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowUp, Search, Sparkles } from "lucide-react";
import { CUSTOMERS, CUSTOMER_CHAT_FALLBACK } from "./consoleData";
import { Card, SyntheticBadge, Tag, axisProps, tooltipProps } from "./ui";

const RISK = { high: "critical", mid: "warn", low: "ok" };
const TONE = { neg: "critical", pos: "ok", neutral: "slate" };

export function Customer360Page() {
  const [id, setId] = useState(CUSTOMERS[0].id);
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState("");
  const [chats, setChats] = useState({}); // customerId -> messages

  const customer = CUSTOMERS.find((c) => c.id === id);
  const list = useMemo(() => {
    const k = q.trim().toLowerCase();
    return k ? CUSTOMERS.filter((c) => `${c.name}${c.id}${c.tier}${c.segment}`.toLowerCase().includes(k)) : CUSTOMERS;
  }, [q]);

  const messages = chats[id] ?? [];

  function ask(text) {
    const question = text.trim();
    if (!question) return;
    const hit = customer.chat.find((c) => c.match.some((m) => question.includes(m)));
    setChats((prev) => ({
      ...prev,
      [id]: [...(prev[id] ?? []), { role: "user", text: question }, { role: "agent", text: hit?.answer ?? CUSTOMER_CHAT_FALLBACK }],
    }));
    setDraft("");
  }

  return (
    <div className="wh-c360">
      <aside className="wh-c360-list">
        <div className="wh-search">
          <Search size={14} />
          <input value={q} placeholder="고객명 · ID · 세그먼트" onChange={(e) => setQ(e.target.value)} />
        </div>
        {list.map((c) => (
          <button key={c.id} className={`wh-cust ${c.id === id ? "is-active" : ""}`} onClick={() => setId(c.id)}>
            <div className="wh-cust-top">
              <b>{c.name}</b>
              <Tag tone={RISK[c.riskLevel]}>{c.risk}</Tag>
            </div>
            <small>{c.tier} · {c.segment}</small>
            <small>{c.property} · 최근 {c.lastStay}</small>
          </button>
        ))}
        {list.length === 0 && <p className="wh-empty">일치하는 고객이 없습니다.</p>}
      </aside>

      <div className="wh-c360-body">
        <div className="wh-profile">
          <div className="wh-profile-avatar">{customer.initials}</div>
          <div>
            <h2>
              {customer.name}
              <Tag tone="copper">{customer.tier}</Tag>
              <Tag tone={RISK[customer.riskLevel]}>{customer.risk}</Tag>
            </h2>
            <div className="wh-profile-meta">
              <div><span>고객 ID</span> <b className="wh-num">{customer.id}</b></div>
              <div><span>주 이용</span> {customer.property}</div>
              <div><span>세그먼트</span> {customer.segment}</div>
              <div><span>LTV</span> <b className="wh-num">{customer.ltv}</b></div>
            </div>
          </div>
          <SyntheticBadge compact />
        </div>

        <div className="wh-facts">
          {[
            ["총 투숙", `${customer.stays}회`],
            ["총 숙박일", `${customer.nights}박`],
            ["1박 평균 결제", customer.avgSpend],
            ["NPS", `${customer.nps} / 10`],
            ["감성 지수", customer.sentiment > 0 ? `+${customer.sentiment.toFixed(2)}` : customer.sentiment.toFixed(2)],
          ].map(([label, value]) => (
            <div key={label} className="wh-fact">
              <span>{label}</span>
              <b className="wh-num">{value}</b>
            </div>
          ))}
        </div>

        <div className="wh-grid" style={{ gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)" }}>
          <Card title="만족도 · 결제액 추이" note="월별 만족도(5점) 및 1박 평균 결제액(백만원)">
            <div style={{ height: 216 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={customer.trend} margin={{ top: 8, right: 10, left: -22, bottom: 0 }}>
                  <CartesianGrid stroke="#f0eeec" vertical={false} />
                  <XAxis dataKey="t" {...axisProps} />
                  <YAxis yAxisId="l" domain={[2.5, 5]} {...axisProps} />
                  <YAxis yAxisId="r" orientation="right" domain={[0, 3]} {...axisProps} />
                  <Tooltip {...tooltipProps} />
                  <Line yAxisId="l" dataKey="sat" name="만족도" stroke="#996b56" strokeWidth={1.8} dot={{ r: 2.5 }} />
                  <Line yAxisId="r" dataKey="spend" name="결제액" stroke="#474e61" strokeWidth={1.4} strokeDasharray="4 3" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="접점 채널 분포" note="VOC 유입 채널별 건수">
            <div style={{ height: 216 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={customer.channels} layout="vertical" margin={{ top: 8, right: 14, left: 18, bottom: 0 }}>
                  <CartesianGrid stroke="#f0eeec" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} {...axisProps} />
                  <YAxis type="category" dataKey="k" width={72} {...axisProps} />
                  <Tooltip {...tooltipProps} />
                  <Bar dataKey="v" name="건수" fill="#52453e" barSize={14} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        <div className="wh-grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
          <Card title="고객 여정 타임라인" note="숙박 · VOC · 보상 이력 통합">
            <div className="wh-timeline">
              {customer.timeline.map((t, i) => (
                <div key={i} className={`wh-tl wh-tl--${t.tone}`}>
                  <div className="wh-tl-head">
                    <b className="wh-num">{t.d}</b>
                    <Tag tone={TONE[t.tone]}>{t.type}</Tag>
                    <span>{t.src}</span>
                  </div>
                  <p>{t.text}</p>
                </div>
              ))}
            </div>
          </Card>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Card title="확인된 선호" note="예약 시 자동 반영 대상">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {customer.tags.map((t) => <Tag key={t} tone="copper">{t}</Tag>)}
              </div>
            </Card>
            <Card title="다음 조치 추천" note="근거 기반 우선순위">
              {customer.nextBest.map((n) => (
                <div key={n.title} className="wh-nba">
                  <b>{n.title}</b>
                  <p>{n.why}</p>
                  <small>담당 · {n.owner}</small>
                </div>
              ))}
            </Card>
          </div>
        </div>

        <Card title={`${customer.name} 고객 전용 대화`} note="이 고객의 데이터 범위에서만 답변합니다" bodyClass="">
          <div className="wh-mini-chat">
            <div className="wh-mini-stream">
              {messages.length === 0 && (
                <p className="wh-empty" style={{ padding: 0 }}>
                  예: “이탈 위험이 왜 높아?”, “이 고객의 선호는?”, “다음에 무엇을 제안해야 해?”
                </p>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`wh-mini-msg ${m.role === "user" ? "wh-mini-msg--user" : ""}`}>
                  {m.text}
                </div>
              ))}
            </div>
            <div className="wh-mini-form">
              <input
                value={draft}
                placeholder="이 고객에 대해 질문하세요"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask(draft)}
              />
              <button className="wh-btn wh-btn--primary" disabled={!draft.trim()} onClick={() => ask(draft)}>
                <ArrowUp size={14} /> 질문
              </button>
            </div>
          </div>
        </Card>

        <p style={{ display: "flex", alignItems: "center", gap: 7, color: "#999", fontSize: 11 }}>
          <Sparkles size={12} /> 고객 식별 정보는 합성 값이며 실제 고객 데이터가 아닙니다.
        </p>
      </div>
    </div>
  );
}
