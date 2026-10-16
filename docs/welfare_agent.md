# 복지자원 추천 연결 초안

현재 단계는 **화면 → API → 공식 복지자원 후보 조회 → 선택 결과 내려받기** 연결이다.
지역·연령·지원 목적으로 필터링한다. LLM 추천 Agent, 위험도 기반 우선순위와 효과 검증은 아직 구현하지 않았다.
정제·위험도 계산과 프로그램 기획 로직은 변경하지 않는다.

## 실행과 파일

프로젝트 최상위에서 `python backend/server.py` 실행 후 <http://127.0.0.1:5175/#recommendations> 접속.
추가 패키지·API 키는 필요 없다. `--port 5176`처럼 다른 포트를 지정할 수 있다.
서버는 로컬 개발용이며 127.0.0.1에서 frontend 폴더만 제공한다. 외부 배포용 서버가 아니다.

| 파일 | 역할 |
| --- | --- |
| `ai/welfare_agent/recommender.py` | 요청 검증·지역/연령대/목적 필터·일치 근거 |
| `ai/welfare_agent/welfare_resources.json` | 공식 안내에 근거한 자원 6개와 출처·확인 상태 |
| `backend/server.py` | 화면 및 JSON API 제공 |
| `frontend/app.js` | API 호출·로딩·오류/재시도·선택/내려받기 |
| `tests/test_welfare_agent.py` | 필터·계약·출처와 HTTP 연결 검증 |

## 요청

`POST /api/welfare/recommendations`, `Content-Type: application/json`

```json
{
  "target": {"region": "춘천시", "age_group": 60, "purpose": "all"},
  "risk_assessment": null
}
```

- 지역: 춘천시 또는 강남구. 원본 관측 지역이 주민 거주지라는 뜻은 아니다. 개인 거주지를 확인해야 한다.
- 연령대: 정수 10/20/30/40/50/60. 각각 20대 미만/20대/30대/40대/50대/60대 이상. 개인 나이가 아니다.
- 목적: all/connection/daily/wellbeing.
- 위험도: 현재 null만 허용. 임의 위험 입력을 무시한 채 추천하지 않고 400으로 거절한다.
- 지정되지 않은 필드·누락·다른 형식은 400. JSON 외 형식은 415, 본문 크기 제한은 16KiB.

## 응답 및 기획 전달

- `schema_version`: welfare-0.2. 이전 demo 계약을 교체한 협업용 초안이다.
- `is_demo`: false. `recommendation_method`: official_candidate_filter_v1. `catalog_version`: official-seed-2026-10-16.
- `target`, `risk_assessment`: 조회 집단과 null 위험도.
- `resources`, `total`: 결과 목록과 개수. 일치가 없어도 정상 200, 빈 배열을 반환한다.
- 각 자원: 식별자·지역·설명·지원 목적·조건·운영 방식·일치 근거(`match_reasons`)·확인 사항.
- `eligibility_status`: needs_confirmation. 개인 신청 자격은 판정하지 않는다.
- `age_match`: overlap(집단 연령 구간과 겹침)/partial(일부만 겹침)/unknown(미명시 기준). 어느 것도 자격 확정이 아니다.
- `source`: official_local_government, 공식 URL·제목·페이지 확인일(checked_at)·페이지 수정일(page_updated_at)·검토 메모.
- `application_method`: 공식 안내의 신청 절차 요약. 온라인 직접 신청 경로를 확정하지 않아 `application_url`은 null이다. 출처 URL을 신청 링크로 오인하지 않는다.
- `availability_status`: needs_confirmation. 현재 모집·예산·운영 확인 전이다.
- `warnings`: 과거 안내 가능성·현재 운영 미확인·자격/순위 미판정·미연동에 관한 주의사항.

선택 목록 JSON은 응답 메타데이터와 주의사항을 유지하고 선택한 자원만 남긴다. `total`은 선택 개수로 바꾸고 `exported_at`을 추가한다. 기획 담당자가 향후 받을 데이터의 초안이며 현재는 로컬 파일만 생성한다.
화면은 조회 중 중복 요청을 막고, 실패를 빈 결과와 구분하며, 재조회 시 이전 선택을 제거한다. 결과는 HTML 문자열로 실행하지 않도록 이스케이프한다.

## 검증 및 다음 단계

```bash
python -m unittest tests.test_welfare_agent -v
```

## 수집한 공식 자원과 해석 범위

2026-10-16에 아래 안내를 열어 필요한 사실만 요약했다. 원문 전체나 첨부물을 복제하지 않았다. 목적 분류와 검토 포인트는 프로젝트의 편집 기준이며 공식 적합성 판정이 아니다.

| 지역 | 자원 | 공식 출처 |
| --- | --- | --- |
| 춘천 | 노인맞춤돌봄서비스 | [춘천시 복지포털](https://www.chuncheon.go.kr/new-welfare/Single-person/senior/comprehensive-care-service/) |
| 춘천 | 일상돌봄서비스 | [춘천시 복지포털](https://www.chuncheon.go.kr/new-welfare/Single-person/youth-old/care-service/) |
| 춘천 | 고독사 예방 사업 | [춘천시 복지포털](https://www.chuncheon.go.kr/new-welfare/Single-person/youth-old/prevention-lonely-death/) |
| 춘천 | 우유배달(안부확인)서비스 | [춘천시 복지포털](https://www.chuncheon.go.kr/new-welfare/Single-person/milk-delivery/) |
| 강남 | 노인맞춤돌봄서비스 | [강남구청, 해당 서비스 항목](https://www.gangnam.go.kr/board/senior_support/list.do?mid=id02_01050501) |
| 강남 | 정신건강 심리상담 바우처사업 | [강남구보건소](https://health.gangnam.go.kr/web/business/mental/mind/sub01.do) |

페이지를 열어본 날짜와 서비스가 최신 기준으로 운영됨을 확인한 날짜는 다르다. 춘천 안내는 수정일이 2025년이고 강남 노인 안내에도 2025년 소득표가 있어 현행 요건은 재확인 대상으로 남겼다. 금액·지원 정원은 자동 추천/예산 계산에 사용하지 않는다. 모든 자원은 현재 모집 미확인 상태다.

집단은 20대 미만=0~19, 20~50대=각 10년, 60대 이상=60세 이상으로 비교한다. 65세 이상 서비스와 60대 이상 집단은 partial이다. 19~64세 서비스와도 60대 이상은 partial이다. 명시된 연령 구간이 전혀 겹치지 않으면 제외한다. 미명시 연령은 임의로 생성하지 않고 unknown 확인 후보로 남긴다. 구간은 유형별 조건을 대신하지 않는다.

종료 상태이거나 명시된 접수 종료일이 지난 자원은 제외한다. 종료일 미확인은 상시 모집으로 간주하지 않는다. 현재 목록에 모집 종료일을 확정한 자원은 없다. 현재 시각은 한국 날짜로 비교한다. 작은 초기 목록이며 빈 결과는 지역에 서비스가 없다는 뜻이 아니다.

## 다음 작업

기관 확인을 통해 현행 요건·모집 기간·제공 범위를 보완하고 강남 관계 형성 자원 등 목록의 빈 영역을 확장한다.
위험도 담당자와 지역/연령/기준 월/판정 상태/주요 신호/관측 제한/모델 버전을 합의하고, 기획 담당자와 전달 형식을 합의한다. 단계가 높다는 이유만으로 특정 프로그램의 자격을 확정하지 않는다.
그 후 추천 기준과 근거를 구현하고, 필요하면 LLM으로 근거 설명을 보완한다. 프로그램 기획·재작성은 별도 후속 작업이다.
