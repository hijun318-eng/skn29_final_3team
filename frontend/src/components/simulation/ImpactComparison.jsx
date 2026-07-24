import { Sparkles, TrendingDown } from "lucide-react";

export function ImpactComparison({ result, cost }) {
  const statusTone = result.status === "정상" ? "normal" : result.status === "주의" ? "warning" : "danger";
  return (
    <section className="impact-comparison" aria-labelledby="impact-title">
      <div className="panel-subheading"><div><span>SCENARIO IMPACT</span><h4 id="impact-title">예상 효과 비교</h4></div><span className="forecast-badge"><Sparkles size={12} /> 예상</span></div>
      <div className="comparison-table" role="table" aria-label="대응 적용 전후 예상 효과">
        <div className="comparison-row comparison-head" role="row"><span>변화 항목</span><span>현재</span><span>대응 적용 후</span></div>
        <div className="comparison-row" role="row"><b>평균 대기시간</b><span>18분</span><strong><TrendingDown size={13} /> {result.wait}분</strong></div>
        <div className="comparison-row" role="row"><b>혼잡도</b><span className="status-text status-text--danger">위험</span><strong className={`status-text status-text--${statusTone}`}>{result.status}</strong></div>
        <div className="comparison-row" role="row"><b>예상 부정 VOC</b><span>13건</span><strong>{result.voc}건</strong></div>
        <div className="comparison-row" role="row"><b>추가 운영비</b><span>-</span><strong>{cost.toLocaleString("ko-KR")}원</strong></div>
      </div>
      <p className="scenario-disclaimer">선택한 대응안과 고정된 합성 시나리오 규칙으로 계산한 예시입니다. 실제 효과를 보장하지 않습니다.</p>
    </section>
  );
}
