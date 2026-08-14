import { ShieldCheck } from "lucide-react";

const STATUS_LABEL = {
  connected: "연결됨",
  delayed: "지연",
  error: "오류",
  healthy: "정상",
  degraded: "주의",
  CONFIG_VALIDATED: "검증 완료",
};

export function StatusBadge({ status }) {
  return <span className={`status status--${status}`}><i />{STATUS_LABEL[status] || status}</span>;
}

export function MetaStrip({ meta, verified = false }) {
  if (!meta) return null;
  return (
    <div className="meta-strip">
      <ShieldCheck size={13} />
      <span>{verified ? "검증된 분석" : "분석 요청 기준"}</span>
      {meta.asOf && <span>데이터 기준일 {meta.asOf} · 서울 시간</span>}
    </div>
  );
}

export function SectionTitle({ eyebrow, title, description, action }) {
  return (
    <header className="section-title">
      <div><p>{eyebrow}</p><h2>{title}</h2>{description && <span>{description}</span>}</div>
      {action}
    </header>
  );
}
