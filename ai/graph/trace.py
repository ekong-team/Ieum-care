"""판단 기록(TraceEvent) 수집기.

노드가 '시작'한 순간도 기록하므로, 서버가 실행 중에 이 목록을 읽으면 화면에 진행 상황을 바로 보여 줄 수 있다.
병렬 노드가 동시에 기록해도 순서 번호(seq)가 겹치지 않도록 잠금(lock)을 쓴다.
"""

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable, Optional

from ai.contracts import TraceEvent

KST = timezone(timedelta(hours=9))


class TraceRecorder:
    def __init__(self, run_id: str, on_event: Optional[Callable[[TraceEvent], None]] = None):
        self.run_id = run_id
        self.events: list[TraceEvent] = []
        self._lock = RLock()  # 재진입 가능: 콜백 안에서 after()를 불러도 멈추지 않는다
        self._on_event = on_event

    def emit(self, node: str, status: str, **fields) -> TraceEvent:
        with self._lock:
            event = TraceEvent(run_id=self.run_id, seq=len(self.events), node=node, status=status,
                               at=datetime.now(KST).isoformat(timespec="seconds"), **fields)
            self.events.append(event)
            # 잠금 안에서 호출해 콜백도 seq 순서대로 받는다. 콜백 동안 병렬 노드가 기다리므로 짧게 끝내야 한다.
            if self._on_event:
                self._on_event(event)
        return event

    def after(self, seq: int) -> list[TraceEvent]:
        """seq보다 뒤의 기록만 돌려준다. 화면이 1초마다 새 기록만 가져갈 때 쓴다."""
        with self._lock:
            return [event for event in self.events if event.seq > seq]
