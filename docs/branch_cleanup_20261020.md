# 한수 브랜치 파일 정리 — 2026-10-20

사용자가 최신 Gemini/Tavily 개선을 포함해 필요한 파일만 정리하고 자신의 브랜치에 올리도록 요청했다.

- 활성 폴더에서 제외한 파일: 56개. 추적 파일은 이번 커밋에서 삭제로 기록하고, 미추적 문서는 업로드하지 않는다.
- 과거 내용을 없애기보다는 .local-archive/branch_cleanup_20261020/items/로 원래 경로대로 보관했다. manifest.json에 경로·크기·SHA-256이 있다. 이 보관함은 Git 제외다.
- 제외 범위: 독립 수정 Agent 실험·옛 데모/계약/시험, 초기 버스·중복 검토 도구, 중복된 과거 문서. 현재 Gemini 분석 CLI의 사용하지 않는 Anthropic 분기도 제거했다.
- 보존 범위: 원본·가공 데이터·키·가상환경·현지/정욱/화면 공통 코드, 현재 분석·검증·성별 전달, 보유 원본에서 배경자료를 재현하는 보조 코드, 논문·트러블슈팅·개발 기록.
- prepare_submission_data_pack의 설명서 참조, README·브랜치 안내·환경 안내를 현재 문서로 갱신했다.
- .env 및 .env.*는 Git 제외이며 비밀값 없는 .env.analysis.example만 예외로 둔다.
- 사용자 키가 없는지 커밋 후보를 검사한 뒤 푸시한다. 공개 원본/가공 데이터와 실제 호출 응답은 커밋하지 않는다.
- 작업 기여: 정리 기준·코드·문서·검증은 AI가 작성했고, 사용자는 최신 검색 개선 포함 및 브랜치 정리·업로드 범위를 결정했다.

## 활성 경로에서 제외한 목록

- ai/evaluation/revision_agent.py
- ai/evaluation/revision_graph.py
- ai/evaluation/revision_provider.py
- ai/evaluation/revision_runtime.py
- ai/evaluation/revision_v2.py
- backend/revision_service.py
- docs/activity_analysis_and_levels_draft.md
- docs/activity_level_rules_v1.md
- docs/agent_design_20261018.md
- docs/agent_design_review_20261018.md
- docs/agent_research_20261018.md
- docs/analysis_agent_implementation_20261019.md
- docs/analysis_agent_output_contract_20261019.md
- docs/analysis_agent_review_20261019.md
- docs/analysis_agent_team_review_20261019.md
- docs/analysis_brief_v1.md
- docs/analysis_context_final_20261015.md
- docs/analysis_handoff_explained_20261019.md
- docs/analysis_reproduction_20261014.md
- docs/cleanup_20261016.md
- docs/cleanup_20261020.md
- docs/contracts/integration_v1.schema.json
- docs/contracts/revision_v2.schema.json
- docs/data_analysis_final_20261014.md
- docs/data_submission_ready_review_20261015.md
- docs/evidence_data_recheck_20261013.md
- docs/external_context_data_20261015.md
- docs/hansu_analysis_revision_20261015.md
- docs/hyeonji_review_20261015.md
- docs/joint_analysis_review_20261014.md
- docs/main_merge_20261020.md
- docs/project_flow_git_review_20261019.md
- docs/public_data_supplement.md
- docs/revision_implementation_20261018.md
- docs/revision_team_integration_v2.md
- docs/spatial_revalidation_20261014.md
- docs/study_revision_20261019.md
- docs/submission_workplan_20261026.md
- docs/team_data_flow_20261015.md
- docs/weather_calendar_context_review_20261015.md
- scripts/data_processing/audit_joint_review.py
- scripts/data_processing/audit_public_bus_context.py
- scripts/data_processing/audit_spatial_activity_levels.py
- scripts/data_processing/build_joint_review_pack.py
- scripts/data_processing/pilot_activity_levels.py
- scripts/data_processing/prepare_analysis_team_review.py
- scripts/integration/audit_agent_design.py
- scripts/integration/build_handoff_examples.py
- scripts/integration/build_revision_contract.py
- scripts/integration/run_revision_demo.py
- scripts/integration/run_revision_graph.py
- scripts/integration/verify_revision_release.py
- tests/test_revision_agent.py
- tests/test_revision_graph.py
- tests/test_revision_v2.py
- docs/cleanup_20261020_manifest.json


검증 확정: 전체 241개 중 238개 통과, 실패/오류0, 공간 패키지 미설치로 3개 생략. 외부 API 호출0. 로컬 HTTP만 허용한 검증 환경에서 확인했다.

커밋 직전 파일 끝 빈 줄을 정리했다. Python AST가 동일함을 검사했고, 코드 해시 변경에 맞춰 성별 입력 manifest·최종216개 분석·전달ZIP을 다시 생성해 검증했다.
