from app.contracts import PipelineStage, StageOutcome, TraceStep


def fixture_trace(name: str) -> tuple[TraceStep, ...]:
    stages = {
        "g1_clarification": (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
        ),
        "g2_blocked": (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.MODEL,
            PipelineStage.G2,
        ),
        "timeout": (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.MODEL,
            PipelineStage.G2,
            PipelineStage.QUERY,
        ),
        "g3_failed": (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.MODEL,
            PipelineStage.G2,
            PipelineStage.QUERY,
            PipelineStage.G3,
        ),
        "repaired": (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.MODEL,
            PipelineStage.G2,
            PipelineStage.REPAIR,
            PipelineStage.G2,
            PipelineStage.QUERY,
            PipelineStage.G3,
            PipelineStage.ARTIFACT,
        ),
    }.get(
        name,
        (
            PipelineStage.ROUTER,
            PipelineStage.CONTROLLER,
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.MODEL,
            PipelineStage.G2,
            PipelineStage.QUERY,
            PipelineStage.G3,
            PipelineStage.ARTIFACT,
        ),
    )
    failed = name in {"timeout", "g3_failed"}
    blocked = name in {"g1_clarification", "g2_blocked"}
    return tuple(
        TraceStep(
            stage=stage,
            outcome=(
                StageOutcome.FAILED
                if failed and index == len(stages) - 1
                else StageOutcome.BLOCKED
                if blocked and index == len(stages) - 1
                else StageOutcome.BLOCKED
                if name == "repaired" and index == 5
                else StageOutcome.PASSED
            ),
        )
        for index, stage in enumerate(stages)
    )
