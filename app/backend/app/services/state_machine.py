"""분석의 RECEIVED·ROUTED·종단 상태 허용표와 변경 불가능한 전이 이력을 제공하며 역행·중복 전이는 InvalidTransitionError로 차단한다."""

from app.contracts import AnalysisStatus


class InvalidTransitionError(ValueError):
    """분석 실행이 허용표 밖의 상태로 이동하려 했음을 나타낸다.

    현재·목표 상태는 예외 메시지에 남고 호출자는 전이를 보정하지 않아 trace와 API 상태의 모순을 숨기지 않는다.
    """
    pass


class AnalysisStateMachine:
    """수신부터 하나의 종단 결과까지 허용된 분석 상태 순서만 기록한다.

    route 전과 후의 종단 상태를 명시적 허용표로 분리하며, history는 응답 감사 근거로
    사용되므로 임의 전이와 외부 list 수정을 모두 차단한다.
    """
    _allowed = {
        AnalysisStatus.RECEIVED: {
            AnalysisStatus.ROUTED,
            AnalysisStatus.BLOCKED,
            AnalysisStatus.CLARIFICATION_REQUIRED,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        },
        AnalysisStatus.ROUTED: {
            AnalysisStatus.SUCCEEDED,
            AnalysisStatus.BLOCKED,
            AnalysisStatus.CLARIFICATION_REQUIRED,
            AnalysisStatus.PARTIAL,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        },
    }

    def __init__(self) -> None:
        self._history = [AnalysisStatus.RECEIVED]

    @property
    def history(self) -> tuple[AnalysisStatus, ...]:
        """수신 상태부터 현재까지의 전이 기록을 변경 불가능한 tuple로 반환한다.

        내부 list를 직접 노출하지 않아 응답 조립 코드가 감사 가능한 상태 순서를 변조하지 못하게 한다.
        """
        return tuple(self._history)

    def transition(self, target: AnalysisStatus) -> None:
        """현재 상태에서 허용된 종단 또는 실행 상태로만 전이 기록을 추가한다.

        허용표에 없는 역행·중복 전이는 ``InvalidTransitionError``로 거부해 응답 상태와
        trace가 서로 다른 실행 생명주기를 주장하지 못하게 한다.
        """
        if target not in self._allowed.get(self._history[-1], set()):
            raise InvalidTransitionError(f"{self._history[-1].value} -> {target.value}")
        self._history.append(target)
