# AI 흐름 그래프 개발 안내

설계 기준: [시스템 설계](system_design.md) 4·5장. 이 문서는 코드를 실행하고 노드를 추가하는 방법만 다룬다.

## 현재 상태 (10/19 뼈대)

| 노드 | 상태 | 파일 |
| --- | --- | --- |
| cause_analysis | 임시 규칙 (LLM 해석 전) | `ai/nodes/causes.py` |
| welfare_recommend | **실제 동작** (복지 추천 Agent 감싸기, offline은 저장 자료) | `ai/nodes/welfare.py` |
| trend_search · gap_analysis · plan_generate · grounding_check · evaluate | 가짜 구현 (`[가짜]` 표시) | `ai/nodes/stubs.py` |
| priority_report | 흐름 규칙으로 동작 | `ai/graph/pipeline.py` |

## 실행

```bash
python -m pip install -r requirements.txt
python -m ai.graph.demo              # 예시 프로필로 그래프 실행, 판단 기록 타임라인 출력 (API 키 불필요)
python -m ai.graph.demo --mermaid    # 그래프 구조 Mermaid 출력 (문서·발표용)
python -m unittest discover tests    # 전체 테스트 (기존 복지 추천 테스트 포함)
```

## 파일 구성

```text
ai/contracts/   입출력 형식 (Pydantic). 모든 노드·API·화면이 공유
  profile.py      TargetProfile: 데이터 → AI 로직 입력
  causes.py       원인 코드 C0~C5, CauseHypothesis
  plan.py         ProgramPlan: 기획안 (평가 입력)
  evaluation.py   PlanEvaluation, 축별 만점, 총점 계산 summarize()
  pipeline.py     중간 결과, TraceEvent(판단 기록), PipelineState(그래프 상태)
ai/graph/
  pipeline.py     그래프: 노드 순서·분기·재기획·실패 처리·결과 일관성 검사
  trace.py        판단 기록 수집기 (실행 중에도 읽을 수 있음)
  demo.py         실행 예시
ai/nodes/       노드별 계산 (그래프는 이 함수들을 Engines로 꽂아 쓴다)
```

## 흐름 규칙 (pipeline.py가 보장하는 것)

- 복지 추천·트렌드 검색은 병렬 실행, 둘 다 끝나야 공백 분석.
- 복지 추천·트렌드 검색·원인 분석·공백 분석이 실패해도 대체 결과로 계속한다.
- 기획 생성·근거 검증·평가가 실패하면 실행 실패로 리포트한다. 단, 재기획 단계에서 실패하면 원안 평가 결과로 마무리한다.
- 평가 기준(60점) 미달 기획안만 1회 재기획한다. 수정안 표시(`revision=1`)는 그래프가 붙인다.
- 재기획안이 근거 검증에서 빠지면 그 기획안만 원안으로 되돌린다. 모두 빠지면 다시 평가하지 않고 원안 결과로 마무리한다.
- 노드 결과의 기획안 id가 중복되거나, 근거 검증·평가 결과의 id가 입력과 맞지 않으면 그 노드를 실패로 처리한다.

## 가짜 노드를 실제 구현으로 바꾸는 법

1. `ai/nodes/`에 새 파일을 만들고 `stubs.py`의 같은 이름 함수와 **같은 인자·반환 형식**으로 작성한다.
2. `ai/graph/pipeline.py`의 `Engines` 기본값을 새 함수로 바꾼다. 그래프 코드는 고치지 않는다.
3. 외부 호출을 하면 `ctx.count("gemini")` 또는 `ctx.count("tavily")`로 센다. offline 모드에서는 외부 호출을 하지 않는다.
4. 테스트에서는 `Engines(..., 바꿀_노드=가짜함수)`로 외부 호출 없이 검증한다 (`tests/test_graph.py` 참고).
