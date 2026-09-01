import assert from "node:assert/strict";
import test from "node:test";

import { compactReportArtifactOptions } from "../../app/frontend/src/features/reports/reportArtifactLibrary.js";

const baseArtifact = {
  summary: "월별 매출",
  metrics: [{ metric_id: "revenue", label: "객실 매출", value: 30, unit: "원" }],
  table: { columns: ["month", "revenue"], rows: [{ month: "2026-05-01", revenue: 30 }] },
  chart: { x_field: "month", y_fields: ["revenue"], chart_type: "bar" },
  evidence: { period: { start: "2026-05-01", end_exclusive: "2026-06-01" }, sources: [] },
};

test("artifact library groups only exact duplicate presentation content", () => {
  const options = [
    { artifactId: "latest", title: "객실 매출" },
    { artifactId: "older", title: "객실 매출" },
    { artifactId: "different", title: "객실 매출" },
  ];
  const artifacts = {
    latest: baseArtifact,
    older: structuredClone(baseArtifact),
    different: {
      ...structuredClone(baseArtifact),
      table: { ...baseArtifact.table, rows: [{ month: "2026-05-01", revenue: 31 }] },
    },
  };
  const compacted = compactReportArtifactOptions(options, artifacts);
  assert.equal(compacted.length, 2);
  assert.equal(compacted[0].artifactId, "latest");
  assert.equal(compacted[0].duplicateCount, 2);
  assert.equal(compacted[1].artifactId, "different");
});

test("artifact library keeps the selected duplicate as the representative", () => {
  const options = [
    { artifactId: "latest", title: "객실 매출" },
    { artifactId: "selected", title: "객실 매출" },
  ];
  const artifacts = { latest: baseArtifact, selected: structuredClone(baseArtifact) };
  const [representative] = compactReportArtifactOptions(options, artifacts, "selected");
  assert.equal(representative.artifactId, "selected");
  assert.equal(representative.duplicateCount, 2);
});
