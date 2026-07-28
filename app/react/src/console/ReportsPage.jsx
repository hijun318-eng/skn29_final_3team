import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, Clock, Download, RefreshCw, Send } from "lucide-react";
import { REPORTS, REPORT_TABS, SYNTHETIC_META } from "./consoleData";
import { Card, Kpi, SyntheticBadge, Tag, axisProps, tooltipProps } from "./ui";

const SEVERITY = { "긴급": "critical", "높음": "warn", "보통": "slate" };
const STATUS = { "초안": "warn", "검토 중": "slate", "확정": "ok" };

export function ReportsPage() {
  const [tab, setTab] = useState("weekly");
  const [notice, setNotice] = useState("");
  const meta = REPORT_TABS.find((t) => t.key === tab);
  const r = REPORTS[tab];

  function demoAction(msg) {
    setNotice(msg);
    setTimeout(() => setNotice(""), 3200);
  }

  return (
    <div className="wh-page" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="wh-tabs">
        {REPORT_TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "is-active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="wh-meta-strip">
        <div><span>대상 기간</span><b className="wh-num">{meta.period}</b></div>
        <div><span>생성 주기</span><b>{meta.cadence}</b></div>
        <div><span>작성</span><b>{r.author}</b></div>
        <div><span>검토자</span><b>{r.reviewer}</b></div>
        <div><span>상태</span><b><Tag tone={STATUS[r.status]}>{r.status}</Tag></b></div>
        <div style={{ marginLeft: "auto" }}><SyntheticBadge /></div>
      </div>

      <Card
        title="핵심 결론"
        note={`${SYNTHETIC_META.dataset} · 자동 생성 후 검토자 확정 필요`}
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <button className="wh-btn" onClick={() => demoAction("데모 환경입니다. 재생성은 report.compose MCP tool 연동 후 동작합니다.")}>
              <RefreshCw size={13} /> 재생성
            </button>
            <button className="wh-btn" onClick={() => demoAction("데모 환경입니다. PDF 내려받기는 실데이터 연동 후 제공됩니다.")}>
              <Download size={13} /> PDF
            </button>
            <button className="wh-btn wh-btn--primary" onClick={() => demoAction("검토 요청이 데모로 기록되었습니다. 실제 발송은 승인 후 수행합니다.")}>
              <Send size={13} /> 검토 요청
            </button>
          </div>
        }
      >
        <p style={{ fontSize: 15, lineHeight: 1.75 }}>{r.headline}</p>
        {notice && (
          <p style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 7, color: "#996b56", fontSize: 11.5 }}>
            <CheckCircle2 size={13} /> {notice}
          </p>
        )}
      </Card>

      <div className="wh-grid wh-grid--4">
        {r.kpis.map((k) => <Kpi key={k.label} {...k} />)}
      </div>

      <div className="wh-grid" style={{ gridTemplateColumns: "minmax(0, 1.55fr) minmax(0, 1fr)" }}>
        <Card title="VOC 추이" note="전체 건수(막대) · 부정 건수(선)">
          <div style={{ height: 262 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={r.series} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#f0eeec" vertical={false} />
                <XAxis dataKey="t" {...axisProps} />
                <YAxis {...axisProps} />
                <Tooltip {...tooltipProps} />
                <Bar dataKey="voc" name="전체 VOC" fill="#996b56" barSize={22} />
                <Line dataKey="neg" name="부정 VOC" stroke="#a83a2b" strokeWidth={1.6} dot={{ r: 2.5 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="집중 이슈" note="건수 · 심각도 · 전기 대비 증감" bodyClass="wh-scroll">
          <table className="wh-table">
            <thead>
              <tr><th>이슈</th><th>부서</th><th className="wh-right">건수</th><th>심각도</th><th className="wh-right">증감</th></tr>
            </thead>
            <tbody>
              {r.issues.map(([title, dept, count, sev, delta]) => (
                <tr key={title}>
                  <td><b>{title}</b></td>
                  <td>{dept}</td>
                  <td className="wh-right wh-num">{count}</td>
                  <td><Tag tone={SEVERITY[sev]}>{sev}</Tag></td>
                  <td className="wh-right wh-num" style={{ color: delta.startsWith("+") ? "#a83a2b" : "#3e7a5e" }}>{delta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="wh-grid" style={{ gridTemplateColumns: `repeat(${r.sections.length}, minmax(0, 1fr))` }}>
        {r.sections.map((s) => (
          <Card key={s.title} title={s.title}>
            <p style={{ color: "#666", lineHeight: 1.8 }}>{s.body}</p>
          </Card>
        ))}
      </div>

      <p style={{ display: "flex", alignItems: "center", gap: 7, color: "#999", fontSize: 11 }}>
        <Clock size={12} /> 마지막 생성 {SYNTHETIC_META.generatedAt} · schema {SYNTHETIC_META.schemaVersion} · seed {SYNTHETIC_META.seed} · {SYNTHETIC_META.note}
      </p>
    </div>
  );
}
