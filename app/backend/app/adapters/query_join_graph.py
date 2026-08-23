"""승인 release가 공표한 join graph를 해석하고 asset 사이의 연결 경로만 계산하는 순수 그래프 모듈이다.

권위 있는 입력은 ``GovernedDataset.join_graph``다. 이 모듈은 DataHub·Trino I/O를 수행하지 않고
entitlement도 판단하지 않는다. 권한 검증은 호출자인 ``query_governance``가 확장 결과 전체에 적용한다.
"""

from __future__ import annotations

from collections import deque


def metric_dependencies(datasets):
    """dataset 자신의 FQN과 그 metric이 차원으로 참조하는 asset FQN 집합을 합쳐 반환한다.

    metric이 다른 asset의 차원을 요구하면 그 asset도 확장 후보에 포함되어야 join 경로가
    끊기지 않는다. 반환 집합은 후보일 뿐이며 실제 편입 여부는 호출자가 join 경로로 판정한다.
    """

    result = {item.fqn for item in datasets}
    for dataset in datasets:
        for metric in dataset.metrics:
            result.update(
                str(item["asset_fqn"])
                for item in metric.get("dimensions", ())
            )
    return result


def other_endpoints(edge, fqn):
    """주어진 edge에서 ``fqn``의 반대편 asset을 반환하고, edge가 ``fqn``과 무관하면 빈 tuple을 반환한다."""

    if edge.left == fqn:
        return (edge.right,)
    if edge.right == fqn:
        return (edge.left,)
    return ()


def connect_fqns(selected, edges, anchor=None):
    """선택된 asset들을 승인된 edge만으로 잇는 최소 경유 asset을 포함한 집합을 반환한다.

    ``anchor``가 선택 집합 안에 있으면 경로 기준점으로 사용하고, 없으면 정렬 첫 원소를
    사용해 결과를 결정적으로 만든다. 경로가 없는 asset은 조용히 이어붙이지 않고 그대로 둔다.
    """

    selected = set(selected)
    if len(selected) < 2:
        return selected
    root = anchor if anchor in selected else sorted(selected)[0]
    result = {root}
    for target in sorted(selected - {root}):
        path = shortest_path(root, target, edges)
        if path:
            result.update(path)
    return result


def shortest_path(start, target, edges):
    """승인된 edge만 따라 ``start``에서 ``target``까지의 최단 경로 tuple을 반환한다.

    경로가 없으면 빈 tuple을 반환한다. 호출자는 이 빈 값을 "연결 불가"로 해석해야 하며
    임의 join으로 대체해서는 안 된다.
    """

    queue = deque([(start, (start,))])
    seen = {start}
    while queue:
        current, path = queue.popleft()
        for edge in edges:
            for neighbor in other_endpoints(edge, current):
                if neighbor == target:
                    return (*path, neighbor)
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, (*path, neighbor)))
    return ()
