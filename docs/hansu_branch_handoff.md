# 한수 브랜치 안내

현재 범위는 제공 데이터 분석·성별 활동 위축 단계·원인 가설·위험도 기준1차 우선 대상까지다.

먼저 [전체 처리 과정](hansu_analysis_pipeline.md)을 읽는다. 원본 파일, 정제 기준, 모듈별 역할, 계산식, 순위, 실제 실행, 다음 Agent의 입력 계약과 한계를 한 문서에 정리했다.

- 실행: scripts/integration/run_analysis_agent.py
- 분석 모듈: ai/analysis_agent/workflow.py 의 run_analysis()
- 준비 입력: features.csv / sensitivity.csv / context.json
- 출력: analysis_bundle.json / profiles/ / priority_review.json / analysis_explained.md
- 한수 출력 risk-input-0.2를 기준으로 확정했다. 현지가 자기 수신부를 이 형식에 맞춘다.
- Gemini·Tavily는 선택 실행이다. 기본 실행은 API를 호출하지 않는다.
- 원본·가공 결과·키·가상환경·로컬 보관함은 Git에 포함하지 않는다.
- 원본에서 새로 실행하려면 보유 원본과 인구·달력 배경자료가 별도로 필요하다.

기존 독립 수정 Agent 실험은 현재 분석 실행 경로에서 제외했다. 팀 공통 기획·평가 그래프의 재기획 경로는 남아 있다. 정리 목록은 [파일 정리 기록](branch_cleanup_20261020.md)을 참고한다.
