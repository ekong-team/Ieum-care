# 분석 에이전트: Gemini·Tavily 연결

## 최신 상태: 사용자 승인 후 실제 연결 검증 완료

사용자가 춘천30대여성 집단 요약의 구체적인 외부 전송을 명시적으로 승인한 뒤, 2026-10-20 실제 Tavily 검색1회와 Gemini 검토1회를 수행했다. 이 승인은 이 집단·각1회 테스트 범위이며 다른 집단의 대량 전송 승인으로 확대하지 않는다. 아래의 키 미설정·승인 대기 기록은 해결 이전의 과정이다.

- 실제 결과: `data/processed/analysis_gemini_live_20261020/8212476d53351f72/`.
- 모델: gemini-3.5-flash-lite. 검토 상태 executed, 출력 검증 validated.
- 검색: 실제1회, 제공자 응답의 사용 크레딧1. 확보한 공식 발췌1개(행정안전부 주민등록 인구통계 안내 페이지).
- 토큰: 입력2020·출력53·합계2073. 실제 금액은 계산하지 않았으며 무료 과금 상태는 계정에서 확인해야 한다.
- Gemini는 E1·E2·E3를 강조 대상으로, C3 동반 위축·C4 지속 신호를 추가 검토할 기존 가설로 선택했다. 질문은 관측 범위·휴일/계절·업종/온라인 이동 확인이다. 새 원인을 확정한 것이 아니다.
- 전체216집단의 판정·팀 프로필·성별1차순위·합산순위는 오프라인 계산과 완전히 같았다. 저장 결과 재계산 검증216/24도 통과했다.
- 검색 품질 한계: 선택된 S1은 일반 통계 홈페이지여서 춘천의 2025년12월 숫자나 변화 원인을 입증하지 못했다. 게시일도 미확인이다. 모델의 출처 선택을 해당 월의 원인 검증으로 해석하면 안 된다. 새 수치 데이터는 추가되지 않았다.
- 개선 방향(다음 작업 제안): 인구·지역 경기·휴일 등 질문을 분리하고 구체적 통계표·해당 기간 보고서를 대상으로 검색한다. 일반 홈페이지는 탐색 경로로만 표시하고 수치·인과 근거에서 제외한다. 다운로드·병합은 지역·기간·단위·이용조건 확인 뒤 수행한다. 이번 승인 상한을 지키기 위해 추가 API 호출은 하지 않았다.
- `live_validation.json`에 연결 성공과 근거 부족을 함께 기록했다. Git push·키 공개는 하지 않았다.


2026-10-20 구현. 키 발급·계정 로그인은 사용자가 직접 한다. 키를 받거나 채팅에 붙여 넣지 않는다.

## 역할과 범위

1. 기존 통신·카드 집단 자료로 활동 위축 단계, 민감도, 근거 수치, 1차 순위를 계산한다.
2. 선택한 집단의 지역·기준월로 Tavily에 공식 자료 검색을 한 번 요청한다. 검색어에는 원본·좌표·결제 내역·성별 수치·위험 단계를 넣지 않는다.
3. Gemini에 선택 집단의 프로필·기존 가설·질문 코드·검색 발췌만 보내 강조할 근거, 검토할 가설, 확인 질문, 관련 출처 번호를 선택하게 한다.
4. 프로그램이 응답 형식과 모든 번호를 검증한다. 결과와 출처를 저장하고 계산을 다시 검증한다.

이 구현은 웹에서 숫자 데이터셋을 자동 다운로드·병합하는 기능이 아니다. 검색으로 찾은 자료는 참고 후보이며, 수치 지표에 반영하려면 기간·단위·지역·이용 조건을 별도로 검토해야 한다. 위험 단계·성별 분석·기존 우선순위는 언어모델이 바꾸지 못한다. 독립 원인 검증이나 개인 고립 판정이 추가된 것은 아니다.

## 모델을 고른 이유

기존 복지 Agent와 같은 Gemini 모델을 사용하되 설정·호출 코드는 분리했다. 분석 설정은 `ANALYSIS_GEMINI_MODEL`을 읽고 복지 설정 `GEMINI_MODEL`을 바꾸지 않는다. 2026-10-20 확인한 공식 요금표에는 `gemini-3.5-flash-lite`의 무료 텍스트 입출력 구간이 있다. 다른 모델로 자동 전환하지 않는다.

무료 모델명을 사용한다고 호출 비용 0원이 코드로 보장되지는 않는다. 키만으로 프로젝트의 과금 등급을 판별할 수 없으므로 AI Studio에서 Free Tier인지 직접 확인한다. Tavily도 계정의 무료 크레딧과 결제 설정을 확인한다. 코드는 자동 재시도·자동 심화 검색·유료 대체 모델·Google 검색 Grounding을 사용하지 않는다.

무료 Gemini 약관에는 입력·출력을 제품 개선에 사용하고 사람이 검토할 수 있다고 명시되어 있다. 원본·개인정보·좌표를 전송하지 않으며 집단별 요약만 보낸다. 집계 자료라는 이유만으로 공모전 자료의 외부 전송 권한이 자동 보장되는 것은 아니므로 제공자료의 이용 조건도 따른다.

## 키 준비

- Gemini: <https://aistudio.google.com/apikey>
- Tavily: <https://app.tavily.com/>

프로젝트 최상위 `Ieum-care/.env`에 다음 이름으로 직접 입력한다. `.env`가 이미 있으면 필요한 줄만 추가하고 기존 값을 덮어쓰지 않는다.

```dotenv
GEMINI_API_KEY=여기에_직접_입력
TAVILY_API_KEY=여기에_직접_입력
ANALYSIS_GEMINI_MODEL=gemini-3.5-flash-lite
```

실제 키가 없는 `.env.analysis.example`도 준비했다. `.env`는 Git 제외 대상이다. 키는 소스·보고서·스크린샷에 포함하지 않는다.

프로젝트 루트에서 값 없이 설정 여부만 확인한다.

```powershell
./.venv-agent/Scripts/python.exe -X utf8 -B scripts/integration/run_analysis_agent.py --check-config
```

## 첫 실제 실행

남녀 분석이 준비된 입력으로 춘천 30대 여성 한 집단만 외부 검토한다. 전체 216개 집단의 계산은 동일하게 실행하되, 외부 호출은 선택 집단에만 수행한다. 기준월과 ID는 반드시 입력에 존재해야 한다. API를 호출하려면 `--mode gemini`, `--allow-external`, `--analysis-id`를 명시해야 하고, Tavily 검색은 `--web-search`로 켠다.

```powershell
./.venv-agent/Scripts/python.exe -X utf8 -B scripts/integration/run_analysis_agent.py --input-folder data/processed/analysis_sex_inputs_20261019 --output data/processed/analysis_gemini_live_20261020 --period 202512 --mode gemini --web-search --analysis-id 202512_32010_30G_female --allow-external
```

키와 Free Tier 설정을 준비한 뒤 실행한다. 이 명령을 문서에 적었다고 실제 실행한 것은 아니다. Gemini만 시험하려면 `--web-search`를 빼면 되고 이 경우 Tavily 키가 없어도 된다. 대량 반복 호출은 구현하지 않았다.

## 출력 위치와 의미

지정한 출력 폴더의 `latest.json`이 성공한 결과 하위 폴더를 가리킨다. 기존 10월 19일 결과를 덮어쓰지 않는다.

```text
data/processed/analysis_gemini_live_20261020/
├─ latest.json
└─ 결과해시16자리/
   ├─ analysis_bundle.json       # 계산·해석·출처·실행 기록
   ├─ external_research.json     # 선택 집단의 검색 발췌·출처·모델 검토·호출 상태
   ├─ profiles/                 # 기존 팀 프로필 계약 유지
   ├─ priority_review.json      # 성별 1차 우선순위
   ├─ aggregate_priority_review.json
   ├─ report.md
   └─ verification.json
```

`execution.search_attempts`와 `gemini_attempts`는 호출 시도 횟수다. `confirmed_llm_responses`는 실제 전송 경로에서 JSON 응답을 수신한 횟수이며, 응답이 유효한지는 `model_review.status`와 수신 기록의 `output_status`를 함께 본다. 호출 실패나 잘못된 출력도 시도 횟수에서 지우지 않는다. HTTP 429·503·타임아웃은 자동 재시도하지 않는다. 검색 실패 시 모델을 호출하지 않고 기존 계산을 유지한다. 검색 결과가 정상적으로 비어 있으면 기존 내부 근거만 검토할 수 있다.

전체 분석 저장 성공은 외부 모델 성공을 뜻하지 않는다. 실제 검토 성공은 대상의 `model_review.status == executed`, 수신 기록의 `output_status == validated`로 확인한다. 가짜 응답 테스트는 `fixture_only`이며 실제 호출로 세지 않는다. 사용량은 제공자 응답에 있는 토큰 수·검색 사용량만 기록하고 비용을 임의로 0원 계산하지 않는다.

## 검색의 신뢰 범위

- 지자체·통계청·KOSIS·행안부·기상청·복지부·복지로 도메인만 허용한다. API 결과 URL도 HTTPS·호스트·포트를 다시 검사한다.
- 분석 기준월 말일을 검색 종료일로 사용하고, 종료일 뒤에 게시된 것으로 표시된 자료는 제외한다.
- 게시일 미확인 자료는 `date_unverified`로 남긴다. 게시일이 맞아도 본문의 통계 기준연도·집단·원인 관계가 자동 검증되는 것은 아니다. 과거 시점 재현이 엄밀하게 보장되지 않는다.
- 본문을 별도로 열어 검증하거나 데이터 파일을 가져오지 않으며 `verification=search_excerpt_only_not_independent_fact_check`로 표시한다.
- 검색 본문의 지시는 따르지 않도록 프롬프트에 명시한다. 실제 방어 경계는 허용 번호·엄격한 출력 규격·수치 수정 금지에 있다.
- 출처 선택은 관련성 선택이지 출처 내용에 대한 사실 보증이 아니다. 현재 공통 프로필에는 외부 발췌를 새 수치 근거 E번호로 넣지 않는다. 다음 Agent가 외부 자료까지 쓰려면 `external_research.json`을 별도 참고 입력으로 받아야 한다.

## 코드 위치

- `ai/analysis_agent/gemini_provider.py`: 설정 읽기, 고정 HTTPS API, 검색·출처 필터, 구조화 Gemini 요청, 호출 상한, 안전한 오류와 수신 기록.
- `ai/analysis_agent/reviewer.py`: 모든 제공자가 지켜야 하는 근거·가설·질문 검증.
- `ai/analysis_agent/workflow.py`: 선택적 검토와 실행 기록을 연결. 계산·순위는 기존 코드가 담당.
- `scripts/integration/run_analysis_agent.py`: 실행 옵션과 결과 저장.
- `scripts/integration/verify_analysis_agent.py`: 저장 결과 재계산 및 별도 검색 출력의 일치 검사.
- `tests/test_analysis_gemini.py`: 키 없이 전송 대체 함수를 주입하는 회귀 검사.

표준 라이브러리 HTTP를 사용해 SDK 의존성은 추가하지 않았다. 기존 복지 Agent의 추천용 출처 필터·모델 전용 함수는 분석 역할과 다르므로 직접 결합하지 않았다. 계정 로그인·키 발급·결제 설정은 자동화하지 않았다.

## 검증·문제 해결

최초 설정 확인에서 Gemini·Tavily 키 모두 미설정이었다. 사용자가 직접 발급해 `.env`에 넣기로 답했다. 키 값은 출력하지 않았다. 실제 API 응답의 품질·검색 관련성·무료 한도는 실제 실행 후 추가 확인할 사항이다.

Git 병합·복원 과정에서 Windows 줄바꿈이 변경되면 코드 해시가 달라질 수 있었다. 기존 결과 검증을 우회하지 않고 원래 줄바꿈을 복원했다. 이번 Gemini 기능 추가는 실제 코드 변경이므로 새 출력 폴더에서 다시 계산한다. 이전 ZIP·결과는 당시 코드 기준의 역사적 결과이며 최신 연결 기능이 포함되어 있지 않다.

테스트 임시폴더 권한 문제는 기존 기록대로 프로젝트 `.venv-agent/test_tmp`를 TEMP/TMP로 지정해 해결했다. 이 방법을 이번에 사용자가 새로 제안했다고 기록하지 않는다.

## 공식 근거

- [Gemini API 키](https://ai.google.dev/gemini-api/docs/api-key)
- [Gemini 요금표](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini 무료 서비스 데이터 이용 약관](https://ai.google.dev/gemini-api/terms)
- [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output)
- [generateContent API](https://ai.google.dev/api/generate-content)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)


## 이번 실행의 최종 상태

- 사용자가 두 키를 저장했다. 실제 위치가 `.env.analysis.example`였으므로 `.env`가 없는 것을 확인한 뒤 키를 `.env`로 옮기고 예시 파일의 키 값을 지웠다. 키 값은 출력하지 않았다.
- 설정 검사: Gemini·Tavily 모두 설정됨. `.env`가 Git 제외 대상임을 확인했다.
- 분석·성별·Gemini/Tavily·공통 계약·그래프·복지 브리지 관련 테스트 134개 모두 통과했다.
- 키를 사용하지 않는 실제 입력 재분석: 216개 집단, 우선순위 24개 재계산 검증 통과. 단계는 기존과 같고 완료173·부분7·보류36이다. 최신 폴더는 `data/processed/analysis_gemini_20261020/latest.json`이 가리킨다.
- 실제 호출 명령은 자동 승인 검토에서 실행 전에 거절됐다. 사유는 사용자가 API 사용·키 설정은 승인했으나 지역·연령·성별·위험 신호 요약의 구체적인 외부 전송 승인이 부족하다는 것이었다. 거절을 우회하지 않았다.
- 실제 Tavily/Gemini 호출은 0회다. 실모델 품질·키 유효성·실제 한도는 아직 확인하지 못했다.
- 구체적 전송 내용은 `data/processed/analysis_gemini_payload_review_20261020.json`에 저장했다. 이 미리보기는 인증 헤더와 키를 포함하지 않는다. 실제 Gemini 입력에는 추가로 Tavily의 공개 공식 자료 발췌 최대5개가 들어간다.
- 전송 승인 대기: Tavily에는 춘천·2025년12월 지역 통계 검색어와 검색 옵션을, Gemini에는 춘천30대여성 집단의 기존 프로필·4단계·카드 -6.62%·유동량 -4.57%·연속 비교2회·한계·가설·질문 목록과 공개 검색 발췌를 전송한다. 원본·좌표·개인 식별정보·전체216집단은 보내지 않는다.
- 새 코드·문서는 커밋하거나 push하지 않았다. 기존 현지 전달 ZIP에는 이번 연결 기능이 포함되지 않는다.
