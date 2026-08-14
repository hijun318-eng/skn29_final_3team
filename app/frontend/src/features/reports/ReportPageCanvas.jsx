import { useLayoutEffect, useRef, useState } from "react";

import "./report-a4.css";

const A4_LABELS = {
  portrait: "A4 세로 210 × 297 mm",
  landscape: "A4 가로 297 × 210 mm",
};

function orientationOf(value) {
  return value === "landscape" ? "landscape" : "portrait";
}

function blockGridStyle(block) {
  const width = Math.min(12, Math.max(1, Math.round(block.w ?? block.columns ?? 12)));
  const column = Math.min(12 - width, Math.max(0, Math.round(block.x ?? 0)));
  const row = Math.max(0, Math.round(block.y ?? 0));
  const height = Math.max(1, Math.round(block.h ?? 1));
  return {
    gridColumn: `${column + 1} / span ${width}`,
    gridRow: `${row + 1} / span ${height}`,
  };
}

function ScaledPage({
  mode,
  orientation,
  page,
  pageIndex,
  pageCount,
  renderBlock,
  renderHeader,
  renderFooter,
  renderGridOverlay,
  gridClassName,
  getGridRef,
}) {
  const viewportRef = useRef(null);
  const pageRef = useRef(null);
  const [frame, setFrame] = useState(null);
  const pageNumber = pageIndex + 1;
  const context = { mode, orientation, page, pageIndex, pageNumber, pageCount };

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const pageElement = pageRef.current;
    if (!viewport || !pageElement) return undefined;

    const resize = () => {
      const naturalWidth = pageElement.offsetWidth;
      const naturalHeight = pageElement.offsetHeight;
      if (!naturalWidth || !naturalHeight) return;
      const scale = Math.min(1, viewport.clientWidth / naturalWidth);
      const next = {
        scale,
        width: naturalWidth * scale,
        height: naturalHeight * scale,
      };
      setFrame((current) => (
        current
        && Math.abs(current.width - next.width) < 0.5
        && Math.abs(current.height - next.height) < 0.5
          ? current
          : next
      ));
    };

    resize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }
    const observer = new ResizeObserver(resize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [orientation]);

  const header = renderHeader ? renderHeader(context) : page.header;
  const footer = renderFooter ? renderFooter(context) : page.footer;
  const pageLabel = page.ariaLabel || `보고서 ${pageNumber}/${pageCount}페이지, ${A4_LABELS[orientation]}`;

  return (
    <div className="answer-report-page-viewport" ref={viewportRef}>
      {mode === "editor" && (
        <div
          className="answer-report-page-chrome"
          data-report-editor-chrome="true"
          style={frame ? { inlineSize: frame.width } : undefined}
          aria-hidden="true"
        >
          <span>{String(pageNumber).padStart(2, "0")} 페이지</span>
          <span>{A4_LABELS[orientation]}</span>
        </div>
      )}
      <div
        className={`answer-report-page-frame answer-report-page-frame--${orientation}`}
        style={frame ? { inlineSize: frame.width, blockSize: frame.height } : undefined}
      >
        <article
          ref={pageRef}
          className={`answer-report-page answer-report-page--${orientation}`}
          data-orientation={orientation}
          role="region"
          aria-label={pageLabel}
          style={frame ? { transform: `scale(${frame.scale})` } : undefined}
        >
          <header className="answer-report-page__header">{header}</header>
          <div
            ref={(element) => getGridRef?.(element, context)}
            className={`answer-report-page__grid ${gridClassName || ""}`.trim()}
          >
            {renderGridOverlay?.(context)}
            {(page.blocks || []).map((block, blockIndex) => (
              <section
                className="answer-report-page__block"
                data-report-block-id={block.id}
                style={blockGridStyle(block)}
                key={block.id || blockIndex}
              >
                {renderBlock(block, { ...context, blockIndex })}
              </section>
            ))}
          </div>
          <footer className="answer-report-page__footer">
            <div className="answer-report-page__footer-slot">{footer}</div>
            <span className="answer-report-page__folio" aria-label={`${pageNumber}/${pageCount}페이지`}>
              {String(pageNumber).padStart(2, "0")} / {String(pageCount).padStart(2, "0")}
            </span>
          </footer>
        </article>
      </div>
    </div>
  );
}

/**
 * A physical A4 surface for editable HTML reports and print-identical previews.
 * Each page may provide `header`, `footer`, `orientation`, and positioned `blocks`.
 */
export function ReportPageCanvas({
  pages = [],
  orientation: documentOrientation = "portrait",
  mode: requestedMode = "editor",
  renderBlock,
  renderHeader,
  renderFooter,
  renderGridOverlay,
  gridClassName = "",
  getGridRef,
  ariaLabel = "보고서 페이지",
  className = "",
}) {
  const mode = requestedMode === "preview" ? "preview" : "editor";
  if (typeof renderBlock !== "function") {
    throw new TypeError("ReportPageCanvas requires a renderBlock callback.");
  }

  return (
    <section
      className={`answer-report-canvas answer-report-canvas--${mode} ${className}`.trim()}
      data-report-mode={mode}
      aria-label={ariaLabel}
    >
      {pages.map((page, pageIndex) => {
        const orientation = orientationOf(page.orientation ?? documentOrientation);
        return (
          <ScaledPage
            mode={mode}
            orientation={orientation}
            page={page}
            pageIndex={pageIndex}
            pageCount={pages.length}
            renderBlock={renderBlock}
            renderHeader={renderHeader}
            renderFooter={renderFooter}
            renderGridOverlay={renderGridOverlay}
            gridClassName={gridClassName}
            getGridRef={getGridRef}
            key={page.id || pageIndex}
          />
        );
      })}
    </section>
  );
}
