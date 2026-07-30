from app.contracts import AnalysisStatus


class InvalidTransitionError(ValueError):
    pass


class AnalysisStateMachine:
    _allowed = {
        AnalysisStatus.RECEIVED: {
            AnalysisStatus.ROUTED,
            AnalysisStatus.BLOCKED,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        },
        AnalysisStatus.ROUTED: {
            AnalysisStatus.SUCCEEDED,
            AnalysisStatus.BLOCKED,
            AnalysisStatus.PARTIAL,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        },
    }

    def __init__(self) -> None:
        self._history = [AnalysisStatus.RECEIVED]

    @property
    def history(self) -> tuple[AnalysisStatus, ...]:
        return tuple(self._history)

    def transition(self, target: AnalysisStatus) -> None:
        if target not in self._allowed.get(self._history[-1], set()):
            raise InvalidTransitionError(f"{self._history[-1].value} -> {target.value}")
        self._history.append(target)
