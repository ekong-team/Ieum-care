# 신규 프로그램 기획 Agent 설계 (초안 v0.1)

작성: 김정욱 · 작성일: 2026-10-18 · 상태: 팀 검토 전 초안
관련 문서: [복지자원 추천 Agent](welfare_agent.md), 위험도 5단계 설계(`hyeonji/risk-model` 브랜치의 `docs/risk_model_design.md`)

## 1. 목적과 범위

복지자원 추천 Agent는 **이미 운영 중인 공식 자원**을 찾아 연결한다.
프로그램 기획 Agent는 그 자원으로 채워지지 않는 영역에 대해 **지금은 없는 새 프로그램**을 기획한다.
지역·연령대·성별·위험 원인과 최근 국내외 사례(트렌드)가 기획의 근거다.

| 구분 | 복지자원 추천 (장현지) | 프로그램 기획 (본 문서) |
| --- | --- | --- |
| 질문 | 지금 연결할 수 있는 자원은? | 기존 자원이 못 채우는 부분을 무엇으로 채울까? |
| 검색 대상 | 지자체·복지로 공식 안내 | 타 지자체 신규 사업·해외 사례·연구 보고서 |
| 출력 | 자원 목록 (`welfare-0.4`) | 기획안 2~3개 (`program-plan-0.1`) |
| 다음 단계 | 담당자 확인·연계 | 기획안 평가 Agent → 필요 시 재기획 |

하지 않는 것: 개인의 고립 여부·신청 자격 판단, 효과를 확정한 것처럼 표현하기, 실제 예산 확정.
기획안은 담당자 검토용 **초안**이며, 집계 데이터의 감소 신호를 개인의 결핍으로 바꾸지 않는다.
이 원칙은 복지 추천 Agent의 원칙과 같다.

## 2. 전체 흐름에서의 위치

```text
[1] 위험도 분류 (risk-model)
     월×지역×연령 → 1~5단계, 판정상태, 신호(소비·이동 감소), 관측 제한
          │
          ▼
  대상 프로필 = 지역 · 연령대 · (성별) · 위험 원인 가설 · 데이터 근거 수치
          │
    ┌─────┴──────────────────────────┐
    ▼                                ▼
[2-A] 복지자원 추천               [2-B] 프로그램 기획  ← 본 문서
 기존 공식 자원 검색               P1 컨텍스트 구성 (규칙)
    │                             P2 트렌드·사례 검색 (Tavily)
    └── 기존 자원 목록 ─────────→ P3 공백 분석 (규칙 + LLM)
                                  P4 기획안 생성 (Gemini)
                                  P5 근거 검증 (규칙)
                                       │
                                       ▼
                               [3] 기획안 평가 Agent
                                타깃 적합성·신규성·실현성·예산·성과지표
                                       │
                         점수 < 기준 ──┴── 통과
                              │              │
                   피드백 → P4 재기획(최대 1회)   ▼
                                       담당자 검토 화면·내보내기
```

- 2-A와 2-B는 같은 대상 프로필에서 출발하는 형제 노드다. 2-B는 2-A의 결과를 "이미 있는 것" 목록으로만 쓴다.
- 2-A가 실패하거나 0건이어도 2-B는 계속한다. 이때 신규성 근거는 `existing_resources_status: unavailable`로 표시한다.
- 코드는 `ai/program_planner/`에 새로 만든다. `ai/welfare_agent/`는 수정하지 않는다.

## 3. 입력 계약 `planner-input-0.1`

```json
{
  "schema_version": "planner-input-0.1",
  "target": {"region": "춘천시", "age_group": 20, "sex": "all"},
  "risk_assessment": { "...": "risk-input-0.1 형식 그대로 (welfare_agent.md 참고)" },
  "data_context": {
    "period": "2025-12",
    "features": [
      {"name": "통신_연령유동량_전월변화율", "value": -0.062},
      {"name": "카드1_전체_결제건수_전월변화율", "value": -0.041},
      {"name": "카드1_사회활동관련후보_건수전월변화율", "value": -0.083},
      {"name": "통신_지역공통_주말평일비", "value": 0.91}
    ],
    "source": "risk_features.csv",
    "is_example": false
  },
  "existing_resources": { "...": "복지 추천 선택 목록 JSON(welfare-0.4) 또는 null" },
  "constraints": {"budget_cap_krw": null, "duration_weeks": null, "delivery": "any"}
}
```

| 필드 | 규칙 |
| --- | --- |
| `target.region` | 춘천시·강남구 (복지 추천과 동일) |
| `target.age_group` | 10·20·30·40·50·60 (60 = 60대 이상) |
| `target.sex` | `male`·`female`·`all`. **현재 위험도 단위에 성별이 없어 기본값은 `all`** (8장 합의 항목) |
| `risk_assessment` | 없으면 일반 기획 모드. held/partial이면 원인 가설을 만들지 않고 일반 기획 + 확인 질문 |
| `data_context.features` | 기획안의 "문제 정의" 근거로만 사용. 값은 입력값 그대로 인용하고 LLM이 새 수치를 만들지 않음 |
| `existing_resources` | 공백 분석과 중복 검사에 사용. 없으면 신규성 검사는 `unavailable` |
| `constraints` | 모두 선택 사항. 예산 상한이 있으면 평가 Agent가 초과 여부를 검사 |

## 4. 위험 원인 분류 (초안)

위험도 모델은 원인이 아니라 **신호**를 준다. 기획에 쓰려면 신호를 "확인이 필요한 원인 가설"로 바꾸는 표가 필요하다.
아래는 팀 합의 전 초안이며, 모든 가설은 `hypothesis`로 표시한다.

| 코드 | 원인 가설 | 판단 근거 (입력 신호·특징) | 기획 방향 예시 |
| --- | --- | --- | --- |
| `C1_mobility` | 외출·이동 위축 | `movement_decline`만 해당 | 집 근처 소규모 거점, 찾아가는 방식, 이동 부담 낮추기 |
| `C2_social_consumption` | 관계형 활동 감소 | 사회활동관련후보(외식·카페, 문화·오락, 운동) 건수 감소가 전체 소비 감소보다 큼 | 함께 먹기·취미·운동 모임처럼 혼자 하던 활동을 함께 하는 방식으로 |
| `C3_overall_withdrawal` | 생활 전반 위축 | `activity_decline` (소비·이동 동시 감소) | 단계적 참여(온라인 → 소그룹 → 지역 활동), 낮은 진입 장벽 |
| `C4_prolonged` | 위축 장기화 | 4·5단계 (연속 동시 감소) | 정기 안부 + 관계 형성 결합, 기존 자원 연계 경로 포함 |
| `C5_weekend_gap` | 주말 공백 | 주말/평일 비 하락 (지역 공통값이라 보조 근거) | 주말 프로그램 편성 |
| `C0_unknown` | 원인 미확정 | 위험도 없음·보류·불완전 | 일반 예방형 기획 + 담당자 확인 질문 |

- 소비 감소만으로 경제적 어려움을 확정하지 않는다. 복지 추천의 `build_review` 원칙과 같다.
- 한 대상에 가설이 여러 개면 모두 전달한다. 기획안마다 어떤 가설을 다루는지 `risk_causes_addressed`에 명시한다.
- 확장 후보: 카드1에는 `TIME_GB`(6시간대)와 성별이 있다. 연령·성별별 야간 소비 비중을 특징으로 추가하면 "야간형 고립(C6)"도 다룰 수 있다. 1번 담당자와의 협의가 필요하다.

## 5. 노드 설계

### P1 컨텍스트 구성 (규칙, LLM 호출 없음)
- 입력을 검증한다. 형식이 다르면 400으로 처리하며, 복지 추천의 `validate_request`·`validate_risk`를 재사용한다.
- 4장 표로 원인 가설을 만든다.
- 근거 수치 목록을 만든다. 기획안에 인용할 수 있는 숫자는 이 목록에 있는 것뿐이다.

### P2 트렌드·사례 검색 (Tavily, 최대 2회)
| 검색 | 검색어 예시 | 설정 |
| --- | --- | --- |
| 국내 신규 사업 | `{연령 표현} 사회적 고립 예방 신규 프로그램 {원인 키워드} 지자체 사례` | 최근 1년(`time_range: year`), 도메인 제한 없음, 결과 8개 |
| 해외·연구 사례 | `{원인 키워드} loneliness intervention program young adults social prescribing` | 최근 2년, 결과 5개 |

- 출처는 등급으로 구분한다: `public`(go.kr, 공공기관), `research`(연구원·학술), `media`(언론), `other`. 기획안에는 등급이 함께 표시된다.
- 캐시: (지역·연령·원인코드) 키로 결과를 저장한다. 복지 추천처럼 메모리에만 두지 않고, 시연 재현성을 위해 `data/processed/planner_cache/`에 날짜와 함께 저장하는 방안을 검토한다.
- 한도(402/429/432/433)에 걸리면 중단한다. 다른 검색으로 자동 대체하지 않는다.

### P3 공백 분석 (규칙 + LLM 판단 일부)
- 기존 자원을 `support_purpose × 운영 방식(방문/모임/온라인/바우처) × 연령 일치`로 펼친다.
- 원인 가설별로 다음을 표시한다.
  - 대응하는 기존 자원이 있음: `covered`
  - 일부만 대응함: `partial`, 이유 포함 (예: 60대 이상 대상만 있음, 평일 낮에만 운영)
  - 대응하는 자원이 없음: `gap`
- 결과 예: `C2_social_consumption: gap — 춘천 20대 대상 기존 자원은 경제·일상 지원 위주이며 관계형 모임 없음`.
- 이 결과가 기획안의 "신규성 근거"이자 평가 Agent의 중복 검사 입력이 된다.

### P4 기획안 생성 (Gemini 1회, JSON 스키마 강제)
- 모델: `gemini-3.5-flash-lite`(무료 등급, 복지 추천과 동일), `temperature 0.5`. 다양성을 위해 추천보다 조금 높게 둔다.
- 서로 다른 방식의 기획안 **2~3개**를 생성한다 (예: 오프라인 모임형 / 온라인→오프라인 단계형 / 기존 자원 연계형).
- 프롬프트 원칙
  1. 수치는 P1 근거 목록에서만 인용한다.
  2. 참고 사례는 P2 검색 결과의 URL만 쓰고, 각 사례를 어떻게 바꿔 적용했는지 쓴다.
  3. `gap`·`partial` 영역을 우선으로 다룬다. `covered` 영역을 다룰 때는 기존 자원과 연계한다고 명시한다.
  4. 효과를 단정하는 표현("고립 해소")은 쓰지 않는다. 대신 "측정할 지표"를 쓴다.
  5. 예산 단가를 모르면 `null`로 두고 산정 근거가 필요하다고 쓴다. 숫자를 지어내지 않는다.
- 재기획 모드: 평가 Agent의 피드백(`revision_requests`)을 함께 넣어 **해당 기획안만** 다시 생성한다. 최대 1회.

### P5 근거 검증 (규칙)
| 검사 | 실패 시 |
| --- | --- |
| 인용 수치가 P1 근거 목록과 일치 | 해당 기획안 제외 |
| 참고 사례 URL이 P2 검색 결과에 있음 | 해당 사례 제거, 사례가 0개면 경고 |
| 기존 자원과 이름·핵심 활동이 거의 같음 | `duplicate_suspected` 경고 |
| 금지 표현(자격 확정, 효과 단정, 개인 진단) | 해당 기획안 제외 |
| 필수 필드 누락·형식 오류 | 전체 결과 미사용 (복지 추천과 동일한 방식) |

## 6. 출력 계약 `program-plan-0.1`

```json
{
  "schema_version": "program-plan-0.1",
  "mode": "live",
  "generated_at": "2026-10-18",
  "target": {"region": "춘천시", "age_group": 20, "sex": "all"},
  "risk_causes": [{"code": "C2_social_consumption", "basis": "hypothesis", "evidence": ["카드1_사회활동관련후보_건수전월변화율 = -0.083 (2025-12)"]}],
  "gap_analysis": {"existing_resources_status": "available", "items": [{"cause": "C2_social_consumption", "coverage": "gap", "reason": "..."}]},
  "plans": [
    {
      "plan_id": "P-20261018-01",
      "title": "춘천 청년 '한 끼 같이' 저녁 식탁",
      "one_liner": "혼밥 대신 주 1회 6인 저녁 식사로 시작하는 관계 회복 모임",
      "format": "offline_group",
      "risk_causes_addressed": ["C2_social_consumption"],
      "problem_statement": "...",
      "data_evidence": [{"feature": "카드1_사회활동관련후보_건수전월변화율", "value": -0.083, "period": "2025-12"}],
      "novelty": {"gap_items": ["C2_social_consumption"], "differs_from_existing": "기존 자원은 경제 지원 중심이며 정기 모임형 없음"},
      "activities": [{"name": "...", "description": "...", "frequency": "주 1회", "time_slot": "평일 19~21시", "format": "offline"}],
      "schedule": {"duration_weeks": 8, "sessions": 8},
      "operation": {"lead_candidates": ["춘천시 청년센터(확인 필요)"], "linked_existing_resources": []},
      "recruitment": ["..."],
      "budget_items": [{"item": "식비", "unit": "1인 1회", "quantity": 48, "unit_cost_krw": null, "basis": "단가 확인 필요"}],
      "kpis": [
        {"name": "재참여율", "definition": "2회 이상 참여자 비율", "data_source": "운영 기록"},
        {"name": "집단 사회활동 소비 변화", "definition": "운영 다음 달 사회활동관련후보 건수 전월변화율", "data_source": "risk_features"}
      ],
      "trend_references": [{"title": "...", "url": "...", "year": 2026, "grade": "public", "how_applied": "..."}],
      "risks_and_mitigations": [{"risk": "초기 참여 저조", "mitigation": "..."}],
      "assumptions": ["..."],
      "status": "draft_needs_review"
    }
  ],
  "warnings": ["집계 신호 기반 가설이며 개인의 고립·자격을 판단하지 않음"],
  "search": {"queries": ["..."], "credits": 2, "cache_hit": false},
  "model": "gemini-3.5-flash-lite"
}
```

이 형식이 **평가 Agent의 입력**이 된다. 담당자가 직접 쓴 기획안도 같은 형식으로 변환해 평가한다. 화면에 입력 폼을 두고, 필수 필드만 받는다.

## 7. 평가 Agent와의 연결 (요약, 상세는 별도 문서)

| 평가 축 | 방식 | 사용 필드 |
| --- | --- | --- |
| 타깃 적합성 | 규칙: 대상 연령·지역·시간대가 위험 집단·신호와 일치하는지 | `target`, `activities.time_slot`, `risk_causes_addressed` |
| 신규성 | 규칙: `gap_analysis`의 `gap` 영역을 다루는지, 중복 의심 여부 | `novelty`, `gap_analysis` |
| 근거성 | 규칙: 데이터 근거·참고 사례 수와 출처 등급 | `data_evidence`, `trend_references` |
| 실현 가능성 | LLM (생성과 다른 평가 프롬프트) | 전체 |
| 예산 | 규칙 계산 + 단가 검색: 총액, 1인당 비용, 상한 초과 여부 | `budget_items`, `constraints` |
| 측정 가능성 | 규칙: 데이터로 측정 가능한 KPI가 1개 이상인지 | `kpis` |

- 점수가 기준 미만이면 `revision_requests`(축별 구체적 수정 요구)를 P4로 돌려보낸다. 재기획은 최대 1회다.
- 원안과 수정안의 점수를 나란히 보존한다. 이것이 3번 역할의 "개선 전후 비교"가 된다.
- 생성과 평가가 같은 모델이라 점수가 후해질 위험이 있다. 그래서 점수의 대부분을 규칙 계산으로 만들고, LLM 점수는 비중을 낮게 두며 따로 표시한다.

## 8. 팀 합의가 필요한 항목

| # | 항목 | 상대 | 임시 기본값 |
| --- | --- | --- | --- |
| 1 | 위험도 결과에 성별 단위를 추가할 수 있는지 | 장현지(1번) | `sex: all` |
| 2 | 4장 원인 분류 표와 판단 근거 | 장현지·김한수 | 초안 표 사용 |
| 3 | 위험도 결과에서 `data_context.features`를 꺼내는 방식 | 장현지 | 예시 입력으로 연결 확인 |
| 4 | 복지 추천 선택 목록 JSON을 기획 입력으로 쓰는 것 | 장현지(2-A) | `welfare-0.4` 그대로 사용 |
| 5 | 평가 축과 통과 기준 점수 | 김한수(3번 공동) | 7장 표 |
| 6 | `risk-model` 브랜치의 main 병합 시점 | 장현지 | 병합 전에는 예시 입력 사용 |

## 9. 검증 계획

추천 품질처럼 정답이 없는 영역이다. 그래서 **"잘못된 기획을 잡아내는가"**와 **"근거가 추적 가능한가"**를 검증한다.

1. **자동 테스트 (가짜 응답)**: 입력 검증, 원인 가설 생성, 공백 분석, P5 검증 규칙, 한도 초과 중단, 재기획 1회 제한.
   형식은 `tests/test_welfare_live_agent.py`와 같게 한다.
2. **시나리오 세트 `tests/fixtures/planner_cases.json`**: 복지 추천의 S01~S14와 같은 방식이다.
   - P01 춘천 20대 사회활동 소비 감소 → C2, 관계형 기획
   - P02 강남 60대 이상 4단계 → C4, 기존 돌봄 자원 연계 포함
   - P03 판정 보류 → 원인 가설 없음, 일반 예방형 + 확인 질문
   - P04 기존 자원이 해당 원인을 이미 충족 → `covered`, 연계형 기획
   - P05 LLM이 근거에 없는 수치 인용(가짜 응답) → 해당 기획안 제외
   - P06 검색 결과에 없는 URL 인용(가짜 응답) → 사례 제거
   - P07 기존 자원과 같은 이름의 기획안 → 중복 경고
   - P08 예산 상한 초과 → 평가에서 감점, 재기획 요청
3. **실제 호출 검증 문서 `docs/program_planner_validation.md`**: 대표 대상 4개(춘천·강남 × 20대·60대 이상)로 실행한다. 출처 원문 대조, 비용·지연, 사람 검토 결과를 기록한다.
4. **사람 검토 루브릭**: 팀원 3명이 기획안을 서로 모른 채로 1~5점으로 채점하고, 평가 Agent 점수와의 순위 일치를 확인한다. 소규모 검증이라는 한계를 함께 적는다.

## 10. 파일 구조와 구현 순서

```text
ai/program_planner/
├─ contract.py        # planner-input / program-plan 검증, 원인 분류 표
├─ context.py         # P1 컨텍스트·근거 수치 구성
├─ trend_search.py    # P2 Tavily 검색·출처 등급·캐시
├─ gap_analysis.py    # P3 공백 분석
├─ planner.py         # P4 Gemini 생성·재기획, P5 검증, 진입점 plan_programs()
└─ prompts.py         # 생성 프롬프트
ai/pipeline.py        # 위험도 → (추천, 기획) → 평가 → 재기획 오케스트레이터
backend/server.py     # POST /api/program/plan, /api/program/evaluate 추가
frontend/             # '신규 프로그램 기획' 메뉴, 추천 결과에서 이어가는 버튼
docs/program_planner_design.md (본 문서) · docs/program_planner_validation.md
tests/test_program_planner.py · tests/fixtures/planner_cases.json
```

| 순서 | 작업 | 완료 기준 |
| --- | --- | --- |
| 1 | `contract.py` + 예시 입력·출력 JSON | 팀 공유, 합의 항목 회신 |
| 2 | P1·P3 (규칙) + 테스트 | P01~P04 시나리오 통과 |
| 3 | P2·P4·P5 (실호출, 가짜 응답 테스트) | P05~P07 통과, 실호출 1회 성공 |
| 4 | API·화면 연결 | 추천 결과 → 기획안 화면에서 확인 |
| 5 | 평가 Agent + 재기획 루프 | P08 통과, 개선 전후 점수 표시 |
| 6 | 실제 호출 검증 문서·발표 자료용 사례 정리 | 대표 대상 4개 결과 기록 |

## 11. 비용과 운영 한도

- 1회 실행당 Tavily 최대 2회(기본 검색, 1크레딧씩)와 Gemini 1회. 재기획 시 Gemini 1회가 추가된다.
- 무료 등급만 사용하고 결제 등급은 확인·변경하지 않는다. 키는 서버에서만 읽는다.
- 검색어에는 지역·연령·원인 키워드만 넣는다. 위험도 원본 수치나 자유 입력은 검색 업체에 보내지 않는다.
