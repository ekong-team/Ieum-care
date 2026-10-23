# 현재 개발 상태 — 2026-10-23

이전 작업: origin/main의 dc8fee5를 fast-forward로 가져온 뒤 adaptive 공식 HTML·PDF 수집을 로컬 구현했다. 문서 GET 최대4회·PDF2개, 공식 도메인·리디렉션 검사, SHA256 캐시, 이미지형 PDF 미확인 처리. 한국은행·강원관광재단 검색 범위 추가. 294시험 통과(외부 API 차단), 원본 재계산216집단·24순위 검증 통과. 한국은행 실제 공개 GET3회로 첨부 PDF 텍스트 추출 확인; Gemini·Tavily 호출0. 이 기록 시점의 변경은 당시 미커밋 상태였다. 최신 Git 상태는 저장소에서 확인한다. 기존 팀원의 React·복지추천·기획 전달 변경은 보존했다.

공식 문서 텍스트도 표 행·열 대응과 인과관계를 검증한 수치가 아니다. 광역은 배경으로만 표시하고 위험 단계·1차 순위에는 자동 병합하지 않는다. 다음 실제 Gemini·Tavily 실행은 이전 특정 호출 범위와 구분한다. 테스트와 실제 문서 GET 결과는 data/processed/analysis_document_validation_20261023에 있다.


최신 완료: React분석 탭→비동기 재계산/선택 집단 외부 검토→원본 검증→대시보드·추천 입력 갱신을 연결했다. backend/analysis.py와 Analysis.jsx/CSS가 담당한다. 분석 모듈8개 구조 유지, 정욱 기획·평가·수정 및 최종2차순위는 구현하지 않았다. Python306/React20시험·빌드·원본216집단/24순위 재검증 통과. 실제 분석 검토3회(각Gemini2/Tavily3/문서GET4), 기본재계산1회, 실제추천1회. 마지막 분석0527c4d62cc67791은 한국은행 PDF/SHA확보·모델S2선택 후 인용 불일치로 채택0. 실제추천은 조건부 간접후보1/직접연관0, 전체1/24조회로2차미확정. 모델·검색 성공과 근거 채택·추천 적합성을 혼동하지 않는다. 데이터·키·빌드·검증결과는Git제외.

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

최신 adaptive 검색 구현: research_decide→조건부research_search→research_check→제한내루프→interpret→first_priority. Gemini계획+검토최대2,Tavily최대3,질문별재검색1.264시험 통과·216건/24순위 재검증. 이번실제API0,모의응답과실제기록구분. 이전 기본focused실행은새방식실행으로간주하지않는다.
