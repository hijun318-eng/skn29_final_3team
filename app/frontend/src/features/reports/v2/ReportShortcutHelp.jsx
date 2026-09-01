/** 실서비스 보고서 편집기에서 실제로 지원하는 키보드 조작만 안내하는 modal이다. */
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Keyboard, X } from "lucide-react";

const SHORTCUTS = [
  [["Ctrl / Cmd + S"], "현재 보고서 저장"],
  [["Ctrl / Cmd + Z"], "실행 취소"],
  [["Ctrl / Cmd + Y", "Ctrl / Cmd + Shift + Z"], "다시 실행"],
  [["Ctrl / Cmd + C / V"], "선택 블록 복사 / 붙여넣기"],
  [["Delete / Backspace"], "선택 블록 삭제"],
  [["Shift + 클릭"], "블록 다중 선택 추가 / 제거"],
  [["Space / Enter"], "이동 손잡이의 키보드 이동 시작"],
  [["방향키"], "이동·크기 조절을 한 단계씩 변경"],
  [["Alt + 휠"], "표 블록의 너비·높이를 한 단계 확대 / 축소"],
  [["Esc"], "이동·크기 조절 또는 이 안내 닫기"],
];

/** modal 배경을 inert 처리하고 Tab 순환·Esc·trigger focus 복귀를 보장한다. */
export function ReportShortcutHelp({ open, onClose, theme = "dark" }) {
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const returnFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    returnFocusRef.current = document.activeElement;
    const editor = document.querySelector("[data-report-builder='v2']");
    const previousAriaHidden = editor?.getAttribute("aria-hidden");
    if (editor) {
      editor.inert = true;
      editor.setAttribute("aria-hidden", "true");
    }
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    const containFocus = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      const controls = dialog ? [...dialog.querySelectorAll("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])")]
        .filter((element) => element.getClientRects().length > 0) : [];
      if (!controls.length) {
        event.preventDefault();
        dialog?.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", containFocus);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", containFocus);
      if (editor) {
        editor.inert = false;
        if (previousAriaHidden === null) editor.removeAttribute("aria-hidden");
        else editor.setAttribute("aria-hidden", previousAriaHidden);
      }
      window.requestAnimationFrame(() => returnFocusRef.current?.focus?.());
    };
  }, [onClose, open]);

  if (!open) return null;
  const overlay = <div className={`report-shortcut-backdrop ${theme === "light" ? "theme-light" : "theme-dark"}`} onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }} onKeyDown={(event) => {
    event.stopPropagation();
    if (event.key === "Escape") onClose();
  }}>
    <section ref={dialogRef} tabIndex={-1} className="report-shortcut-dialog" role="dialog" aria-modal="true" aria-labelledby="report-shortcut-title">
      <header><div><Keyboard size={18} /><h2 id="report-shortcut-title">단축키</h2></div><button ref={closeRef} type="button" onClick={onClose} aria-label="단축키 닫기"><X size={17} /></button></header>
      <p>블록을 선택한 뒤 사용할 수 있습니다. 입력 중에는 일반 편집 키가 우선합니다.</p>
      <dl>{SHORTCUTS.map(([keys, description]) => <div key={keys.join(":")}><dt>{keys.map((key) => <kbd key={key}>{key}</kbd>)}</dt><dd>{description}</dd></div>)}</dl>
    </section>
  </div>;
  return createPortal(overlay, document.body);
}
