"""SensePlace 앱 URL 루트.

인증 API를 하위 패턴으로 포함한다.
"""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("senseplace.auth.urls")),
]
