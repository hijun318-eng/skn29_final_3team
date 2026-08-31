/** 분석·보고서 화면이 공유하는 섹션 제목 UI 모듈이다. */

/** 화면 섹션의 접근 가능한 제목과 선택적 설명·액션을 일관된 구조로 렌더링한다. */
export function SectionTitle({ eyebrow, title, description, action }) {
  return (
    <header className="section-title">
      <div><p>{eyebrow}</p><h2>{title}</h2>{description && <span>{description}</span>}</div>
      {action}
    </header>
  );
}
