/** A4 편집 영역의 clipping과 무관하게 viewport 안에 배치되는 편집용 floating panel이다. */
import { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

const VIEWPORT_MARGIN = 12;
const PANEL_GAP = 6;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

/** anchor 주변의 여유 공간을 계산해 아래/위 배치와 viewport collision을 처리한다. */
export function ReportFloatingPanel({
  anchorRef,
  panelRef,
  open,
  className,
  children,
  onRequestClose,
  ...panelProps
}) {
  const [position, setPosition] = useState(null);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return undefined;
    }

    const updatePosition = () => {
      const anchor = anchorRef.current;
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      const anchorRect = anchor.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      const spaceBelow = window.innerHeight - anchorRect.bottom - PANEL_GAP - VIEWPORT_MARGIN;
      const spaceAbove = anchorRect.top - PANEL_GAP - VIEWPORT_MARGIN;
      const placeBelow = spaceBelow >= Math.min(panelRect.height, 260) || spaceBelow >= spaceAbove;
      const availableHeight = Math.max(96, placeBelow ? spaceBelow : spaceAbove);
      const renderedHeight = Math.min(panelRect.height, availableHeight);
      const top = placeBelow
        ? clamp(anchorRect.bottom + PANEL_GAP, VIEWPORT_MARGIN, window.innerHeight - renderedHeight - VIEWPORT_MARGIN)
        : clamp(anchorRect.top - PANEL_GAP - renderedHeight, VIEWPORT_MARGIN, window.innerHeight - renderedHeight - VIEWPORT_MARGIN);
      const renderedWidth = Math.min(panelRect.width, window.innerWidth - VIEWPORT_MARGIN * 2);
      const left = clamp(
        anchorRect.right - renderedWidth,
        VIEWPORT_MARGIN,
        window.innerWidth - renderedWidth - VIEWPORT_MARGIN,
      );
      setPosition({ top, left, maxHeight: availableHeight });
    };
    const closeFromOutside = (event) => {
      if (anchorRef.current?.contains(event.target) || panelRef.current?.contains(event.target)) return;
      onRequestClose?.();
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    document.addEventListener("pointerdown", closeFromOutside, true);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updatePosition);
    if (anchorRef.current) resizeObserver?.observe(anchorRef.current);
    if (panelRef.current) resizeObserver?.observe(panelRef.current);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      document.removeEventListener("pointerdown", closeFromOutside, true);
      resizeObserver?.disconnect();
    };
  }, [anchorRef, onRequestClose, open, panelRef]);

  if (!open || typeof document === "undefined") return null;
  const anchor = anchorRef.current;
  const themeClass = anchor?.closest(".theme-light") ? "theme-light" : "theme-dark";
  const builderVersion = anchor?.closest('[data-report-builder="v2"]') ? "v2" : undefined;
  return createPortal(
    <div className={`report-editor-portal ${themeClass}`}>
      <div data-report-builder={builderVersion}>
        <div
          {...panelProps}
          ref={panelRef}
          className={`${className} report-editor-floating-panel`}
          style={{
            position: "fixed",
            zIndex: 1000,
            top: position?.top ?? 0,
            left: position?.left ?? 0,
            right: "auto",
            bottom: "auto",
            maxHeight: position?.maxHeight ?? "calc(100dvh - 24px)",
            overflow: "auto",
            visibility: position ? "visible" : "hidden",
            pointerEvents: "auto",
          }}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
