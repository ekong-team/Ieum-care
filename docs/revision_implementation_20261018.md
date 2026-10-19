# 수정 에이전트 구현·검증 보고

2026-10-18. 사용자 요구에 따라 AI가 구현하고 기록했다. 시간 절약을 이유로 단순 구현을 최종으로 삼지 말라는 추가 요청을 반영했다. 실제 LLM 성능·복지 효과·다중 사용자 배포가 완료됐다는 보고가 아니다.

## 실행 경로와 역할

최종 실행 경로는 `scripts/integration/run_revision_graph.py` → `ai/evaluation/revision_graph.py`(LangGraph) → `revision_v2.py`(계약·검사·수정 적용)다. API 통합 함수는 `backend/revision_service.py`다. 서버가 자동 실행되거나 정욱의 화면과 연결되지는 않는다.

기존 `revision_agent.py`는 v1 호환과 과거 감사 재현을 위해 보존했다. `revision_runtime.py`와 `run_revision_demo.py`의 단순 SQLite 실행은 개발 중 비교용 경로이며 최종 진입점이 아니다. run_revision_demo 모듈의 가상 입력·생성 fixture는 LangGraph 시연에서도 사용한다. 코드만 보고 이 두 경로를 실제 서비스2개로 해석하지 않는다.

## 이번에 구현한 기능

|기능|구현·확인 범위|
|---|---|
|배경자료 전달|사용자 확정 인구·달력72건 중 선택한 집단을 실제 생성/평가 payload에 넣음. 기존 단계 불변|
|표준 계약 검사|jsonschema Draft2020-12로 기존 ProgramPlan 전체 검사. 중복ID·NaN·날짜 순서 등 별도 검사|
|버전·해시|기획버전·전체 기획hash·분석hash·배경hash가 평가와 일치해야 수정 허용|
|수정 범위|제목·목적·활동·성과측정 제안만 변경. 대상·분석·예산·출처는 모델 변경 금지|
|후보 격리|원안 보존, 후보 검사, 전체 재평가. 새 지적 발생/해결 없음이면 후보 미채택|
|수정 이력|필드별 before/after·issue_id·이유·원안/후보hash 저장|
|평가 분리|코드 기본 검사와 별도 의미 평가 callable. 모델 미연결이면 의미평가 미수행 표시|
|실제 모델 어댑터|Anthropic Messages HTTP 어댑터 작성·가짜 응답으로 전송형식 검사. 키·명시 모델·외부전송 허용 플래그 필요. 실제 API 미호출|
|상태·중단/재개|실제 LangGraph+SQLite checkpoint. 담당자 입력 시 interrupt, 다음 프로세스에서 Command(resume)로 재검사|
|호출 안전성|호출 ledger를 먼저 기록하고 결과 저장. 결과불명 중단은 자동 과금 재시도 금지. 로컬 관리자가 구 프로세스 종료를 확인하고 복구|
|중복 요청|동일run/동일입력은 저장 상태 재조회, 다른 입력은 충돌. 동시에 실행 중인run은 거부|
|실행 제한|수정 시도·평가/수정 총 호출 수 상한, 모델 타임아웃·입력 크기·출력 토큰 상한|
|예산|Decimal 계산, 미완성 총합null, 확인 가능한 소계 별도. 사용자 가정을 공식 확인단가로 부르지 않음|
|관측성|checkpoint의 events·usage·버전·diff·중단이유, 호출 ledger. LangSmith 외부 tracing은 실행시 명시적으로 비활성화|
|담당자 기록|자격·단가·일정 등을 모르면 needs_input. 검토 기록을 남겨도 실제 집행승인/고립진단으로 표시하지 않음|

### 왜 LangGraph를 실제로 사용했나

처음에는 작은 SQLite 실행기를 만들었지만, 사용자가 시간 때문에 쉽게 넘어가지 말라고 정정했다. 요구사항에도 지속적 중단·재개와 분기·재평가가 있으므로 LangGraph의 체크포인터와 interrupt를 실제 구현했다. 단지 최신 도구라서가 아니라 해당 요구를 검증하기 위해서다. SQLite는 여기서 단일 호스트 로컬 저장소다. 여러 서버/사용자 배포를 하려면 공유 저장소·인증·run 소유권·운영 정책을 추가해야 한다.

## 시연 결과 읽기

최종 검증 기록: 수정 관련40개 테스트 모두 통과. 기존 분석 포함 전체65개 중62개 통과·공간 관련3개 건너뜀. 전체 검사는 기존 분석 Python3.12에서 새 에이전트 의존성 경로를 읽도록 구성해 수행했다. 독립 에이전트 환경에서 수행한 것은 수정 관련40개다. 실제 분석72건의 원근거 일치와 인구·달력 전달을 대조했다. 기록은 `data/processed/revision_graph_20261018/verification.json`, `full_regression.json`이다.

1차는 기능·계약·정상흐름 점검, 2차는 구버전/변조/잘린응답/후보악화/질문반복/중단/재시작/동일run충돌 등 실패유도 점검이다. 두 번 모두 AI가 수행했으며 독립 전문가 또는 실제 모델 품질평가가 아니다. 프로그램 평가와 수정이 같은 모델을 사용할 수 있어 서로 통계적으로 독립적인 심사라고 주장하지 않는다.

실제 입력은 2025년12월 춘천30대 분석과 인구·달력이다. 기획안은 가상이며 생성/의미평가 응답도 미리 작성한 fixture다. 이 데이터 조합을 실제 자원 기획 완료라고 부르지 않는다.

정상 시연: 코드 검사 → 평가 fixture → 수정 fixture → 후보 검사 → 재평가 fixture → 입력 대기. 기획안은 v1→v2, title/objective/activities/performance_measures를 보완한다. 실제 인원·주민 자격·신청 자격·일정·근거·예산은 없으므로 **needs_input이 정상 종료/대기 결과**다. 이것을 억지로 합격으로 만들지 않았다.

고정 응답3회는 외부 모델 호출3회가 아니다. `calls`는 생성/평가 함수 호출 횟수이고 `confirmed_llm_responses`는 실제 provider 응답이 확인된 횟수다. 키가 없어 실제 LLM 응답은0이다. `fixture_not_domain_evaluation`과 `not_run`을 실제 의미평가와 구분한다.

## 남은 실질적 한계

코드 재검토로 추가 반영한 사항: 실행 코드·모델 설정이 바뀌면 오래된 checkpoint를 그대로 재개하지 않도록 pipeline hash와 actor identity를 묶었다. 활동 변경 비용 확인 질문과 구조적 누락 목록 재계산을 추가했다. 잘리거나 JSON이 틀린 실제 provider 응답도 과금될 수 있어, 제안은 폐기하되 response ID·usage·종료 이유는 보존한다. 모델 응답 형식 오류를 숨겨 고치는 자동 복구/무제한 재시도는 넣지 않았다.

1. API키와 사용할 실제 모델이 설정되지 않았다. 선택 가능한 Anthropic 어댑터를 구현했을 뿐 팀 모델 선정/비용 승인을 대신하지 않았다. 실제 JSON 준수·지적해소·비용/시간은 미측정.
2. 실제 복지자원·운영기관·단가 카탈로그가 없다. 존재하지 않는 자료를 생성해 채우지 않았다. 추천·기획의 실질적 품질은 이 자료와 다른 담당자의 구현이 필요하다.
3. 코드의 문장검사는 제한된 패턴 tripwire다. 완전한 의미 검증·프롬프트 주입 방지·사실성 보증이 아니다. 외부 평가 모델도 근거 원문과 사람 검토를 대체하지 않는다.
4. 검증 자격/단가가 제공됐다고 단정하는 기능은 없다. 공식 출처라고 적힌 URL도 원문·유효성은 별도 확인해야 한다. 예산의 declared_documented_unverified는 선언된 근거이며 실제 검증 완료가 아니다.
5. 검토 기록 기능은 집행승인이 아니다. 보안 인증·웹 서버·프론트 연결은 미구현이며 함수 단위 백엔드 어댑터를 제공한다.
6. 실제 모델 개선 실험 A/B/C/D와 독립 복지 전문가 검토는 미실행. 기존 시범 단계의 통계적 한계는 유지된다.
7. 전체 분석 파이프라인을 새로 계산하지 않았다. 에이전트 변경으로 원본 데이터/기존 단계가 바뀌지 않았는지 별도 대조한다.

## 출처

- [LangGraph interrupt·재개 공식문서](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph persistence 공식문서](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Anthropic Messages 공식 API](https://platform.claude.com/docs/en/api/messages/create)
- 이전 논문·하네스 근거는 agent_research_20261018.md 참조.
