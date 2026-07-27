import { ArrowUpRight, ChevronRight } from "lucide-react";

const issues = [
  { rank: "1", name: "체크인 대기 시간 과다", voc: "프론트 데스크 · 134건", severity: "긴급", trend: "+18", level: "critical" },
  { rank: "2", name: "객실 청결 상태 불량", voc: "하우스키핑 · 89건", severity: "높음", trend: "+11", level: "high" },
  { rank: "3", name: "레스토랑 예약 불편", voc: "F&B · 67건", severity: "높음", trend: "+2", level: "high" },
  { rank: "4", name: "엘리베이터 대기 지연", voc: "시설관리 · 45건", severity: "보통", trend: "-5", level: "medium" },
  { rank: "5", name: "Wi-Fi 연결 불안정", voc: "IT · 38건", severity: "보통", trend: "+8", level: "medium" },
];

export function PriorityIssues() {
  return (
    <article className="card issues-card">
      <div className="section-heading"><div><p>AI 분석 기반 · 즉시 조치 권고</p><h2>개선 우선순위</h2></div></div>
      <div className="issue-list">
        {issues.map((issue) => (
          <button className="issue-row" key={issue.rank}>
            <span className="issue-rank">{issue.rank}</span>
            <span className="issue-name"><b>{issue.name}</b><small>{issue.voc}</small></span>
            <span className={`severity severity--${issue.level}`}>{issue.severity}</span>
            <span className="issue-trend"><ArrowUpRight size={14} />{issue.trend}</span>
            <ChevronRight size={17} />
          </button>
        ))}
      </div>
      <button className="primary-button">전체 이슈 분석 보기 <ChevronRight size={16} /></button>
    </article>
  );
}
