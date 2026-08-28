from app.services.rag_gateway import RagGatewayTool


def test_two_document_follow_up_preserves_comparison_context() -> None:
    assert RagGatewayTool.selected_document_limit(
        "IMMEDIATE_ACTION",
        ("MANUAL-FACILITY", "MANUAL-SAFETY"),
    ) == 2
    assert RagGatewayTool.selected_document_limit(
        "IMMEDIATE_ACTION",
        ("MANUAL-FACILITY",),
    ) == 1
