# 현재 개발 상태 — 2026-10-22

사용자는 한국어 설명을 원한다. 최신 실행 방법은 ai/analysis_agent/README.md, 분석 기준은 docs/analysis.md다.

- 분석 모듈8개: inputs,assessment,interpretation,priority,workflow,model,research,agent.
- run_analysis는 workflow에, 프로필·추천 요청·추천 실행 함수는 agent에 있다.
- 실행3개: scripts/integration/run_analysis_agent.py,verify_analysis_agent.py,run_analysis_welfare.py.
- ZIP 생성·검사 도구와 중복 전달 문서는 활성 코드에서 제외했다. 원본은 .local-archive/structure_cleanup_20261022와 Git 이전 이력에 보존했다.
- 기본 입력 data/processed/analysis_inputs,결과 analysis_current,추천 결과 analysis_welfare_current.
- 성별 포함 risk-input-0.2 수신,기존0.1 호환. 분석 기준·순위 계산을 변경하지 않는다.
- 사용자 요청으로 구조 정리 후 메인 반영한다. 실제 Git 반영 상태는 원격에서 확인한다.
- 과거 Gemini/Tavily 시험 승인은 특정 집단·호출수에 한정됐으며 전체 집단 승인으로 확대하지 않는다. 이번 정리에서는 실제 API를 호출하지 않는다.
- 원본·가공 결과·키·가상환경·로컬 보관함은 Git 제외다. .env 값을 출력하지 않는다.
- 공통 그래프의 기획·평가 임시 노드는 이번 작업으로 완성된 것이 아니다.
- troubleshooting.md와 development_journal.md에 실제 기여·검증을 기록한다. AI 구현을 사용자 고안으로 기록하지 않는다.

검증: 전체243개 통과,삭제한 도구 전용4개 시험 제외. 원본 재실행216개 상세 결과·24개 순위 동일,37개 함수/클래스 AST 동일. 외부API0회.
