/** 실서비스 보고서 편집기에서 실제로 지원하는 키보드 조작만 안내하는 modal이다. */
import { useEffect, useRef } from "react";
import { Keyboard, X } from "lucide-react";

const SHORTCUTS = [
  ["Ctrl / Cmd + S", "현재 draft를 서버에 저장"],
  ["Ctrl / Cmd + Z", "실행 취소"],
  ["Ctrl / Cmd + Y · Ctrl / Cmd + Shift + Z", "다시 실행"],
  ["Ctrl / Cmd + C / V", "선택 블록 복사 / 붙여넣기"],
  ["Delete / Backspace", "선택 블록 삭제"],
  ["Shift + 클릭", "블록 다중 선택 추가 / 제거"],
  ["Space / Enter", "이동 손잡이의 키보드 이동 시작"],
  ["방향키", "이동·크기 조절 중 12열 격자 단위 조정"],
  ["Alt + 휠", "표 블록의 너비·높이를 한 단계 확대 / 축소"],
  ["Esc", "이동·크기 조절 또는 이 안내 닫기"],
];

/** 배경·닫기 버튼·Esc를 지원하고 열릴 때 닫기 버튼으로 초점을 옮긴다. */
export function ReportShortcutHelp({ open, onClose }) {
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  if (!open) return null;
  return <div className="report-shortcut-backdrop" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }} onKeyDown={(event) => {
    event.stopPropagation();
    if (event.key === "Escape") onClose();
  }}>
    <section className="report-shortcut-dialog" role="dialog" aria-modal="true" aria-labelledby="report-shortcut-title">
      <header><div><Keyboard size={18} /><h2 id="report-shortcut-title">단축키 안내</h2></div><button ref={closeRef} type="button" onClick={onClose} aria-label="단축키 안내 닫기"><X size={17} /></button></header>
      <p>입력창 밖에서 선택한 블록에 적용됩니다. 제목과 본문을 입력할 때는 일반 편집 키가 우선합니다.</p>
      <table><tbody>{SHORTCUTS.map(([key, description]) => <tr key={key}><th scope="row"><kbd>{key}</kbd></th><td>{description}</td></tr>)}</tbody></table>
    </section>
  </div>;
}
