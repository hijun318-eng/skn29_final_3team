/** 보고서 편집기의 실제 지원 단축키를 입력 요소와 블록 포커스 규칙에 맞춰 연결한다. */
import { useCallback, type KeyboardEvent } from "react";

interface ReportEditorKeyboardOptions {
  readonly canEdit: boolean;
  readonly copySelected: () => void;
  readonly deleteSelected: () => void;
  readonly pasteBlocks: () => void;
  readonly redo: () => void;
  readonly saveDraft: () => Promise<void>;
  readonly undo: () => void;
}

/** 브라우저 기본 입력 단축키를 보존하면서 editor 범위 명령만 가로챈다. */
export function useReportEditorKeyboard(options: ReportEditorKeyboardOptions) {
  return useCallback((event: KeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    const textField = ["input", "textarea", "select"].includes(target.tagName.toLowerCase());
    if (!textField && options.canEdit && ["Delete", "Backspace"].includes(event.key)) {
      event.preventDefault();
      options.deleteSelected();
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "s" && options.canEdit) {
      event.preventDefault();
      void options.saveDraft();
      return;
    }
    if (textField) return;
    if (key === "c") { event.preventDefault(); options.copySelected(); }
    else if (key === "v" && options.canEdit) { event.preventDefault(); options.pasteBlocks(); }
    else if (key === "z" && event.shiftKey) { event.preventDefault(); options.redo(); }
    else if (key === "z") { event.preventDefault(); options.undo(); }
    else if (key === "y") { event.preventDefault(); options.redo(); }
  }, [options]);
}
