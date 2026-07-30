import { ShieldCheck } from "lucide-react";
import { SYNTHETIC_META } from "../../data/enterpriseDemoData";

const STATUS_LABEL = {
  connected: "연결됨",
  delayed: "지연",
  error: "오류",
  healthy: "정상",
  degraded: "주의",
};

export function StatusBadge({ status }) {
  return (
    <span className={`status status--${status}`}>
      <i />
      {STATUS_LABEL[status] || status}
    </span>
  );
}

export function MetaStrip({ meta = SYNTHETIC_META }) {
  return (
    <div className="meta-strip">
      <ShieldCheck size={13} />
      {meta.synthetic ? "Synthetic data" : SYNTHETIC_META.label}
      <span>seed {meta.seed}</span>
      <span>schema {meta.schemaVersion}</span>
      {meta.asOf && <span>as_of {meta.asOf} · {meta.timezone}</span>}
    </div>
  );
}

export function SectionTitle({ eyebrow, title, description, action }) {
  return (
    <header className="section-title">
      <div>
        <p>{eyebrow}</p>
        <h2>{title}</h2>
        {description && <span>{description}</span>}
      </div>
      {action}
    </header>
  );
}
