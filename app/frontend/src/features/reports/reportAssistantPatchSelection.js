/** Report Assistant 변경안의 의존성 선택과 페이지 그룹화를 결정론적으로 계산한다. */
function operationIndexMap(items) {
  return new Map(items.map((item) => [item.index, item]));
}

function dependencyIndexes(item) {
  return Array.isArray(item?.depends_on_indexes) ? item.depends_on_indexes : [];
}

/** 서버가 만든 backward-only dependency DAG를 따라 승인 선택의 선행 작업을 닫는다. */
export function closeReportPatchSelection(items, indexes) {
  const itemByIndex = operationIndexMap(items);
  const selected = new Set(indexes.filter((index) => itemByIndex.has(index)));
  const pending = [...selected];
  while (pending.length) {
    const index = pending.pop();
    for (const dependencyIndex of dependencyIndexes(itemByIndex.get(index))) {
      if (!itemByIndex.has(dependencyIndex) || selected.has(dependencyIndex)) continue;
      selected.add(dependencyIndex);
      pending.push(dependencyIndex);
    }
  }
  return [...selected].sort((left, right) => left - right);
}

/** 선행 작업을 해제하면 그것 없이는 적용할 수 없는 모든 후속 작업도 함께 해제한다. */
export function removeReportPatchSelection(items, indexes, removedIndex) {
  const selected = new Set(indexes.filter((index) => index !== removedIndex));
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of items) {
      if (!selected.has(item.index)) continue;
      if (dependencyIndexes(item).some((dependencyIndex) => !selected.has(dependencyIndex))) {
        selected.delete(item.index);
        changed = true;
      }
    }
  }
  return [...selected].sort((left, right) => left - right);
}

/** 승인 목록을 보고서 공통 변경과 실제 페이지 순서로 묶는다. */
export function groupReportPatchItemsByPage(items) {
  const groups = new Map();
  for (const item of items) {
    const pageIndex = Number.isInteger(item.page_index) && item.page_index > 0
      ? item.page_index
      : null;
    const key = pageIndex == null ? "report" : `page-${pageIndex}`;
    if (!groups.has(key)) groups.set(key, { key, pageIndex, items: [] });
    groups.get(key).items.push(item);
  }
  const orderedGroups = [...groups.values()];
  for (const group of orderedGroups) {
    group.items.sort((left, right) => left.index - right.index);
  }
  return orderedGroups.sort((left, right) => {
    if (left.pageIndex == null) return -1;
    if (right.pageIndex == null) return 1;
    return left.pageIndex - right.pageIndex;
  });
}
