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

export function MetaStrip() {
  return (
    <div className="meta-strip">
      <ShieldCheck size={13} />
      {SYNTHETIC_META.label}
      <span>seed {SYNTHETIC_META.seed}</span>
      <span>schema {SYNTHETIC_META.schemaVersion}</span>
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
