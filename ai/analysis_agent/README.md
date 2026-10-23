# 데이터 분석 에이전트

통신·카드 집계로 활동 위축 단계, 관측 기반 원인 가설, 1차 우선 검토 순위를 만든다. 사회적 고립 확정·개인 확률을 산출하지 않는다.

## 파일

| 파일 | 역할 |
| --- | --- |
| inputs.py | 분석 기준·입력 읽기·집단 및 수치 검증 |
| assessment.py | 1~5단계와 완료·부분판정·보류 계산 |
| interpretation.py | 수치 근거·원인 가설·인구와 달력 배경 |
| priority.py | 동일 기준월의 1차 순위 |
| workflow.py | LangGraph 계산·검색 판단·조건부 재검색·순위 실행 |
| model.py | Gemini·Tavily 호출과 모델 응답 검증 |
| research.py | 공식 자료 검색 계획·발췌 검사·설명 보고서 |
| agent.py | 공통 프로필과 추천 입력, recommend_from_analysis() |

## 실행

프로젝트 루트, Python3.12 기준. 분석 환경 의존성은 requirements-agent.txt와 requirements-analysis.txt에 있다.

```powershell
python scripts/data_processing/build_sex_features.py
python scripts/integration/run_analysis_agent.py
```

입력은 data/processed/analysis_inputs의 features.csv·sensitivity.csv·context.json, 결과는 data/processed/analysis_current다. latest.json이 최신 결과 폴더를 가리킨다. 원본·가공 결과·키는 Git에 포함하지 않는다.

검증은 `python scripts/integration/verify_analysis_agent.py`로 실행한다. 기본 분석은 외부 API를 호출하지 않는다. 선택적 모델 검토에는 --mode gemini, --analysis-id, --allow-external을 명시한다. 검색이 필요하면 --web-search를 함께 지정한다. 키는 프로젝트 .env에 저장한다.

자세한 분석 기준은 [분석 설명](../../docs/analysis.md)을 참고한다.

검색을 허용한 실행의 기본은 adaptive다. Gemini가 기존 배경을 보고 검색 생략 또는 질문 최대2개를 선택한다. 코드는 출처를 검사하고 부족하면 검색어를 바꿔 질문별1회 재검색한다. 한 집단 Tavily최대3회·Gemini계획/최종검토 합계최대2회이며 인증·한도 오류를 무한 재시도하지 않는다. 부분판정·보류는 웹으로 원본 관측을 대체하지 않는다. basic/focused는 이전 시험 재현용 명시 모드다.

```powershell
python scripts/integration/run_analysis_agent.py --mode gemini --web-search --analysis-id 202512_32010_30G_female --allow-external
```

흐름: calculate → describe → research_decide → (검색 필요 시 research_search → research_check → 제한 내 재검색) → interpret → first_priority. 검색 판단·검색어·재검색 이유·종료 사유는 실행 기록에 남긴다. 출처 검사는 참고 후보의 최소 조건이며 인과관계 검증이 아니다.

adaptive 검색 결과는 공식 HTML 본문과 연결된 PDF 첨부까지 수집한다. 한 집단 실행에서 문서 GET 최대4회(리디렉션 포함), PDF 추출 최대2개, 파일당30MB·150페이지까지다. 한국은행·강원관광재단도 공식 검색 범위에 포함한다. 다운로드는 API 키 없이 수행하고 URL·본문 SHA256·페이지·성공/실패를 기록한다. 캐시 재사용 시 SHA256을 검사하며 GET을 새 호출로 세지 않는다.

이미지형 PDF는 OCR하지 않고 ‘본문 미확인’으로 남긴다. 텍스트 PDF도 표 행·열 대응을 검증한 수치 데이터가 아니므로 위험 계산에 자동 병합하지 않는다. 광역 보고서는 광역 배경으로 표시하고 대상 지역·성별·연령 수치와 구분한다. `external_research.json`과 `analysis_explained.md`에서 수집 상태를 확인한다. basic/focused 모드는 이 문서 수집을 사용하지 않는다.

2025-12 춘천 경제 검토에는 앞서 원문을 확인한 한국은행 보고서 주소를 등록했다. 검색 자동 발견과 구분하고 현재 원문 SHA256이 확인본과 같을 때만 본문을 사용한다. 기간·지역이 다르면 재사용하지 않는다. 다음 질문에서 등록 출처를 읽어야 하면 일반 페이지의 본문 GET을 보류해 한도를 먼저 소진하지 않는다. 최종 인용은 여전히 모델의 문장과 제공 발췌를 대조하므로 원문 확보 후에도 탈락할 수 있다.

React의 분석 탭에서 기본 재분석과 선택 집단 외부 검토를 실행할 수 있다. 실행·화면 설명은 frontend/README.md를 참고한다. 서버 결과에 원본 경로·API 키를 노출하지 않고, 검증된 같은 배치의 추천 입력만 연결한다. 기획·평가·수정 및 최종2차순위는 이 분석 모듈의 범위가 아니다.
