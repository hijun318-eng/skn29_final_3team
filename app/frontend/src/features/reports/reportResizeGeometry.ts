/** 보고서 block의 8방향 grid resize를 DOM과 분리해 계산하는 순수 geometry 모듈이다. */

export type ReportResizeDirection = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

export interface ReportResizeFrame {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export interface ReportResizeLimits {
  readonly minimumWidth: number;
  readonly minimumHeight: number;
  readonly maximumHeight: number;
}

const clamp = (value: number, minimum: number, maximum: number): number => (
  Math.max(minimum, Math.min(maximum, value))
);

/** 반대편 edge를 고정한 채 상·하·좌·우·모서리 resize 결과를 12열 grid 범위로 제한한다. */
export function resizeReportFrame(
  frame: ReportResizeFrame,
  direction: ReportResizeDirection,
  deltaX: number,
  deltaY: number,
  limits: ReportResizeLimits,
): ReportResizeFrame {
  const right = frame.x + frame.w;
  const bottom = frame.y + frame.h;
  let x = frame.x;
  let y = frame.y;
  let w = frame.w;
  let h = frame.h;

  if (direction.includes("w")) {
    x = clamp(frame.x + deltaX, 0, right - limits.minimumWidth);
    w = right - x;
  } else if (direction.includes("e")) {
    w = clamp(frame.w + deltaX, limits.minimumWidth, 12 - frame.x);
  }

  if (direction.includes("n")) {
    y = clamp(
      frame.y + deltaY,
      Math.max(0, bottom - limits.maximumHeight),
      bottom - limits.minimumHeight,
    );
    h = bottom - y;
  } else if (direction.includes("s")) {
    h = clamp(frame.h + deltaY, limits.minimumHeight, limits.maximumHeight);
  }

  return { x, y, w, h };
}
