/** 보고서 text block의 접근 가능한 Markdown 편집·format 명령을 제공하는 모듈이다. */
import { memo, useEffect, useRef, useState } from "react";
import { Bold, Heading2, Italic, Link2, List, ListChecks, Minus, Quote, Table2 } from "lucide-react";

import { MarkdownText } from "./ReportArtifactContent";

/** toolbar와 키보드가 공유하는 안전한 Markdown 삽입 명령 집합이다. */ export const MARKDOWN_INSERT_COMMANDS = [
  {
    id: "heading",
    title: "소제목",
    description: "내용을 구분하는 2단계 제목",
    aliases: ["제목", "heading", "h2"],
    group: "텍스트",
    shortcut: "##",
    icon: Heading2,
    content: "## 소제목",
  },
  {
    id: "list",
    title: "글머리 목록",
    description: "항목을 빠르게 나열",
    aliases: ["목록", "list", "bullet"],
    group: "텍스트",
    shortcut: "-",
    icon: List,
    content: "- 목록 항목",
  },
  {
    id: "checklist",
    title: "체크리스트",
    description: "실행 항목과 후속 조치",
    aliases: ["할 일", "todo", "check"],
    group: "텍스트",
    shortcut: "[]",
    icon: ListChecks,
    content: "- [ ] 할 일",
  },
  {
    id: "quote",
    title: "인사이트",
    description: "핵심 해석을 강조",
    aliases: ["인용", "quote", "callout"],
    group: "텍스트",
    shortcut: ">",
    icon: Quote,
    content: "> 핵심 인사이트",
  },
  {
    id: "table",
    title: "Markdown 표",
    description: "간단한 비교 표 삽입",
    aliases: ["표", "table", "grid"],
    group: "구조",
    shortcut: "|",
    icon: Table2,
    content: "| 항목 | 값 |\n| --- | ---: |\n| 지표 | 값 입력 |",
  },
  {
    id: "divider",
    title: "구분선",
    description: "문서 흐름을 시각적으로 분리",
    aliases: ["선", "divider", "rule"],
    group: "구조",
    shortcut: "---",
    icon: Minus,
    content: "---",
  },
];

function markdownSlashContext(content, cursor) {
  const from = content.lastIndexOf("\n", Math.max(0, cursor - 1)) + 1;
  const line = content.slice(from, cursor);
  const match = line.match(/^\/([^\s/]*)$/);
  return match
    ? { from, to: cursor, query: match[1].toLocaleLowerCase("ko-KR") }
    : null;
}

/** Markdown 입력·선택·명령을 조정하며 memo 경계가 무관한 block 변경의 재렌더를 차단한다. */
export const MarkdownBlockEditor = memo(function MarkdownBlockEditor({
  block,
  disabled,
  onModeChange,
  onUpdate,
}) {
  const textareaRef = useRef(null);
  const slashMenuRef = useRef(null);
  const typingTimerRef = useRef(null);
  const typingTransactionRef = useRef(false);
  const [mode, setMode] = useState("edit");
  const [slash, setSlash] = useState(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const slashCommands = slash ? MARKDOWN_INSERT_COMMANDS.filter((command) => (
    !slash.query
    || `${command.title} ${command.description} ${command.aliases.join(" ")}`
      .toLocaleLowerCase("ko-KR")
      .includes(slash.query)
  )) : [];

  useEffect(() => {
    setSlash(null);
    setSlashIndex(0);
    typingTransactionRef.current = false;
    window.clearTimeout(typingTimerRef.current);
    return () => window.clearTimeout(typingTimerRef.current);
  }, [block.id, mode]);

  useEffect(() => {
    slashMenuRef.current
      ?.querySelector(`[data-slash-index="${slashIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [slashIndex, slashCommands.length]);

  const updateSlash = (content, cursor) => {
    setSlash(markdownSlashContext(content, cursor));
    setSlashIndex(0);
  };

  const changeMode = (nextMode) => {
    if (mode === nextMode) return;
    setMode(nextMode);
    setSlash(null);
    onModeChange?.(nextMode);
    if (nextMode === "edit") {
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        const cursor = textarea?.value.length ?? 0;
        textarea?.focus();
        textarea?.setSelectionRange(cursor, cursor);
      });
    }
  };

  const insertSlashCommand = (command) => {
    if (!slash) return;
    const content = block.content || "";
    const next = `${content.slice(0, slash.from)}${command.content}${content.slice(slash.to)}`;
    const cursor = slash.from + command.content.length;
    onUpdate({ content: next }, true);
    setSlash(null);
    setSlashIndex(0);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(cursor, cursor);
    });
  };

  const handleTextareaKeyDown = (event) => {
    if (!slash) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setSlash(null);
      return;
    }
    if (!slashCommands.length) return;
    if (event.key === "Home") {
      event.preventDefault();
      setSlashIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setSlashIndex(slashCommands.length - 1);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setSlashIndex((index) => (index + 1) % slashCommands.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSlashIndex((index) => (index - 1 + slashCommands.length) % slashCommands.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      insertSlashCommand(slashCommands[slashIndex] || slashCommands[0]);
    }
  };

  const apply = (command) => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const content = block.content || "";
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = content.slice(start, end);
    const wrappers = {
      bold: ["**", "**", "강조할 내용"],
      italic: ["*", "*", "기울임"],
      link: ["[", "](https://)", "링크 텍스트"],
    };
    let from = start;
    let to = end;
    let replacement;
    if (wrappers[command]) {
      const [before, after, fallback] = wrappers[command];
      replacement = `${before}${selected || fallback}${after}`;
    } else {
      const prefix = { heading: "## ", list: "- ", quote: "> " }[command];
      from = content.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
      const lineEnd = content.indexOf("\n", end);
      to = lineEnd < 0 ? content.length : lineEnd;
      replacement = content
        .slice(from, to)
        .split("\n")
        .map((line) => `${prefix}${line}`)
        .join("\n");
    }
    const next = `${content.slice(0, from)}${replacement}${content.slice(to)}`;
    onUpdate({ content: next }, true);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(from, from + replacement.length);
    });
  };

  const preview = disabled || mode === "preview";

  return (
    <div className={`report-markdown-editor ${preview ? "is-preview" : "is-editing"}`}>
      {!disabled && mode === "edit" && (
        <div className="report-markdown-toolbar" aria-label={`${block.title} Markdown 도구`}>
          <div>
            <button type="button" title="굵게" aria-label="굵게" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("bold")}><Bold size={14} /></button>
            <button type="button" title="기울임" aria-label="기울임" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("italic")}><Italic size={14} /></button>
            <button type="button" title="소제목" aria-label="소제목" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("heading")}><Heading2 size={14} /></button>
            <button type="button" title="목록" aria-label="목록" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("list")}><List size={14} /></button>
            <button type="button" title="인용" aria-label="인용" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("quote")}><Quote size={14} /></button>
            <button type="button" title="링크" aria-label="링크" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("link")}><Link2 size={14} /></button>
          </div>
          <div className="report-markdown-mode">
            <button type="button" onClick={() => changeMode("preview")}>미리보기</button>
          </div>
        </div>
      )}
      {preview ? (
        <>
          {!disabled && (
            <div className="report-markdown-preview-actions" data-report-editor-chrome="true">
              <button type="button" onClick={() => changeMode("edit")}>편집</button>
            </div>
          )}
          <div className="report-markdown-preview"><MarkdownText content={block.content} /></div>
        </>
      ) : (
        <>
          <textarea
            ref={textareaRef}
            className="notion-markdown-input"
            aria-label={`${block.title} 내용`}
            aria-expanded={Boolean(slash)}
            aria-controls={slash ? `${block.id}-slash-menu` : undefined}
            aria-activedescendant={slash && slashCommands.length
              ? `${block.id}-slash-option-${slashCommands[slashIndex]?.id}`
              : undefined}
            disabled={disabled}
            value={block.content || ""}
            onChange={(event) => {
              const record = !typingTransactionRef.current;
              typingTransactionRef.current = true;
              window.clearTimeout(typingTimerRef.current);
              typingTimerRef.current = window.setTimeout(() => {
                typingTransactionRef.current = false;
              }, 700);
              onUpdate({ content: event.target.value }, record);
              updateSlash(event.target.value, event.target.selectionStart);
            }}
            onClick={(event) => updateSlash(
              event.currentTarget.value,
              event.currentTarget.selectionStart,
            )}
            onKeyUp={(event) => {
              if (!["ArrowDown", "ArrowUp", "Home", "End", "Enter", "Escape"].includes(event.key)) {
                updateSlash(event.currentTarget.value, event.currentTarget.selectionStart);
              }
            }}
            onKeyDown={handleTextareaKeyDown}
            placeholder="내용을 입력하세요. Markdown 표·목록·체크박스·링크를 사용할 수 있습니다."
          />
          {slash && (
            <div
              ref={slashMenuRef}
              id={`${block.id}-slash-menu`}
              className="report-slash-menu"
              role="listbox"
              aria-label="Markdown 블록 삽입"
            >
              <header>
                <b>블록 삽입</b>
                <span>↑↓·Home·End 선택 · Enter 삽입 · Esc 닫기</span>
              </header>
              {slashCommands.length ? slashCommands.map((command, index) => {
                const Icon = command.icon;
                return (
                  <button
                    id={`${block.id}-slash-option-${command.id}`}
                    data-slash-index={index}
                    type="button"
                    role="option"
                    aria-selected={index === slashIndex}
                    className={index === slashIndex ? "active" : ""}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => insertSlashCommand(command)}
                    key={command.id}
                  >
                    <Icon size={15} aria-hidden="true" />
                    <span>
                      <small>{command.group}</small>
                      <b>{command.title}</b>
                      <small>{command.description}</small>
                    </span>
                    <kbd>{command.shortcut}</kbd>
                  </button>
                );
              }) : <p role="status">일치하는 블록이 없습니다.</p>}
            </div>
          )}
          <small className="report-markdown-hint">
            <kbd>/</kbd> 입력으로 제목·목록·표를 바로 삽입할 수 있습니다.
          </small>
        </>
      )}
    </div>
  );
});
