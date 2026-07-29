"""SensePlace 공개 API URL 패턴.

AIC v2.0 기준 7개 엔드포인트를 /api/v1/ prefix로 등록한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §3
"""

from django.urls import path

from senseplace.api import views

app_name = "senseplace_api"

urlpatterns = [
    # 인증
    path("auth/login/", views.api_login, name="api-login"),
    path("auth/logout/", views.api_logout, name="api-logout"),
    # VOC
    path("vocs/", views.voc_list, name="voc-list"),
    path("vocs/<str:voc_id>/", views.voc_detail, name="voc-detail"),
    # Job
    path("jobs/", views.job_create, name="job-create"),
    path("jobs/<uuid:job_id>/", views.job_detail, name="job-detail"),
    # Report
    path("reports/", views.report_list, name="report-list"),
    # Connection
    path("connections/", views.connection_list, name="connection-list"),
    # Catalog
    path("tools/", views.tool_list, name="tool-list"),
    path("data-products/", views.data_product_list, name="data-product-list"),
    # Customer 360
    path("customers/", views.customer_list, name="customer-list"),
    # Agent
    path("agent/workflow/", views.agent_workflow, name="agent-workflow"),
]
