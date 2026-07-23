import { AlertCircle, Check, Clock3, Database, FileSearch, Info, MessageSquareText, ShieldCheck, Users } from "lucide-react";
import { ImpactComparison } from "./ImpactComparison";

export function FacilityDetailPanel({ facility, detail, options, selectedOptions, onToggleOption, simulated, result, cost, memo, onMemoChange, decision, onDecision }) {
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

    {isBreakfast ? <>
      <section className="response-options"><div className="panel-subheading"><div><span>RESPONSE OPTIONS</span><h4>대응안 선택</h4></div><small>복수 선택 가능</small></div><div className="option-grid">{options.map((option) => { const selected = selectedOptions.includes(option.id); return <button type="button" className={`response-option ${selected ? "is-selected" : ""}`} aria-pressed={selected} onClick={() => onToggleOption(option.id)} key={option.id}><span className="option-check">{selected && <Check size={13} />}</span><span><b>{option.label}</b><small>{option.description}</small></span></button>; })}</div></section>
      <ImpactComparison result={result} cost={cost} />
    </> : <section className="facility-action-block"><div className="panel-subheading"><div><span>RECOMMENDED CHECK</span><h4>권장 확인·조치</h4></div><Users size={17} /></div><ol>{detail.actions.map((action, index) => <li key={action}><span>{index + 1}</span>{action}</li>)}</ol></section>}

    <section className="decision-block"><div className="panel-subheading"><div><span>MANAGER DECISION</span><h4>관리자 결정</h4></div><ShieldCheck size={18} /></div><label htmlFor={`decision-memo-${facility.id}`}>관리자 메모</label><textarea id={`decision-memo-${facility.id}`} value={memo} onChange={(event) => onMemoChange(event.target.value)} placeholder={`${facility.name} 현장 확인 내용이나 결정 사유를 입력하세요.`} /><p className="execution-boundary"><Info size={13} /> 승인은 실행 후보 등록이며 실제 운영 조치를 자동 실행하지 않습니다.</p><div className="decision-actions"><button type="button" onClick={() => onDecision("승인")}>승인</button><button type="button" onClick={() => onDecision("보류")}>보류</button><button type="button" onClick={() => onDecision("반려")}>반려</button></div>{decision && <div className={`decision-result decision-result--${decision.type}`} role="status"><b>{decision.label}</b><span>{decision.message}</span><small>{decision.time}</small></div>}</section>
  </aside>;
}
