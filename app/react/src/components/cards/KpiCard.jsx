import { ArrowDownRight, ArrowUpRight } from "lucide-react";

export function KpiCard({ icon: Icon, title, value, unit, delta, deltaText, subtext, trend = "up", tone = "brown" }) {
  const TrendIcon = trend === "down" ? ArrowDownRight : ArrowUpRight;
  return (
    <article className="card kpi-card">
      <div className={`kpi-icon kpi-icon--${tone}`}><Icon size={25} strokeWidth={1.7} /></div>
      <div className="kpi-content">
        <p>{title}</p>
        <div className="kpi-value">{value}<small>{unit}</small></div>
        {subtext && <span className="kpi-subtext">{subtext}</span>}
        <div className={`kpi-delta kpi-delta--${trend}`}><TrendIcon size={14} /><b>{delta}</b><span>{deltaText}</span></div>
      </div>
    </article>
  );
}
