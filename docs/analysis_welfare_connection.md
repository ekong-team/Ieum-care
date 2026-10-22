# 분석 → 복지추천 직접 연결 (2026-10-22)

ZIP은 실행 입력이 아니다. 같은 저장소의 파이썬 함수끼리 연결한다. 과거 ZIP은 당시 분석 스냅샷을 전달한 기록이다.

## 함수로 연결 — 현지에게 전달할 진입점

```python
from ai.analysis_agent.workflow import run_analysis
from ai.analysis_agent.recommendation import recommend_from_analysis

bundle = run_analysis(rows, contexts, manifest, period="202512")
result = recommend_from_analysis(
    bundle, "202512_32010_30G_female", mode="offline"
)
```

`rows/contexts/manifest`는 기존 `load_inputs(features_path, sensitivity_path, context_path)`의 반환값이다. `run_analysis()`의 결과를 파일·ZIP으로 변환할 필요가 없다. 추천할 집단은 호출자가 analysis_id로 명시한다. 1차 우선순위 전체를 무조건 외부 API에 보내지 않는다.

요청만 필요하면 `recommendation_request(bundle, analysis_id)`를 사용한다. 반환값은 target·risk_assessment·confirmed_support_needs·analysis_context를 가진 dict다. `analysis_context`는 welfare-context-0.1의 profile+causes이며 보관용 handoff_record.analysis_context와 구분한다.

## 저장된 분석으로 즉시 연결 시험

프로젝트 루트에서:

```powershell
.\.venv-agent\Scripts\python.exe scripts/integration/run_analysis_welfare.py --analysis-id 202512_32010_30G_female
```

- 입력: data/processed/analysis_current/latest.json이 가리키는 analysis_bundle.json.
- 출력: data/processed/analysis_welfare_current/result.json.
- 실제 저장 자원 추천 함수를 사용하지만 외부 API는 호출하지 않는다.
- 다른 집단: --analysis-id를 바꾼다. 결과를 구별해 남기려면 --output 경로를 명시한다.
- 팀원 컴퓨터에는 가공 결과가 Git으로 내려가지 않는다. 로컬에서 분석을 실행하거나 analysis_bundle.json 한 개를 따로 전달한다. 전달한 JSON 폴더를 --results로 지정하면 된다.
- 최신 Python 의존성을 설치해야 하며 ZIP을 읽거나 생성하는 과정은 없다.

## 실제 외부 호출

함수의 `mode="live"`는 현지 recommend_live를 호출한다. CLI는 추가로 --allow-external을 요구한다. 현재 검증에서는 실제 외부 호출을 하지 않았다. 분석 단계의 Gemini 검토 실행 여부와 추천 단계의 Gemini 실행 여부는 서로 다르다.

## 서버 또는 공통 그래프

- 서버: recommendation_request 반환값에 mode="offline"을 더해 POST /api/welfare/recommendations에 보낸다. mode 생략 시 서버 기본값은 live다. dict를 직접 recommend()에 넘길 때에는 mode를 넣지 않는다.
- 공통 그래프: 기존 to_welfare_payload도 risk-input-0.2와 성별을 전달하도록 수정했다. 원인 노드는 make_cause_engine(bundle)을 Engines.analyze_causes에 주입하고 target_profile(bundle, analysis_id)를 입력한다. 전체 기획·평가의 임시 노드는 이번 작업으로 완성된 것이 아니다.

## 수신 기준과 검증

- 0.2에는 target.sex와 risk_assessment.sex가 필수이며 두 값이 일치해야 한다.
- 분석 맥락의 성별도 요청과 일치해야 한다. 수치·단위·근거 ID·상태·기준월·모델 버전을 보존한다.
- 기존 화면의 성별 없는 0.1 요청은 계속 받는다. 성별 포함 요청을 0.1로 낮추지 않는다.
- 10대 연령 범위는 10~19세다. 0~9세 전용 자원을 추천 대상과 겹친다고 보지 않는다.
- complete/partial/held를 유지한다. 부분·보류는 원인 미확정으로 전달한다.
- 기존 자원 목록의 성별 자격은 확인되지 않았으므로 후보 조회는 개인 자격 판정이 아니다.
- 회귀 테스트247개 통과. 실제 저장 분석216개 전부 성별·상태·단계·근거 보존 확인. 춘천30대여성의 저장 자료 후보3개 반환. 현재 운영·자격·추천 효과 검증과는 다르다.

과거 분석의 수치와 우선순위를 바꾸지 않고 연결부를 수정했다. 과거 파일의 구현 해시는 당시 코드의 기록이며 현재 코드로 덮어쓰지 않는다. 코드 변경 뒤 새 분석이 필요하면 정규 분석 명령으로 새 실행을 만든다.
