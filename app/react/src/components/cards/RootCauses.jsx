const causes = [
  { name: "체크인 인력 부족", detail: "인사/운영", probability: 87, tone: "danger" },
  { name: "시스템 처리 지연", detail: "IT 인프라", probability: 64, tone: "warning" },
  { name: "성수기 예약 집중", detail: "수요 예측", probability: 91, tone: "danger" },
  { name: "교육 미흡", detail: "인적자원", probability: 43, tone: "neutral" },
  { name: "동시 단체 투숙", detail: "예약관리", probability: 78, tone: "warning" },
];

export function RootCauses() {
  return (
    <article className="card bottom-card">
      <div className="section-heading"><div><p>체크인 대기 이슈 기준</p><h2>원인 후보 및 가능성</h2></div></div>
      <div className="cause-list">
        {causes.map((cause) => <div className="cause" key={cause.name}>
          <div><b>{cause.name}</b><small>{cause.detail}</small></div><strong>{cause.probability}%</strong>
          <div className="progress"><i className={`progress--${cause.tone}`} style={{ width: `${cause.probability}%` }} /></div>
        </div>)}
      </div>
      <p className="disclaimer">가능성은 조사 우선순위를 의미하며 확정 원인이 아닙니다.</p>
    </article>
  );
}
