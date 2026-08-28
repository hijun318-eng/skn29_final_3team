from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rag_gateway import InternalManualAgent


def test_two_document_follow_up_preserves_approved_snapshot() -> None:
    assert InternalManualAgent.selected_document_limit(
        "REGULATION_CHECK",
        ("MANUAL-FACILITY", "MANUAL-SAFETY"),
    ) == 2
    assert InternalManualAgent.selected_document_limit(
        "REGULATION_CHECK",
        ("MANUAL-FACILITY",),
    ) == 1
