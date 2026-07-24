import { AlertCircle, ArrowRight, Clock3, Database, FileSearch, Info, MessageSquareText, Users } from "lucide-react";

export function FacilityDetailPanel({ facility, detail, simulated }) {
  const isBreakfast = facility.id === "breakfast";
  const effectiveStatus = isBreakfast && simulated ? "주의" : facility.statusLabel;
  const tone = effectiveStatus === "위험" ? "danger" : effectiveStatus === "주의" ? "warning" : "normal";

  return <aside className="facility-panel" aria-label={`${facility.name} 운영 상세`}>
    <div className="facility-summary">
      <div><span className="panel-eyebrow">SELECTED FACILITY</span><h3>{facility.name}</h3></div>
      <span className={`facility-status facility-status--${tone}`}><AlertCircle size={13} /> {effectiveStatus}</span>
    </div>

    <div className="current-metric"><div><span>{detail.metricLabel}</span><strong>{detail.metricValue}<small>{detail.metricUnit}</small></strong></div><div><Clock3 size={14} /><span>{detail.observedAt}</span><em>Synthetic data</em></div></div>

    <section className="evidence-block"><div className="panel-subheading"><div><span>OBSERVED FACTS</span><h4>관측 사실</h4></div><small>{detail.owner}</small></div><ul>{detail.facts.map((fact, index) => <li key={fact}>{index === 0 ? <Database size={14} /> : index === 1 ? <Clock3 size={14} /> : <FileSearch size={14} />}<span>{fact}</span></li>)}</ul></section>

    <section className="cause-block"><div className="panel-subheading"><div><span>EVIDENCE REVIEW</span><h4>원인 후보와 반대 근거</h4></div></div><div className="cause-note"><b>원인 후보</b><span>{detail.cause}</span></div><div className="counter-note"><b>반대 근거</b><span>{detail.counter}</span></div><p><Info size={13} /> 확정 원인이 아닌 관측 데이터 기반 후보입니다.</p></section>

    <section className="facility-voc-block"><div className="panel-subheading"><div><span>RECENT VOC</span><h4>최근 고객 의견</h4></div><MessageSquareText size={17} /></div><blockquote>“{detail.recentVoc}”</blockquote></section>

    <section className="facility-action-block"><div className="panel-subheading"><div><span>RECOMMENDED CHECK</span><h4>권장 확인·조치</h4></div><Users size={17} /></div><ol>{detail.actions.map((action, index) => <li key={action}><span>{index + 1}</span>{action}</li>)}</ol></section>

    {isBreakfast && <section className="analysis-handoff"><Info size={15} /><div><b>관리자 검토는 정기 보고서에서 진행합니다.</b><p>대응안 선택, 예상 효과 비교와 승인·보류는 보고서의 운영 대응안 검토에서 확인할 수 있습니다.</p><a href="/reports#response-review">정기 보고서에서 검토 <ArrowRight size={13} /></a></div></section>}
  </aside>;
}
