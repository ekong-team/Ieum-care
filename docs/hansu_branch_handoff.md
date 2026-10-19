# 한수 작업 브랜치 안내

2026-10-19. 데이터 분석 보완 코드와 수정 에이전트 v2를 공유하기 위한 브랜치다.

## 포함 범위

- 분석: 활동 위축 시범 단계·설명 근거·민감도/공간 감사·보고서 생성·인구 배경 연결 코드.
- 수정: 실제 LangGraph/SQLite 체크포인트, 기획/평가 버전·해시 검사, 수정 후보·재평가, 중단/재개, 호출 기록, 표준 JSON Schema 검사.
- 테스트·설치 목록·v1/v2 입출력 계약·공식 기술자료 근거와 팀 연결 문서.

원본·가공 데이터, 상세 결과표·개인 로컬 인수인계/진행 기록, 가상환경·캐시·API키는 이 브랜치 업로드 대상에서 제외했다. 공모전 제공 자료와 로컬 결과 파일은 공개 저장소에서 배포하지 않는다.

## 실행 준비

에이전트 환경은 Python3.12에서 `requirements-agent-lock.txt`로 구성한다. 분석 환경은 기존 `requirements.txt`와 추가 `requirements-analysis.txt`를 참고한다. 가상환경 폴더를 복사하지 않는다.

실제 분석과 배경자료를 사용한 시연에는 아래 로컬 파일이 필요하다. 저장소에 없는 것은 의도된 분리다.

- `data/processed/agent_activity_evidence.json`
- `data/processed/submission_data_review_20261015/analysis_with_population_calendar.json`

담당자가 허용된 경로로 준비한 기존 특징/분석 결과를 사용하거나, `scripts/data_processing`의 정제·활동 단계/근거·인구 연결·제출 준비본 생성 코드를 순서에 맞게 실행한다. 원본 파일은 `data/raw`와 `data/external`에 로컬 보관한다. 경계자료 조건과 기관 좌표 정의는 별도 확인한다. 이 브랜치는 데이터가 포함된 독립 실행 배포물이 아니다.

수정 진입점: `scripts/integration/run_revision_graph.py`. fixture 모드는 미리 작성한 응답으로 실행 경로만 확인하며 실제 LLM 성능 검증이 아니다. 문서: `revision_implementation_20261018.md`, `revision_team_integration_v2.md`, `agent_research_20261018.md`.

## 상태·통합 주의

- 기존 분석 단계는 인구·달력 추가로 재가중하지 않았고 개인 고립 진단·확률이 아니다.
- 실제 모델 키/모델 선정·실제 자원/단가·팀 평가/화면 연결은 별도 작업이다.
- 한수 로컬의 기존 분석 기준 커밋에서 작업을 분리했다. 원격 main의 이후 분석 구조 통합·복지 추천·화면 변경과는 이번 업로드에서 병합하지 않았다. 팀 통합 시 경로/계약 호환을 확인해야 한다.
- 기존 v1·단순 실행 경로는 호환/비교용이다. 최종 에이전트 실행은 LangGraph v2 문서를 따른다.
