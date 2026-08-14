import { ShieldCheck } from "lucide-react";

export function MetaStrip({ meta, verified = false }) {
  if (!meta) return null;
  return (
    <div className="meta-strip">
      <ShieldCheck size={13} />
      <span>{verified ? "분석 근거 연결 완료" : "분석 요청 기준"}</span>
      {meta.asOf && <span>데이터 기준일 {meta.asOf} · 서울 시간</span>}
    </div>
  );
}

export function SectionTitle({ eyebrow, title, description, action }) {
  return (
    <header className="section-title">
      <div><p>{eyebrow}</p><h2>{title}</h2>{description && <span>{description}</span>}</div>
      {action}
    </header>
  );
}
