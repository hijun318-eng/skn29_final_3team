import { AlertTriangle, ArrowRight, CheckCircle2 } from "lucide-react";

export function OperationalBrief() {
  return (
    <section className="operational-brief" aria-label="Executive operational summary">
      <div className="health-status">
        <span className="health-icon"><AlertTriangle size={19} /></span>
        <div>
          <p>OPERATIONAL HEALTH</p>
          <h2>Attention Required</h2>
        </div>
        <span className="health-note">2 decisions need review today</span>
      </div>

      <div className="brief-divider" />

      <div className="executive-summary">
        <p>EXECUTIVE SUMMARY</p>
        <strong>Breakfast congestion is the primary service risk this week.</strong>
        <span>Negative VOC rose 2.1%p alongside a 2.6-minute increase in waiting time.</span>
      </div>

      <div className="brief-divider" />

      <div className="recommended-action">
        <span><CheckCircle2 size={17} /> AI RECOMMENDATION</span>
        <strong>Review 08:00–09:00 staffing allocation</strong>
        <button>Open decision brief <ArrowRight size={14} /></button>
      </div>
    </section>
  );
}
