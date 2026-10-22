# AI 흐름 그래프 개발 안내

2026-10-22: 복지 수신부·공통 변환기는 성별 포함 risk-input-0.2를 지원한다. 기존0.1도 호환한다. 아래0.1 유지 설명은 이전 구현 기록이다.

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

## 복지 추천 연결부 보완 (2026-10-20)

기존 Engines 함수 인자와 target-profile-0.2/risk-input-0.1/welfare-0.4 형식은 유지한다. 복지 추천 요청에는 선택적인 analysis_context(welfare-context-0.1)를 추가했다. 기존 화면처럼 이 필드를 보내지 않는 요청도 동작한다.

- 분석 입력: profile 전체(근거 id·수치·단위·기준 월·출처·관측 제한·성별·예시 여부)와 causes를 전달한다. 수치를 백분율로 임의 변환하지 않는다. 검색에는 지역·연령·목적만 보내고 분석 맥락은 Gemini 판단에만 전달한다.
- 원인 전달: _Node가 기존 state.causes를 ctx.cause_hypotheses에 넣어 복지 노드로 전달한다. 따라서 recommend_existing(ctx, profile) 인터페이스는 바뀌지 않는다. 원인 설명을 새로 생성하는 기능은 이번 작업에 포함하지 않는다.
- 검증: 원인 코드 중복·존재하지 않는 근거 id 참조·다른 지역/연령·위험 판정 상태/단계/월/모델 버전/신호/관측 제한/예시 여부의 충돌을 거부한다. 위험도 미연결·held·partial에는 C0_unknown만 허용한다.
- 기획 출력: ExistingResource에 설명·신청 조건·연령 범위·추천 이유·고립 예방 연관성·신청 방법·출처 메타데이터를 추가했다. source_url은 기존 이용자를 위해 유지하고, source에는 자료 연도와 인용 근거 등을 보존한다.
- 전체 응답: ExistingResources.recommendation에 원래 추천 응답과 전달한 analysis_context의 독립 복사본을 보관한다. 검색 단계·크레딧·제외 사유 등 새 필드도 보존한다. coverage/review/has_example_context도 따로 제공한다.
- 상태 해석: available은 조회 결과를 받았다는 뜻이다. resources=[]이면 자원이 없다고 확정하지 말고 coverage와 경고를 읽는다. unavailable은 실행·입력 오류다. 둘을 같은 공백으로 계산하지 않는다. 공백 분석·지원 우선순위 정책 자체는 아직 별도 작업이다.

### 기존 자원 연계와 예방 기획의 대응 경로

복지 노드 결과의 `existing_resources.response_routing` (`response-routing-0.1`)에 다음 기획 담당자가 검토할 대응 경로를 함께 전달한다. 위험 단계·집단 우선순위를 계산하는 기능은 아니다.

| 조회 결과 | candidate_status | 함께 검토할 경로 |
| --- | --- | --- |
| 기존 자원 후보 확보 | candidates_found | 기존 자원 연계 + 예방·신규 기획 + 추가 확인 |
| 정상 조회했지만 후보 0개 | no_candidates_found | 예방·신규 기획 + 검색 범위·제외 사유 확인 |
| 검색·추천 실패 | unavailable | 예방 기획 초안 검토 + 기존 자원 재확인 |

각 경로는 `route`, `title`, `reason`, `resource_ids`, `checks`를 담는다. 경로는 서로 배타적이지 않다. 기존 자원이 있어도 예방·관계 형성이나 기존 서비스를 보완할 새 프로그램을 검토할 수 있다. 후보 0개는 실제 지역의 자원 부재를 증명하지 않으며, 실패 시에는 자원 확인이 완료되지 않았다는 사유를 보존한다.

이는 기획 검토용 선택지이며 신규 사업의 필요성·효과를 확정하거나 자동 실행하지 않는다. 기획 담당자는 기존 서비스와의 중복·보완 관계, 참여 수요와 근거를 확인해야 한다. 추천 건수로 위험 단계를 변경하지 않으며 지원 긴급성은 별도로 판단한다. 그래프의 전달 데이터·판단 기록과 추천 화면의 ‘프로그램 기획 요청 준비’에 연결했다. 화면은 담당자 요청과 선택 자원을 담은 `planning-request-0.1` JSON을 내려받는다([필드 설명](welfare_agent.md#기획-요청-파일-초안-planning-request-01)). 공통 그래프에 이를 자동 입력하거나 기획서를 생성하는 것은 후속 작업이다. 기존 `recommendation` 원문과 분석 입력은 그대로 보존한다.

### 호출 기록

기본 live 경로는 recommend_live(..., on_external_call=ctx.count)를 사용한다. Tavily는 메모리 캐시 확인 뒤 HTTP 요청 직전, Gemini도 HTTP 요청 직전에 콜백을 실행한다. 요청 전 검증 실패는 0회, 캐시 적중은 검색 0회, 검색 확장은 최대 2회, 실패한 HTTP 요청도 시도한 횟수에 포함한다. 이 값은 청구 크레딧이나 토큰 사용량이 아니라 요청 시도 수다.

response_call/tavily_search를 재사용하는 다른 노드는 on_external_call=ctx.count를 선택적으로 전달할 수 있다. 이 방식을 쓸 때 기존 ctx.count를 별도로 더하면 중복 집계된다. 테스트용 live_call/offline_call 주입 함수는 실제 요청을 하지 않는 한 횟수를 늘리지 않는다. 실제 호출하는 커스텀 구현은 자체적으로 계측해야 한다.

외부 호출 없이 연결과 그래프를 검사하는 명령:

```powershell
python -m unittest tests.test_contracts tests.test_welfare_bridge tests.test_graph tests.test_welfare_live_agent tests.test_welfare_agent
python -m ai.graph.demo
```

데모의 기획·평가는 여전히 [가짜] 구현이다. 실제 위험도 자동 수신·프로그램 기획·집단 우선순위를 완성한 실행이 아니다.
