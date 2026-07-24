"""Framework 독립 분석 순수 로직 패키지.

DSG v2.0 §11(품질 Gate), §13(scenario manifest) 기반의
결정론적 품질 판정·KPI 계산·이상 감지·근거 수집 순수 함수를 제공한다.

모든 모듈은 DB/IO/네트워크 접근 없이 순수 함수만 노출한다.

Modules:
    quality: 품질 게이트 결정론적 판정
    metrics: KPI 계산 (NEGATIVE 감성 비율)
    detection: 이상 감지 결정론적 규칙
    evidence: 근거 수집/포맷

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
"""

from analysis.detection import detect_anomalies
from analysis.evidence import build_evidence
from analysis.metrics import calculate_kpis
from analysis.quality import run_quality_gate

__all__ = [
    "run_quality_gate",
    "calculate_kpis",
    "detect_anomalies",
    "build_evidence",
]
