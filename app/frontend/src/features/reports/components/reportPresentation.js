/** 보고서 UI의 일반 template·pagination·표시 helper 계약을 제공하는 모듈이다. */
import { Columns2, FileBarChart, Heading2, List, Quote, Sparkles, Table2, Type } from "lucide-react";

import { compactDraftLayout, restoreDraftLayout } from "../../../contracts/report";
import {
  artifactMetricCards,
  frontendTextBlockLayout,
} from "../reportDraftV2";
import { isCurrencyMetricUnit } from "../reportCurrency";
import { metricDisplayLabel } from "../../../utils/presentation";

/** 보고서 컴포넌트가 공유하는 표시·pagination·키보드 순수 계약이다. */
export { reportEvidenceReady } from "../reportArtifactEvidence";

/** 실행 내역 점진 표시 크기다. */ export const REPORT_RUN_PAGE_SIZE = 10;

/** 특정 지표와 무관한 사용자 작성용 text block template 집합이다. */ export const REPORT_TEMPLATES = [
  {
    id: "text",
    title: "텍스트",
    description: "문단·목록·Markdown",
    icon: Type,
    blockTitle: "새 텍스트",
    content: "새 문단을 작성하세요.",
    w: 8,
    h: 3,
  },
  {
    id: "section",
    title: "섹션",
    description: "소제목이 있는 문단",
    icon: Heading2,
    blockTitle: "새 섹션",
    content: "## 새 섹션\n섹션 내용을 입력하세요.",
    w: 8,
    h: 3,
  },
  {
    id: "executive",
    title: "경영진 요약",
    description: "결론과 비즈니스 영향",
    icon: Sparkles,
    blockTitle: "경영진 요약",
    content: "## 핵심 결론\n가장 중요한 결과를 한 문장으로 정리하세요.\n\n## 비즈니스 영향\n의사결정에 미치는 영향을 작성하세요.",
    w: 8,
    h: 5,
  },
  {
    id: "monthly-report",
    title: "월간 경영 보고서",
    description: "월간 성과와 변동 요인 구성",
    icon: FileBarChart,
    blockTitle: "월간 경영 보고서",
    content: "## 월간 경영 보고서\n\n핵심 성과와 전월 대비 변동 요인을 정리하세요.",
    w: 8,
    h: 3,
  },
  {
    id: "hotel-sales-report",
    title: "호텔 매출 보고서",
    description: "객실·F&B·연회 매출 구성",
    icon: FileBarChart,
    blockTitle: "호텔 매출 보고서",
    content: "## 호텔 매출 보고서\n\n객실·F&B·연회 부문의 주요 실적을 정리하세요.",
    w: 8,
    h: 3,
  },
  {
    id: "kpi",
    title: "핵심 지표",
    description: "수치와 의미를 한눈에",
    icon: Columns2,
    blockTitle: "핵심 지표",
    content: "| 지표 | 값 | 의미 |\n| --- | ---: | --- |\n| 핵심 지표 | 값 입력 | 의미를 작성하세요 |",
    w: 6,
    h: 5,
  },
  {
    id: "insight",
    title: "핵심 인사이트",
    description: "해석을 강조하는 콜아웃",
    icon: Quote,
    blockTitle: "핵심 인사이트",
    content: "> 데이터가 말하는 핵심 변화와 그 의미를 간결하게 작성하세요.",
    w: 6,
    h: 3,
  },
  {
    id: "actions",
    title: "권고 사항",
    description: "실행 항목과 후속 조치",
    icon: List,
    blockTitle: "권고 사항",
    content: "- [ ] 우선 실행할 조치\n- [ ] 담당자와 기한 확인\n- [ ] 후속 지표 모니터링",
    w: 6,
    h: 3,
  },
];

/** governed artifact의 table/chart view를 삽입하는 일반 template 집합이다. */ export const ARTIFACT_TEMPLATES = [
  {
    id: "artifact-table",
    title: "표 보기만",
    description: "Artifact의 상세 행만 삽입",
    icon: Table2,
    w: 6,
    h: 5,
  },
  {
    id: "artifact-chart",
    title: "차트 보기만",
    description: "Artifact의 차트만 삽입",
    icon: FileBarChart,
    w: 8,
    h: 7,
  },
];

/** governed artifact 전체 view를 삽입하는 일반 template이다. */ export const WHOLE_ARTIFACT_TEMPLATE = {
  id: "artifact-whole",
  title: "분석 결과",
  description: "요약·핵심 지표·차트·표를 한 블록으로",
  icon: FileBarChart,
};

/** renderer가 지원하는 차트 타입과 표시 라벨 계약이다. */ export const REPORT_CHART_OPTIONS = [
  ["bar", "세로 막대"],
  ["horizontal-bar", "가로 막대"],
  ["line", "선"],
  ["area", "영역"],
  ["stacked-bar", "누적 막대"],
  ["donut", "도넛"],
  ["pie", "원형"],
];

/** template ID의 O(1) 조회를 위한 immutable-source index다. */ export const REPORT_TEMPLATE_MAP = new Map(
  [...REPORT_TEMPLATES, ...ARTIFACT_TEMPLATES].map((template) => [template.id, template]),
);

/** 방향별 편집 grid row 한도다. */ export const REPORT_PAGE_ROWS = { landscape: 18, portrait: 30 };

/** canonical result field와 정확히 일치하는 governed metric 근거를 찾는다. */
export function artifactMetric(artifact, resultField) {
  return artifact?.evidence?.metrics?.find((metric) => metric.result_field === resultField);
}

function humanizeColumnIdentifier(column) {
  const words = String(column ?? "")
    .trim()
    .split("_")
    .flatMap((part) => part.split("-"))
    .flatMap((part) => part.split(" "))
    .filter(Boolean);
  return words.join(" ") || "구분";
}

/** governed metric label을 우선하고 없으면 canonical column을 일반 표시형으로만 바꾼다. */
export function reportColumnLabel(artifact, column) {
  const governedMetric = artifactMetric(artifact, column);
  const governedLabel = governedMetric ? metricDisplayLabel(governedMetric) : "";
  return typeof governedLabel === "string" && governedLabel.trim()
    ? governedLabel.trim()
    : humanizeColumnIdentifier(column);
}

/** 통화 unit이 명시된 metric의 표·카드 원본 수치만 수집한다. */
export function artifactCurrencyValues(artifact) {
  const fields = new Set(
    (artifact?.evidence?.metrics ?? [])
      .filter((metric) => isCurrencyMetricUnit(metric.unit))
      .map((metric) => metric.result_field),
  );
  const tableValues = (artifact?.table?.rows ?? []).flatMap((row) => (
    [...fields].map((field) => row[field])
  ));
  const cardValues = artifactMetricCards(artifact)
    .filter((metric) => isCurrencyMetricUnit(metric.unit))
    .map((metric) => metric.value);
  return [...tableValues, ...cardValues];
}

/** text 외 블록의 JSON 설정을 객체로 읽고 손상 값은 빈 설정으로 닫는다. */
export function blockSettings(block) {
  if (block.type === "text" || !block.content) return {};
  try {
    const parsed = JSON.parse(block.content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/** grid row를 A4 방향 한도에 맞춰 안정적으로 페이지로 나눈다. */
export function paginateReportBlocks(blocks, orientation, documentId = "report") {
  const rowLimit = REPORT_PAGE_ROWS[orientation] || REPORT_PAGE_ROWS.landscape;
  const rows = [...blocks]
    .sort((left, right) => (
      (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0)
    ))
    .reduce((groups, block) => {
      const sourceY = block.y ?? 0;
      const current = groups.at(-1);
      if (current?.sourceY === sourceY) current.blocks.push(block);
      else groups.push({ sourceY, blocks: [block] });
      return groups;
    }, []);
  const pages = [];
  let page = null;
  let cursorY = 0;
  const startPage = (sourceY = 0) => {
    page = {
      id: `${documentId}:page:${pages.length + 1}`,
      index: pages.length,
      orientation,
      offsetY: sourceY,
      blocks: [],
    };
    pages.push(page);
    cursorY = 0;
  };
  for (const row of rows) {
    if (row.blocks.some((block) => block.type === "page_break")) {
      if (!page) startPage(row.sourceY);
      startPage(row.sourceY + 1);
      continue;
    }
    const height = Math.min(
      rowLimit,
      Math.max(...row.blocks.map((block) => block.h ?? 1)),
    );
    if (!page || (page.blocks.length && cursorY + height > rowLimit)) {
      startPage(row.sourceY);
    }
    for (const sourceBlock of row.blocks) {
      page.blocks.push({ ...sourceBlock, y: cursorY, h: height, sourceBlock });
    }
    cursorY += height;
  }
  if (!pages.length) startPage(0);
  return pages;
}

/** text 높이를 다시 계산한 뒤 복원·compact해 editor grid를 준비한다. */
export function prepareEditorLayout(blocks, orientation = "landscape") {
  return compactDraftLayout(
    restoreDraftLayout(blocks).map((block) => (
      block.type === "text"
        ? { ...block, h: frontendTextBlockLayout(block, orientation).height }
        : block
    )),
  );
}

/** dirty 비교에 필요한 block 필드만 canonical JSON signature로 만든다. */
export function draftLayoutSignature(blocks) {
  return JSON.stringify(
    compactDraftLayout(restoreDraftLayout(blocks)).map((block) => ({
      id: block.id,
      title: block.title,
      artifactId: block.artifactId,
      queryId: block.queryId,
      type: block.type,
      content: block.content ?? "",
      x: block.x,
      y: block.y,
      w: block.w,
      h: block.h,
    })),
  );
}

/** arrow key를 drag sensor 좌표 이동으로 변환하고 다른 키는 처리하지 않는다. */
export function reportKeyboardCoordinates(event, { currentCoordinates }) {
  const movement = {
    ArrowRight: [80, 0],
    ArrowLeft: [-80, 0],
    ArrowDown: [0, 72],
    ArrowUp: [0, -72],
  }[event.code];
  if (!movement) return undefined;
  event.preventDefault();
  return {
    x: currentCoordinates.x + movement[0],
    y: currentCoordinates.y + movement[1],
  };
}
