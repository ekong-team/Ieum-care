"""노드 함수에 넘기는 실행 정보. 외부 호출 횟수를 노드별로 세어 판단 기록에 남긴다."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from ai.contracts.causes import CauseHypothesis


@dataclass
class NodeContext:
    run_id: str
    mode: Literal["live", "offline"]  # offline = 외부 호출 없이 저장 자료·가짜 응답 사용
    calls: Counter = field(default_factory=Counter)
    cause_hypotheses: list[CauseHypothesis] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def count(self, provider: str, n: int = 1) -> None:
        """provider: "gemini" 또는 "tavily". 비용·무료 한도 확인용."""
        self.calls[provider] += n

    def warn(self, message: str) -> None:
        """노드가 멈추지 않고 계속 진행하면서 남기는 주의 사항 (예: 형식 오류로 버린 기획안)."""
        self.warnings.append(message)
