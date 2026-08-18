/** 큰 표를 A4 미리보기 행으로 정직하게 축약하는 순수 helper 모듈이다. */
/** A4 미리보기에서 표 header와 함께 안전하게 표시할 최대 행 수다. */ export const REPORT_TABLE_ROW_LIMIT = 12;

/** 첫·끝 행을 보존하고 중간 행을 전체 결과에 균등 배분하며 원본 행 번호를 함께 반환한다. */
export function sampleReportTableRows(rows, limit = REPORT_TABLE_ROW_LIMIT) {
  if (!Array.isArray(rows)) return [];
  if (!Number.isInteger(limit) || limit < 1) {
    throw new RangeError("report table row limit must be a positive integer");
  }
  if (rows.length <= limit) {
    return rows.map((row, sourceIndex) => ({ row, sourceIndex }));
  }
  if (limit === 1) return [{ row: rows[0], sourceIndex: 0 }];

  const lastIndex = rows.length - 1;
  return Array.from({ length: limit }, (_, position) => {
    const sourceIndex = Math.floor((position * lastIndex) / (limit - 1));
    return { row: rows[sourceIndex], sourceIndex };
  });
}
