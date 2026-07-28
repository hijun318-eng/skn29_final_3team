import { ArrowDownRight, ArrowUpRight, FlaskConical } from "lucide-react";
import { SYNTHETIC_META } from "./consoleData";

export function Card({ title, note, action, children, className = "", bodyClass = "wh-card-body" }) {
  return (
    <section className={`wh-card ${className}`}>
      {(title || action) && (
        <header>
          <div>
            <h3>{title}</h3>
            {note && <p>{note}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Tag({ tone = "", children }) {
  return <span className={`wh-tag ${tone ? `wh-tag--${tone}` : ""}`}>{children}</span>;
}

export function Kpi({ label, value, delta, dir, bad, note }) {
  const good = delta && !bad;
  return (
    <div className="wh-kpi">
      <p>{label}</p>
      <b className="wh-num">{value}</b>
      <div className={`wh-kpi-delta ${bad ? "is-bad" : good ? "is-good" : ""}`}>
        {dir === "up" ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
        <em className="wh-num">{delta}</em>
        <span>{note}</span>
      </div>
    </div>
  );
}

export function SyntheticBadge({ compact = false }) {
  return (
    <span className="wh-synth" title={SYNTHETIC_META.note}>
      <FlaskConical size={12} />
      {compact
        ? "SYNTHETIC"
        : `SYNTHETIC DATA · schema ${SYNTHETIC_META.schemaVersion} · seed ${SYNTHETIC_META.seed}`}
    </span>
  );
}

// **강조** 만 지원하는 최소 렌더러. 데모 응답 텍스트용.
export function RichText({ text }) {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part));
}

export const axisProps = { stroke: "#bbb", tick: { fill: "#888", fontSize: 11 }, tickLine: false };
export const tooltipProps = {
  contentStyle: { borderRadius: 0, border: "1px solid #ddd", boxShadow: "0 6px 18px rgba(0,0,0,.06)", fontSize: 12 },
  labelStyle: { color: "#333", fontWeight: 600 },
};
