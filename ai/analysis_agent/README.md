# 분석 에이전트

2026-10-20: Gemini·Tavily 선택적 연결은 `docs/analysis_gemini_tavily_20261020.md` 참조.
`--mode gemini --web-search --analysis-id ... --allow-external`로 단일 집단을 검토한다.
키는 `.env`에서 읽고 `--check-config`는 값 없이 설정 여부만 출력한다.
검색 출처는 `external_research.json`에 저장하며 위험 단계나 순위를 바꾸지 않는다.
무료 과금 등급은 계정에서 확인해야 하며 키만으로 무료를 보장할 수 없다.

최신 v2.2는 남녀별144건과 합산72건을 지원한다. 남녀 순위와 합산 순위는 분리한다. 성별분석 설명은 docs/analysis_sex_results_20261019.md, 현지 전달은 docs/hyeonji_analysis_handoff_20261019.md 참조. 기존60세이상식별자60GU를유지한다. 현지에게 제안한 성별입력0.2는 현재 서버에 반영된 계약이 아니다.

범위: 제공 데이터 분석 → 활동 위축 1~5단계·원인 가설 → 위험 단계 기준 1차 검토 순위.
복지자원 추천·2차 필터링은 포함하지 않는다.

## 처음 읽을 순서

1. policy.py: 계산 기준과 범위.
2. assessment.py: 단계 산식·부분판정·보류.
3. interpretation.py와 context.py: 근거·가설·집단 특성과 배경.
4. priority.py: 단계만으로 순위 계산.
5. workflow.py: 전체 네 단계.
6. reviewer.py: 선택적 모델 검토.
7. handoff.py: 정욱 공통 입력/원인 함수 연결.
8. inputs.py: 파일·숫자·키 검사.

각 모듈은 하나의 역할을 맡는다. 계산은 언어모델과 무관하며, 모델 실패 시 계산 결과를 보존한다.
기본 실행은 오프라인이다. 모델을 사용한 실행과 동일하다고 표시하지 않는다.
위험 영향 요인은 검토 후보이며 개인 고립 원인·실제 자격을 확정하지 않는다.

## 실행

프로젝트 루트에서:
~~~powershell
./.venv-agent/Scripts/python.exe -X utf8 scripts/integration/run_analysis_agent.py
./.venv-agent/Scripts/python.exe -X utf8 scripts/integration/verify_analysis_agent.py
~~~

기본 입력은 data/processed/analysis_inputs의 features.csv, sensitivity.csv, context.json이다. build_sex_features.py가 준비하며, 기본 출력은 data/processed/analysis_current다.
결과 최상위의 latest.json이 재검산에 성공한 최신 하위 폴더를 가리킨다. 과거 최상위 report.md는 초기 버전 기록일 수 있다.

## 출력과 팀 연결

- profile: 정욱 TargetProfile-0.2.
- team_causes: 정욱 CauseHypothesis.
- assessment: 계산 정책·값·단계·상태.
- characteristics/background_context: 집단 특성과 인구·달력, 누락 항목.
- interpretation: 가설·근거·확인 질문·선택적 모델 검토.
- sensitivity: 비교 기준별 결과.
- priority_review: 1차 순위·부분/보류·빠진 대상 목록.

target_profile(bundle, analysis_id)로 공통 입력을 받는다.
make_cause_engine(bundle)은 정욱 Engines.analyze_causes에 연결하는 함수다.
실제 전체 팀 그래프 실행은 팀 브랜치 통합 후 별도 확인해야 한다.

원본부터 다음 Agent 전달까지의 최신 설명: docs/hansu_analysis_pipeline.md.
focused 질문별 검색과 인용 검사: docs/analysis_research_improvement_20261020.md.
