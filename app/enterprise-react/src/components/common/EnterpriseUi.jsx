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

export function MetaStrip({ meta }) {
  if (!meta) return null;
  return (
    <div className="meta-strip">
      <ShieldCheck size={13} />
      <span>contract {meta.contractVersion}</span>
      {meta.asOf && <span>as_of {meta.asOf} · {meta.timezone}</span>}
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
