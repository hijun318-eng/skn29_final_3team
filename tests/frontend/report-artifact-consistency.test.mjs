import assert from "node:assert/strict";

import {
  REPORT_TABLE_ROW_LIMIT,
  sampleReportTableRows,
} from "../../app/frontend/src/features/reports/reportTableRows.js";
import { reportSources, sourceSection } from "./report-source-contract.mjs";

const rows = Array.from({ length: 101 }, (_, sourceIndex) => ({ sourceIndex }));
const sampled = sampleReportTableRows(rows);
const expectedIndexes = Array.from(
  { length: REPORT_TABLE_ROW_LIMIT },
  (_, position) => Math.floor((position * (rows.length - 1)) / (REPORT_TABLE_ROW_LIMIT - 1)),
);
assert.equal(REPORT_TABLE_ROW_LIMIT, 12);
assert.deepEqual(sampled.map(({ sourceIndex }) => sourceIndex), expectedIndexes);
assert.deepEqual(sampled.map(({ row }) => row.sourceIndex), expectedIndexes);
assert.equal(sampled[0].row, rows[0]);
assert.equal(sampled.at(-1).row, rows.at(-1));
assert.deepEqual(sampleReportTableRows(rows.slice(0, 3)).map(({ sourceIndex }) => sourceIndex), [0, 1, 2]);
assert.deepEqual(sampleReportTableRows(rows, 1), [{ row: rows[0], sourceIndex: 0 }]);
assert.throws(() => sampleReportTableRows(rows, 0), RangeError);

assert.match(reportSources.artifactContent, /const visibleRows = sampleReportTableRows\(rows\)/);
assert.match(reportSources.artifactContent, /visibleRows\.map\(\(\{ row, sourceIndex \}\)/);
assert.match(
  reportSources.artifactContent,
  /전체 \{rows\.length\}행 중 \{visibleRows\.length\}개 대표 행을 첫·마지막 포함 균등 표시합니다/,
);
assert.match(reportSources.artifactContent, /전체 값은 원본 분석 결과에서 확인할 수 있습니다/);

const loadSource = sourceSection(reportSources.artifacts, "const loadArtifacts", "const retryArtifact");
assert.match(loadSource, /const generation = loadGenerationRef\.current \+ 1/);
assert.match(loadSource, /const isCurrentLoad = \(\) => loadGenerationRef\.current === generation/);
assert.ok(
  (loadSource.match(/if \(!isCurrentLoad\(\)\) return false/g) ?? []).length >= 2,
  "each awaited load phase must stop when a newer report load owns the hook",
);
assert.ok(
  (loadSource.match(/if \(isCurrentLoad\(\)\) \{\s*setArtifactStates/g) ?? []).length >= 2,
  "per-artifact success and failure updates must be generation guarded",
);
const finalGuard = loadSource.lastIndexOf("if (!isCurrentLoad()) return false");
const finalArtifactCommit = loadSource.indexOf("setArtifacts(artifactMap)");
const hydrationCallback = loadSource.indexOf("onHydrated(artifactMap, definition)");
assert.ok(finalGuard >= 0 && finalGuard < finalArtifactCommit && finalArtifactCommit < hydrationCallback);
assert.match(
  reportSources.artifacts,
  /useEffect\(\(\) => \(\) => \{\s*loadGenerationRef\.current \+= 1/,
  "unmount must invalidate all outstanding loads",
);
const retrySource = sourceSection(reportSources.artifacts, "const retryArtifact", "const artifactOptions");
assert.match(retrySource, /const generation = loadGenerationRef\.current/);
assert.match(retrySource, /if \(!isCurrentLoad\(\)\) return/);

console.log("frontend report artifact consistency tests passed");
