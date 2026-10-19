# 정욱·평가 담당자와 연결할 v2 약속

현재는 로컬 함수 어댑터이며 HTTP서버·인증·화면은 구현되어 있지 않다. 아래 함수는 실제 실행 가능하고 v1 분석/화면 계약은 덮어쓰지 않았다.

## 시작

`backend.revision_service.execute_revision(request, database, generator=None, reviewer=None)`.

request: `run_id`, `analysis_id`, `planning_as_of`, `program_plan`, 선택 `max_attempts`.
모델·API키·DB경로·자료 경로·context를 클라이언트가 지정하지 않는다. context는 서버측 확정 파일에서 로드한다. 모델이 없으면 needs_model/의미평가 미수행으로 표시한다. generator/reviewer는 서버가 관리하는 callable이다.

응답: `state`, `paused`, `next_nodes`, `requires_human_review`, `actual_llm_responses`.
state에서 `current_plan`, `evaluation.issues`, `history`, `questions`, `status`, `stop_reason`을 화면에 표시한다. fixture 표시와 실모델 표시를 구분하고 needs_input을 성공 추천/승인으로 바꾸지 않는다.

## 재개

`backend.revision_service.resume_revision(run_id, decision, database, generator=None, reviewer=None)`.

decision은 `action`(provide_input/record_review/reject), `reviewer`, `note`, provide_input일 때만 `program_plan`을 가진다. 새 기획안은 같은plan_id/analysis_id, 현재version+1이어야 한다. record_review는 검토 기록일 뿐 집행 승인 아니다.

계약: `docs/contracts/revision_v2.schema.json`. 계획 본체는 v1 ProgramPlan을 참조하므로 기존 입력을 재사용한다. 분석/context해시는 런타임이 추가한다. 실제 팀 평가 응답을 받으려면 버전/hash와 issue 형식의 신뢰 가능한 변환·검증 어댑터가 필요하다. 임의 클라이언트가 평가 결과를 넣어 수정 권한을 풀 수 없다.

## 배포 전 필요

서버측 사용자 인증·run 소유권 확인·요청크기 제한·동시 실행/장애 운영·자료 보존 정책·실제 모델 계약·토큰/비용 한도가 필요하다. run_id는 식별자이며 비밀번호가 아니다. 지금의 SQLite 체크포인트와 호출 ledger는 로컬 단일 호스트 기준이고, 여러 서버라면 공유 저장소와 분산 실행 잠금을 검토해야 한다. 외부 API응답 저장 전 중단 시 결과불명 상태가 생길 수 있으므로 함부로 재과금 호출하지 않는다.

설치: Python3.12 가상환경에서 requirements-agent-lock.txt. 기존 분석 의존성은 requirements.txt/requirements-analysis.txt에 별도 보존한다. 전체 분석 테스트는 기존 분석 Python과 새 에이전트 의존성 경로를 함께 읽는 별도 회귀 검사로 수행했으며, 새 환경에 pandas/numpy를 설치했다고 표시하지 않는다.
