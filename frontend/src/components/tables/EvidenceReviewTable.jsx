const reviews = [
  { date: "7/13", channel: "OTA", review: "체크인에 40분이나 기다렸습니다. 직원이 너무 부족한 것 같아요.", sentiment: "부정", tone: "negative", confidence: 94 },
  { date: "7/12", channel: "네이버", review: "객실은 넓고 좋았지만 청결 상태가 기대 이하였어요.", sentiment: "부정", tone: "negative", confidence: 87 },
  { date: "7/12", channel: "구글", review: "전반적으로 만족스러웠으나 레스토랑 예약이 너무 어려웠습니다.", sentiment: "혼합", tone: "mixed", confidence: 79 },
  { date: "7/11", channel: "OTA", review: "엘리베이터 대기가 길었습니다. 로비가 매우 혼잡했어요.", sentiment: "부정", tone: "negative", confidence: 82 },
  { date: "7/11", channel: "카카오", review: "야경이 정말 훌륭했고 서비스도 친절했습니다. 재방문 의향 있어요.", sentiment: "긍정", tone: "positive", confidence: 96 },
];

export function EvidenceReviewTable() {
  return (
    <article className="card evidence-card">
      <div className="section-heading"><div><p>최근 분석된 고객 VOC · AI 신뢰도 포함</p><h2>근거 리뷰</h2></div></div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>날짜</th><th>채널</th><th>내용</th><th>감성</th><th>AI 신뢰도</th></tr></thead>
          <tbody>{reviews.map((row, index) => <tr key={`${row.date}-${index}`}><td>{row.date}</td><td>{row.channel}</td><td className="review-copy">{row.review}</td><td><span className={`sentiment sentiment--${row.tone}`}>{row.sentiment}</span></td><td><div className="confidence"><span><i style={{ width: `${row.confidence}%` }} /></span><b>{row.confidence}%</b></div></td></tr>)}</tbody>
        </table>
      </div>
    </article>
  );
}
