2026-10-20 안내: 이 문서는 성별 전달 계약의 기존 안내다. 최신 전체 흐름은 hansu_analysis_pipeline.md를 우선한다. 문서의 과거 API0 기록은 당시 오프라인 묶음에 관한 것이며 현재 실제 Gemini 연결 시험과 구분한다. 한수 출력 risk-input-0.2가 기준이며 수신부의 성별 계약 적용은 현지 담당이다.

# 현지에게 보낼 파일과 입력 맞추기 — 2026-10-19

## 보내는 방법

최신 ZIP 한 개를 팀 채팅이나 허용된 파일 공유 경로로 보내면 된다.
파일: hansu_to_hyeonji_20261019_6d5304bcb1eefb32.zip.
최신 위치는 data/processed/hyeonji_handoff_20261019/latest_package.json에 기록돼 있다.
압축 안 README_현지에게.md → 분석결과_설명.md → examples/female_complete_proposed_request.json 순서로 보면 된다.
아직 직접 전송하거나 Git에 업로드하지 않았다.

## 나의 출력과 현지 입력

| 한수 출력 | 현지 입력 | 맞출 내용 |
| --- | --- | --- |
| profile.target.region | target.region | 춘천시 또는 강남구 |
| profile.target.age_group | target.age_group | 정수 10/20/30/40/50/60, 연령 구간 의미 확인 |
| profile.target.sex | 현재 없음 | 새 target.sex에 all/male/female 필수 |
| profile.period | risk_assessment.period | YYYY-MM |
| profile.risk.level/status | 동일 항목 | 완료·부분판정·보류 의미 유지 |
| analysis_id | risk_assessment.assessment_id | 성별 접미사까지 보존 |
| profile.target.sex | 현재 risk에는 없음 | risk_assessment.sex도 보존하고 target과 일치 검사 |
| profile.signals와 근거 설명 | risk_assessment.signals | 실제 변화율·단위·한계 보존 |
| profile.limitations | risk_assessment.limitations | 개인 고립 확정 금지·활동지역 한계 등 |
| profile.risk.model_version | 동일 항목 | activity-review-v2.2-sex-aware |
| 확인된 실제 욕구 | confirmed_support_needs | 분석으로 추정해 채우지 않음. 현재 빈 목록 |
| 민감도·배경·원인 가설 | 현재 전용 필드 없음 | handoff_records의 analysis_context에 별도 보관, 전달 방식 합의 |

risk-input-0.2는 사용자가 한수 출력의 기준으로 확정한 버전이다. 현지 현재 코드의 0.1과 혼동하지 않는다.
현재 0.1에는 성별 필드가 없다. 따라서 남녀 입력에서 성별을 제거해 호환시키지 않는다. 기존 계약용 예시는 합산 집단만 제공한다.

## 압축 파일 구성

- README_현지에게.md: 수정할 항목과 연결 순서.
- 분석결과_설명.md: 담당 분석과 실제 남녀 차이.
- 입출력_맞추기.md: 이 안내서.
- 상세_성별분석.md: 집계·산식·검증·한계를 더 자세히 설명한 문서.
- contracts/: 새 추천 입력 JSON Schema와 정욱 TargetProfile 계약.
- examples/: 여성 완료·남성 완료·3단계·부분판정·보류, 기존 합산 offline 예시.
- profiles/: 집단별 입력 216개.
- data/handoff_records.json: 각 집단의 profile, request_v02, analysis_context.
- data/sex_comparison.csv: 합산·남성·여성의 단계·상태·변화율 비교 72행.
- data/priority_sex.json: 남녀 24집단의 1차 순위.
- data/priority_aggregate.json: 합산 12집단의 별도 비교 순위.
- data/current_receiver_contract_check.json: 현지 현재 코드의 입력 검사 결과와 기준 커밋.
- ai/analysis_agent/: 우리 분석·연결 코드.
- scripts/integration/check_welfare_handoff.py: 외부 API 없이 수신 형식을 확인하는 도구.
- MANIFEST.json: 전달 파일 해시.

원본 자료·좌표별 자료·가상환경·.env·API 키는 없다.
실제 복지자원의 모집·성별 자격을 확인한 묶음은 아니다.

## 현지 쪽에서 필요한 변경

1. target.sex와 risk_assessment.sex를 받고 지역·연령과 함께 같은 집단인지 검사한다.
2. 새 버전을 수용하되 이전 0.1은 합산으로만 구분한다. 남녀 입력을 all로 바꾸지 않는다.
3. 모델 입력·응답·선택 목록 내보내기에도 성별을 보존한다.
4. 자원의 성별 자격은 공식 근거로 확인한다. 분석 대상의 성별만으로 자격·욕구를 확정하지 않는다.
5. 분석의 10코드는 10~19세인데 현재 추천은 0~19세다. 이 차이도 맞춘다.
6. 정욱의 기존 to_welfare_payload도 성별을 제거하므로 새 변환 함수로 교체하거나 같은 기능으로 수정한다.

새 예시를 현재 서버에 넣으면 400 오류로 거부되는 것이 정상이다.
우리 변환 함수가 현지 서버를 자동 수정하지는 않는다.
ZIP의 request_v02만 기준 추천 요청이다. handoff 전체 객체를 기존 HTTP 요청에 붙이지 않는다.

## API 키 없이 확인

압축을 푼 폴더에서 실행한다.

~~~powershell
python scripts/integration/check_welfare_handoff.py .
~~~

pydantic과 jsonschema가 필요하다. 자동 검색·모델 호출은 없다.
여성 완료 → 남성 완료 → 부분판정 → 보류 → 성별 불일치 거부 → 10대 범위 순서로 연결을 확인한다.
형식 검사와 추천 내용 검증은 별개다. 실제 API 연결은 현지가 기준 입력을 적용한 뒤 별도로 수행한다.
