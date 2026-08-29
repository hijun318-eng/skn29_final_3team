/** 분석·보고서 화면이 공유하는 기준일 meta와 섹션 제목 UI 모듈이다. */

/** 서버 기준일만 표시하며 meta 부재 시 추정값 없이 렌더링을 생략한다. */
export function MetaStrip({ meta }) {
  if (!meta) return null;
  return (
    <div className="meta-strip" aria-label="분석 데이터 기준일">
      {meta.asOf && <span>데이터 기준일 {meta.asOf} · 서울 시간</span>}
    </div>
  );
}

/** 화면 섹션의 접근 가능한 제목과 선택적 설명·액션을 일관된 구조로 렌더링한다. */
export function SectionTitle({ eyebrow, title, description, action }) {
  return (
    <header className="section-title">
      <div><p>{eyebrow}</p><h2>{title}</h2>{description && <span>{description}</span>}</div>
      {action}
    </header>
  );
}
