"""Guarded Text-to-SQL Pipeline — 기획서 기반 결정론적 Pipeline 구조.

DataHub Core + Trino + sLLM 없이 구조와 계약만 갖춘 stub 구현이다.
각 컴포넌트는 기획서 §7-9의 계약을 Pydantic 모델로 정의한다.
"""
