/** 승인된 PMS 예측의 진행·실패·검증 결과를 근거 정보와 함께 표시한다. */
import { useState } from "react";
import { Activity, BarChart3, Check, ChevronDown, Database, ShieldCheck, Sparkles, X, XCircle } from "lucide-react";
import "./MLPredictionCard.css";

const STAGES = [["요청 분석", Sparkles],["권한 확인", ShieldCheck],["PMS 데이터 조회", Database],["수요 예측", Activity],["결과 검증", Check]];
const number = (value, digits = 1) => Number(value || 0).toLocaleString("ko-KR", { maximumFractionDigits: digits });
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;

/** 실행 상태에 따라 예측 진행 단계, KPI 또는 재시도 가능한 실패를 렌더링한다. */
export function MLPredictionCard({ run, disabled, onRetry }) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const prediction = run.mlPrediction;
  const completed = prediction.completedStages || 0;

  if (prediction.status === "RUNNING") return (
    <section className="ml-result ml-result--running" aria-live="polite">
      <div className="ml-result__running-head"><Activity size={18}/><b>실제 PMS 데이터 기반 예측을 실행하고 있습니다.</b></div>
      <ol className="ml-stages">{STAGES.map(([label, Icon], index) => (
        <li key={label} className={index < completed ? "is-done" : index === completed ? "is-active" : ""}>
          <span>{index < completed ? <Check size={14}/> : <Icon size={14}/>}</span>{label}{index < completed ? " 완료" : ""}
        </li>
      ))}</ol>
    </section>
  );

  if (prediction.status === "FAILED") return (
    <section className="ml-result ml-result--failed" role="alert">
      <div><XCircle size={20}/><b>예측을 실행하지 않았습니다.</b></div>
      <p>{prediction.error || run.error?.message}</p>
      {run.error?.retryable && <button type="button" disabled={disabled} onClick={onRetry}>다시 시도</button>}
    </section>
  );

  const summary = prediction.summary;
  const daily = prediction.daily || [];
  const roomTypes = prediction.roomTypes || [];
  const maxAvailable = Math.max(1, ...daily.map((row) => row.available_rooms));
  const kpis = [
    ["예측 판매 객실박", summary.totalPredicted, `일평균 ${number(summary.dailyAverage)}개`],
    ["전체 공급 객실박", summary.totalAvailable, ""],
    ["잔여 예상 객실박", summary.totalRemaining, ""],
    ["가중 예측 점유율", percent(summary.weightedOccupancy), ""],
  ];

  return <section className="ml-result">
    <header className="ml-result__header">
      <div><small>LIVE PMS FORECAST</small><h3>{prediction.request.hotelScope} 객실 수요 예측</h3><p>향후 {prediction.request.horizon}일 · 기준일 {prediction.request.asOf}</p></div>
      <span><Check size={13}/>검증 완료</span>
    </header>
    <p className="ml-result__answer">향후 {prediction.request.horizon}일 동안 전체 <b>{number(summary.totalAvailable)} 객실박</b> 중 약 <strong>{number(summary.totalPredicted)} 객실박</strong>이 판매될 것으로 예측됩니다. 하루 평균 예상 판매 객실 수는 <b>{number(summary.dailyAverage)}개</b>입니다.</p>
    <div className="ml-kpis">{kpis.map(([label, value, helper], index) => <article key={label} className={index === 0 ? "is-primary" : ""}><small>{label}</small><b>{typeof value === "number" ? number(value) : value}</b>{helper && <span>{helper}</span>}</article>)}</div>
    <div className="ml-capacity"><span style={{ width: `${Math.min(100, summary.weightedOccupancy)}%` }}/></div>
    <small className="ml-capacity__label">전체 공급 대비 예측 판매 {percent(summary.weightedOccupancy)}</small>

    <section className="ml-section">
      <h4><BarChart3 size={17}/>날짜별 수요 변화</h4>
      <div className="ml-chart">{daily.map((row) => <div className="ml-chart__day" key={row.target_date}>
        <div className="ml-chart__bars"><i className="available" style={{height:`${row.available_rooms/maxAvailable*100}%`}}/><i className="booked" style={{height:`${row.booking_on_hand/maxAvailable*100}%`}}/><i className="predicted" style={{height:`${row.predicted_rooms_sold/maxAvailable*100}%`}}/></div>
        <span>{row.target_date.slice(5)}</span>
      </div>)}</div>
      <div className="ml-legend"><span className="available">전체</span><span className="booked">현재 예약</span><span className="predicted">예측 판매</span></div>
      <p className="ml-trend">{prediction.trendDescription} 수요 변화의 원인으로 단정하지 않습니다.</p>
    </section>

    <section className="ml-section"><h4>날짜별 요약</h4><div className="ml-table-wrap"><table><thead><tr><th>날짜</th><th>전체</th><th>현재 예약</th><th>예측 판매</th><th>잔여</th><th>점유율</th></tr></thead><tbody>
      {daily.map((row) => <tr key={row.target_date}><td>{row.target_date}</td><td>{number(row.available_rooms)}</td><td>{number(row.booking_on_hand)}</td><td><b>{number(row.predicted_rooms_sold)}</b></td><td>{number(row.remaining_rooms)}</td><td>{percent(Number(row.predicted_occupancy_rate) * 100)}</td></tr>)}
    </tbody></table></div></section>

    <button className="ml-disclosure" type="button" onClick={() => setDetailsOpen((open) => !open)}><ChevronDown size={16}/>객실 유형별 상세 {detailsOpen ? "닫기" : "보기"}</button>
    {detailsOpen && <div className="ml-table-wrap"><table><thead><tr><th>날짜</th><th>객실 유형</th><th>전체 공급</th><th>현재 예약</th><th>예측 판매</th><th>점유율</th></tr></thead><tbody>
      {roomTypes.map((row,index) => <tr key={`${row.target_date}-${row.room_type_code||index}`}><td>{row.target_date}</td><td>{row.room_type_code||row.room_type||row.room_type_id||"-"}</td><td>{number(row.available_room_nights)}</td><td>{number(row.booking_on_hand)}</td><td>{number(row.predicted_rooms_sold)}</td><td>{percent(Number(row.predicted_occupancy_rate)*100)}</td></tr>)}
    </tbody></table></div>}

    <aside className="ml-limitation"><b>현재 분석 범위</b><p>프로모션·행사·외부 이벤트 데이터는 예측 입력에 연동되어 있지 않아 수요 변화의 원인을 해당 요인으로 확정할 수 없습니다.</p></aside>
    <footer><button type="button" onClick={() => setEvidenceOpen(true)}>실행 근거 보기</button></footer>
    {evidenceOpen && <div className="ml-evidence-backdrop" onMouseDown={() => setEvidenceOpen(false)}><aside className="ml-evidence" onMouseDown={(event) => event.stopPropagation()}>
      <header><h3>실행 근거</h3><button type="button" aria-label="닫기" onClick={() => setEvidenceOpen(false)}><X size={18}/></button></header>
      <Evidence label="호텔" value={prediction.request.hotelScope}/><Evidence label="지표" value={prediction.request.metric}/><Evidence label="기간" value={`${prediction.request.horizon}일`}/>
      <h4>검증 단계</h4><p>사용자·데이터 접근 권한 확인 완료</p><p>승인 모델 scope 확인 완료</p><p>Trino PMS 조회 완료</p><p>예측 결과 및 KPI 집계 검증 완료</p>
      <h4>기술 정보</h4><Evidence label="Request ID" value={prediction.evidence.requestId}/><Evidence label="Trace ID" value={prediction.evidence.traceId}/><Evidence label="Execution ID" value={prediction.evidence.executionId}/><Evidence label="모델" value={prediction.evidence.modelName}/><Evidence label="버전" value={prediction.evidence.modelVersion}/><Evidence label="Artifact hash" value={prediction.evidence.artifactHash}/><Evidence label="Feature source" value={prediction.evidence.featureSource}/><Evidence label="Training source" value={prediction.evidence.trainingSource}/><Evidence label="Feature as-of" value={prediction.evidence.featureAsOf}/><Evidence label="Prediction rows" value={prediction.evidence.predictionRows}/><Evidence label="Trino Query IDs" value={(prediction.evidence.trinoQueryIds||[]).join(", ")}/>
    </aside></div>}
  </section>;
}

/** 실행 근거의 한 라벨과 값을 누락 안전 표기로 표시한다. */
function Evidence({ label, value }) {
  return <div className="ml-evidence__row"><b>{label}</b><span>{value || "-"}</span></div>;
}
