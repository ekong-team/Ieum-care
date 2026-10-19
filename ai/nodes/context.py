"""노드 함수에 넘기는 실행 정보. 외부 호출 횟수를 노드별로 세어 판단 기록에 남긴다."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class NodeContext:
    run_id: str
    mode: Literal["live", "offline"]  # offline = 외부 호출 없이 저장 자료·가짜 응답 사용
    calls: Counter = field(default_factory=Counter)

    def count(self, provider: str, n: int = 1) -> None:
        """provider: "gemini" 또는 "tavily". 비용·무료 한도 확인용."""
        self.calls[provider] += n
