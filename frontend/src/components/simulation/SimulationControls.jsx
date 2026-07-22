import { Activity, Clock3 } from "lucide-react";

export function SimulationControls({ simulated, onModeChange, timeline, timeIndex, onTimeChange }) {
  return (
    <div className="simulation-controls">
      <div className="mode-switch" role="group" aria-label="운영 맵 표시 모드">
        <button type="button" className={!simulated ? "is-active" : ""} aria-pressed={!simulated} onClick={() => onModeChange(false)}>현재 운영</button>
        <button type="button" className={simulated ? "is-active" : ""} aria-pressed={simulated} onClick={() => onModeChange(true)}><Activity size={14} /> 시뮬레이션</button>
      </div>
      <div className={`time-control ${simulated ? "" : "is-disabled"}`}>
        <div><Clock3 size={14} /><span>조치 후 예상 변화</span><b>{timeline[timeIndex].label}</b></div>
        <input type="range" min="0" max="3" step="1" value={timeIndex} disabled={!simulated} onChange={(event) => onTimeChange(Number(event.target.value))} aria-label="조치 후 예상 시간" />
        <div className="time-labels">{timeline.map((point) => <span key={point.label}>{point.label}</span>)}</div>
      </div>
    </div>
  );
}
