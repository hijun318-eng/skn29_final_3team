import { AlertCircle, AlertTriangle, CheckCircle2 } from "lucide-react";

const icons = { danger: AlertCircle, warning: AlertTriangle, normal: CheckCircle2 };

export function FacilityMarker({ facility, selected, simulated, onSelect }) {
  const effectiveStatus = facility.id === "breakfast" && simulated ? "warning" : facility.status;
  const Icon = icons[effectiveStatus] || CheckCircle2;
  const statusLabel = effectiveStatus === "warning" ? "주의" : facility.statusLabel;

  return (
    <button
      type="button"
      className={`facility-marker facility-marker--${effectiveStatus} ${selected ? "is-selected" : ""} ${facility.id === "breakfast" && !simulated ? "is-pulsing" : ""}`}
      style={{ left: `${facility.labelX ?? facility.x}%`, top: `${facility.labelY ?? facility.y}%` }}
      onClick={() => onSelect(facility.id)}
      aria-pressed={selected}
      aria-label={`${facility.name}, ${statusLabel}, ${facility.metric}`}
    >
      <span className="facility-marker__icon"><Icon size={15} strokeWidth={2.2} /></span>
      <span className="facility-marker__copy"><b>{facility.name}</b><small>{statusLabel} · {facility.metric}</small></span>
    </button>
  );
}
