"""SensePlace 앱 URL 루트.

- /api/auth/  : 기존 인증 API (하위 호환)
- /api/v1/    : 공개 API 7개 (AIC v2.0)
"""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("senseplace.auth.urls")),
    path("v1/", include("senseplace.api.urls")),
]
