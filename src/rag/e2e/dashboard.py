"""RAG 내부 상태와 선택적 Analysis·ML URL 도달성을 조회하는 E2E 상태 화면을 제공한다."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


class E2EDashboard:
    """주입된 RAG 애플리케이션과 외부 런타임의 연결 상태를 대시보드 형식으로 집계한다."""

    def __init__(self, rag_application: Any) -> None:
        self._rag_application = rag_application

    def runtime_status(self) -> dict[str, Any]:
        """RAG·Analysis·ML별 설정 여부와 실제 도달성 진단을 이름별 사전으로 반환한다."""

        return {
            "rag": self._probe_rag(),
            "analysis": self._probe_url(
                os.getenv("ANALYSIS_DASHBOARD_URL", "http://127.0.0.1:18000/openapi.json")
            ),
            "ml": self._probe_optional_url(os.getenv("ML_DASHBOARD_URL")),
        }

    def _probe_rag(self) -> dict[str, Any]:
        try:
            return {"configured": True, "reachable": True, "details": self._rag_application.status()}
        except Exception as error:
            return {"configured": True, "reachable": False, "error": str(error)}

    @staticmethod
    def _probe_url(url: str) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(3.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.get(url, headers={"Accept": "application/json"})
            return {
                "configured": True,
                "reachable": 200 <= response.status_code < 300,
                "url": url,
                "status_code": response.status_code,
                "redirect_blocked": response.is_redirect,
            }
        except httpx.RequestError as error:
            return {"configured": True, "reachable": False, "url": url, "error": str(error)}

    @classmethod
    def _probe_optional_url(cls, url: str | None) -> dict[str, Any]:
        if not url:
            return {"configured": False, "reachable": False, "reason": "ML_DASHBOARD_URL is not configured"}
        return cls._probe_url(url)

    @staticmethod
    def html() -> str:
        """런타임 상태 API를 새로고침해 연결·실패·미설정을 구분하는 독립 HTML을 반환한다."""

        return """<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Answervice E2E 검증</title><style>body{margin:0;background:#f3f6fa;color:#172033;font:15px 'Malgun Gothic',sans-serif}.wrap{max-width:960px;margin:auto;padding:38px 22px}h1{margin:0;font-size:31px}.sub{color:#5c6b80;margin:10px 0 28px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.card{background:#fff;border:1px solid #dbe3ed;border-radius:14px;padding:19px;box-shadow:0 4px 12px #203b5a0d}.label{font-size:12px;color:#66758b;font-weight:700}.state{font-size:24px;font-weight:800;margin:8px 0}.ok{color:#15803d}.bad{color:#b42318}.wait{color:#a16207}pre{white-space:pre-wrap;word-break:break-word;background:#0f1f33;color:#dcecff;border-radius:10px;padding:14px;min-height:190px}.actions{display:flex;gap:10px;margin:23px 0}button,a{border:0;border-radius:8px;padding:10px 14px;font-weight:700;text-decoration:none;cursor:pointer}button{background:#17395c;color:#fff}a{background:#e9f1fa;color:#17395c}.note{background:#fff8e8;border-left:4px solid #d69200;padding:14px;border-radius:6px}</style></head><body><main class=\"wrap\"><h1>RAG·ML·Analysis Core E2E 검증</h1><p class=\"sub\">표시 값은 브라우저가 아닌 현재 RAG 서버가 실제 런타임을 조회한 결과입니다.</p><div class=\"grid\" id=\"cards\"></div><div class=\"actions\"><button onclick=\"load()\">상태 새로고침</button><a href=\"/docs\">RAG API 명세</a><a href=\"http://127.0.0.1:18000/docs\" target=\"_blank\">Analysis Core 명세</a></div><div class=\"note\">ML이 미설정 또는 비승인 상태이면 E2E는 통과로 표시되지 않습니다. RAG 검색·답변은 서명된 Gateway 요청으로만 실행됩니다.</div><h2>실제 응답</h2><pre id=\"raw\">조회 중...</pre></main><script>const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));function card(n,v){const state=v.reachable?'연결됨':v.configured?'연결 실패':'미설정';const cls=v.reachable?'ok':v.configured?'bad':'wait';return `<article class=\"card\"><div class=\"label\">${esc(n)}</div><div class=\"state ${cls}\">${state}</div><div>${esc(v.url||v.reason||'RAG 서버 내부 상태')}</div></article>`}async function load(){const raw=document.getElementById('raw'),cards=document.getElementById('cards');raw.textContent='조회 중...';try{const r=await fetch('/v1/e2e/runtime-status',{cache:'no-store'});const data=await r.json();cards.innerHTML=Object.entries(data).map(([n,v])=>card(n,v)).join('');raw.textContent=JSON.stringify(data,null,2)}catch(e){raw.textContent='상태 조회 실패: '+e}}load();</script></body></html>"""
