"""평가 노드 ⑤의 규칙 축 (설계 문서 5.5). 규칙 5축(85점) + LLM 1축(실현 가능성, feasibility.py).

축마다 (점수, 이유, 개선 요청)을 만든다. 개선 요청은 축 점수가 만점의 60% 미만일 때만,
그리고 기획 생성(LLM)이 실제로 고칠 수 있는 내용만 낸다 (예: 단가 미확정은 요청하지 않는다).
축별 세부 규칙은 docs/evaluation_rules.md에 표로 공개한다 (재현 가능한 설명).

1. 타깃 적합성(25): 원인 대응 10 + 시간대 적합 10 + 형식 적합 5
2. 신규성(20): 공백 대응 12 + 중복 없음 8
3. 근거성(15): 원인별 근거 연결 9 + 참고 사례 6 (사례 검색이 없었으면 근거 연결만으로 15점 환산)
4. 예산(15): 항목 구성 5 + 회차 연동 5 + 단가 확정 5 (단가 미확정은 감점만 하고 개선 요청은 내지 않는다)
5. 측정 가능성(10): 집단 단위 데이터 KPI 5 + 과정 KPI 5
진입점 evaluate_plans()가 규칙 5축과 LLM 1축(feasibility.py)을 합쳐 PlanEvaluation을 만든다.
"""

from dataclasses import dataclass, field
import re

from ai.contracts import AXIS_MAX, CAUSE_LABELS, AxisScore, PlanEvaluation, ProgramPlan, RevisionRequest, summarize
from ai.nodes.context import NodeContext
from ai.nodes.feasibility import review_feasibility, unavailable
from ai.nodes.grounding import check_duplicates
from ai.nodes.planner import open_gaps

REQUEST_BELOW = 0.6  # 축 점수가 만점의 60% 미만이면 개선 요청을 낸다


@dataclass
class AxisResult:
    """축 하나의 채점 결과. 진입점이 AxisScore와 RevisionRequest로 나눠 담는다."""

    score: AxisScore
    requests: list[RevisionRequest] = field(default_factory=list)


def finish(axis: str, points: float, reasons: list[str], fixes: list[str]) -> AxisResult:
    """점수를 만점 안으로 자르고, 60% 미만일 때만 고칠 거리(fixes)를 개선 요청으로 바꾼다."""
    points = round(min(max(points, 0.0), AXIS_MAX[axis]), 2)
    requests = ([RevisionRequest(axis=axis, request=fix[:500]) for fix in fixes]
                if points < AXIS_MAX[axis] * REQUEST_BELOW else [])
    return AxisResult(AxisScore(axis=axis, score=points, method="rule", reasons=reasons), requests)


# ── 1. 타깃 적합성 ───────────────────────────────────────────────────────────────
WEEKDAYS = ("월", "화", "수", "목", "금")
DAY = re.compile(r"([월화수목금토일])요일|평일|주중|주말")
HOUR = re.compile(r"(오전|오후|저녁|밤|새벽)?\s*(\d{1,2})(?=\s*(?:시|:|~|-))")
# 연령별로 피할 시간대. (평일에만 해당하는지, 시작 시각, 끝 시각, 이유)
BUSY = {
    10: (True, 9, 16, "수업 시간"),
    20: (True, 9, 18, "근로·학업 시간"),
    30: (True, 9, 18, "근로 시간"),
    40: (True, 9, 18, "근로 시간"),
    50: (True, 9, 18, "근로 시간"),
}
LATE_FOR_SENIORS = 21  # 60대 이상은 21시 이후·6시 이전 이동 부담
# 원인별로 잘 맞는 운영 방식. C0(원인 미확정)은 모든 방식을 인정한다.
FORMAT_FIT = {
    "C1_mobility": {"outreach", "online", "hybrid"},
    "C2_social_consumption": {"offline_group", "hybrid"},
    "C3_overall_withdrawal": {"hybrid", "outreach"},
    "C4_prolonged": {"linked", "outreach"},
    "C5_weekend_gap": {"offline_group", "hybrid"},
}
FORMAT_LABELS = {"offline_group": "오프라인 모임", "online": "온라인", "hybrid": "온·오프라인 단계형",
                 "outreach": "찾아가는 방식", "linked": "기존 자원 연계"}


def read_slot(text: str) -> tuple[bool | None, int | None]:
    """'목요일 오후 2시~3시' → (평일만인지, 시작 시각 24시간제). 읽지 못한 값은 None.

    평일과 주말이 함께 적혀 있으면('평일 저녁 또는 주말') 주말 선택지가 있으니 평일만으로 보지 않는다.
    """
    days = set()
    for match in DAY.finditer(text):
        word = match.group(1) or match.group()
        days.add("weekday" if word in WEEKDAYS or word in ("평일", "주중") else "weekend")
    weekday_only = None if not days else days == {"weekday"}
    hour = None
    match = HOUR.search(text)
    if match:
        prefix, hour = match.group(1), int(match.group(2))
        if prefix in ("오후", "저녁", "밤") and hour < 12:
            hour += 12
    return weekday_only, hour


def slot_problem(text: str, age_group: int) -> str | None:
    """대상 연령에 맞지 않는 시간대면 이유를, 맞거나 판단할 수 없으면 None."""
    weekday_only, hour = read_slot(text)
    if hour is None:
        return None  # 시각을 읽지 못하면 감점하지 않는다 (확인 필요로만 남김)
    if age_group == 60:
        return "야간 이동 부담" if hour >= LATE_FOR_SENIORS or hour < 6 else None
    weekday_rule, start, end, reason = BUSY[age_group]
    if weekday_rule and weekday_only and start <= hour < end:
        return reason
    return None


def target_fit(plan: ProgramPlan, planning) -> AxisResult:
    hypotheses = [c.code for c in planning.causes]
    addressed = [code for code in hypotheses if code in plan.risk_causes_addressed]
    cause_points = 10 * len(addressed) / len(hypotheses) if hypotheses else 10
    missing = [CAUSE_LABELS[code] for code in hypotheses if code not in addressed]

    age = planning.profile.target.age_group
    problems = [(a.name, a.time_slot, slot_problem(a.time_slot, age)) for a in plan.activities]
    bad = [(name, slot, why) for name, slot, why in problems if why]
    unread = [name for name, slot, _ in problems if read_slot(slot)[1] is None]
    slot_points = 10 * (len(problems) - len(bad)) / len(problems)

    unfit = [code for code in plan.risk_causes_addressed
             if code != "C0_unknown" and plan.format not in FORMAT_FIT.get(code, set())]
    format_points = 5 * (1 - len(unfit) / len(plan.risk_causes_addressed))

    reasons = [f"원인 대응 {len(addressed)}/{len(hypotheses)}" + (f" (빠짐: {', '.join(missing)})" if missing else ""),
               f"시간대 적합 {len(problems) - len(bad)}/{len(problems)}"
               + "".join(f" · '{name}' {slot}: {why}" for name, slot, why in bad)
               + (f" · 시각 확인 필요: {', '.join(unread)}" if unread else ""),
               f"형식 '{FORMAT_LABELS[plan.format]}': "
               + (f"{', '.join(CAUSE_LABELS[c] for c in unfit)}에 덜 맞음" if unfit else "적합")]
    fixes = [f"원인 가설 {', '.join(missing)}도 다루세요."] if missing else []
    fixes += [f"활동 '{name}'({slot})은 {age}대에게 {why}입니다. 저녁·주말로 옮기세요." for name, slot, why in bad]
    fixes += [f"{CAUSE_LABELS[code]}에는 {', '.join(repr(FORMAT_LABELS[f]) for f in sorted(FORMAT_FIT[code]))} 형식이 더 맞습니다."
              for code in unfit[:1]]
    return finish("target_fit", cause_points + slot_points + format_points, reasons, fixes)


# ── 2. 신규성 ────────────────────────────────────────────────────────────────────
DUPLICATE_PENALTY = 4  # 중복 의심 1건당. 2건이면 8점이 모두 빠진다


def novelty(plan: ProgramPlan, planning) -> AxisResult:
    """기존 자원이 못 채우는 부분(공백)을 다루는지, 기존 자원과 겹치지 않는지.

    공백 판정은 gap_analysis 결과를 그대로 쓴다. 중복은 근거 검증과 같은 함수로 다시 확인한다
    (평가 입력에는 근거 검증 리포트가 없고, 순수 규칙이라 다시 돌려도 비용이 없다).
    """
    open_causes = open_gaps(planning)
    addressed_open = [code for code in open_causes if code in plan.risk_causes_addressed]
    covered = [g.cause for g in planning.gaps if g.coverage == "covered"]
    linked = plan.format == "linked" or bool(plan.operation.linked_existing_resources)
    fixes = []
    if addressed_open:
        gap_points = 12
        gap_reason = f"공백 원인 대응: {', '.join(CAUSE_LABELS[c] for c in addressed_open)}"
    elif open_causes:
        gap_points = 0
        gap_reason = f"공백 원인({', '.join(CAUSE_LABELS[c] for c in open_causes)})을 다루지 않음"
        fixes.append(f"기존 자원이 채우지 못하는 {', '.join(CAUSE_LABELS[c] for c in open_causes)}을(를) 다루세요.")
    elif covered:
        # 공백이 없으면 새 프로그램보다 기존 자원과 이어 주는 방식이 신규성 있는 대응이다.
        gap_points = 8 if linked else 4
        gap_reason = "확인된 공백 없음 · " + ("기존 자원 연계 포함" if linked else "기존 자원과 연계하지 않음")
        if not linked:
            fixes.append("기존 자원이 이미 대응하는 원인입니다. 기존 자원과 연계하는 방식을 포함하세요.")
    else:
        # 기존 자원을 확인하지 못했다. 기획안 탓이 아니므로 절반을 주고 요청하지 않는다.
        gap_points = 6
        gap_reason = "공백 미확인 (기존 자원 조회 실패) · 담당자 확인 필요"

    duplicates = check_duplicates(plan, planning.existing)
    duplicate_points = max(0, 8 - DUPLICATE_PENALTY * len(duplicates))
    reasons = [gap_reason, f"중복 의심 {len(duplicates)}건" + "".join(f" · {d.detail}" for d in duplicates)]
    fixes += [f"{d.detail}. 기존 자원과 다른 점이 이름과 활동에 드러나게 고치세요." for d in duplicates]
    return finish("novelty", gap_points + duplicate_points, reasons, fixes)


# ── 3. 근거성 ────────────────────────────────────────────────────────────────────
STRONG_GRADES = ("public", "research")


def grounding(plan: ProgramPlan, planning) -> AxisResult:
    """근거 검증을 통과한 기획안만 오므로 '근거가 있는가'가 아니라 '원인별로 연결됐는가·출처 질'로 변별한다 (설계 문서 5.5).

    사례 검색이 없었으면(offline·검색 실패) 사례 항목을 빼고 근거 연결만으로 15점 만점 환산한다. 기획안 탓이 아니다.
    """
    evidence_of = {c.code: set(c.evidence_ids) for c in planning.causes}
    cited = set(plan.data_evidence)
    # 근거가 붙은 원인 가설만 대상으로 한다. C0처럼 근거 없는 가설은 연결할 근거가 없다.
    needs = [code for code in plan.risk_causes_addressed if evidence_of.get(code)]
    unlinked = [code for code in needs if not evidence_of[code] & cited]
    link_share = (len(needs) - len(unlinked)) / len(needs) if needs else 1.0
    reasons = [f"원인별 근거 연결 {len(needs) - len(unlinked)}/{len(needs)}" if needs else "근거가 필요한 원인 가설 없음"]
    fixes = [f"{CAUSE_LABELS[code]}의 근거({', '.join(sorted(evidence_of[code]))})를 인용하고 data_evidence에 넣으세요."
             for code in unlinked]

    if not planning.trends:
        reasons.append("참고 사례 검색 없음 → 근거 연결만으로 환산")
        return finish("grounding", 15 * link_share, reasons, fixes)

    references = plan.trend_references
    strong = [r for r in references if r.grade in STRONG_GRADES]
    reference_points = (3 if references else 0) + (3 * len(strong) / len(references) if references else 0)
    reasons.append(f"참고 사례 {len(references)}개 (공공·연구 {len(strong)}개)")
    if not references:
        # 사례 등급은 검색 결과에 달린 문제라 요청하지 않는다. 인용 여부만 기획안이 고칠 수 있다.
        fixes.append("검색된 참고 사례 중 이 대상에 맞는 것을 골라 어떻게 바꿔 적용하는지 쓰세요.")
    return finish("grounding", 9 * link_share + reference_points, reasons, fixes)


# ── 4. 예산 ─────────────────────────────────────────────────────────────────────
# 설계 문서의 '총액·1인당 비용·상한 초과'는 지금 입력으로 계산할 수 없다 (설계 결정 A).
# 단가는 지어내지 않도록 null로 오고, 참여 인원 필드와 예산 상한 입력이 없다. 입력이 생기면 이 축에 추가한다.
PER_SESSION_UNIT = re.compile(r"회|시간")  # '회', '1인 1회', '시간'처럼 회차마다 드는 항목


def budget(plan: ProgramPlan, planning) -> AxisResult:
    items = plan.budget_items
    sessions = plan.schedule.sessions
    composition_points = 5 if len(items) >= 2 else 2.5
    fixes = [] if len(items) >= 2 else ["활동에 드는 비용(공간·재료·강사·홍보 등)을 항목별로 나눠 쓰세요."]

    per_session = [item for item in items if PER_SESSION_UNIT.search(item.unit)]
    short = [item for item in per_session if item.quantity < sessions]
    session_points = 5 * (len(per_session) - len(short)) / len(per_session) if per_session else 5
    fixes += [f"'{item.item}' 수량 {item.quantity:g}({item.unit})이 운영 {sessions}회보다 적습니다. 회차에 맞게 고치세요."
              for item in short]

    priced = [item for item in items if item.unit_cost_krw is not None]
    price_points = 5 * len(priced) / len(items)
    reasons = [f"예산 항목 {len(items)}개",
               f"회차 연동 {len(per_session) - len(short)}/{len(per_session)} (운영 {sessions}회)" if per_session
               else "회차 단위 항목 없음",
               f"단가 확정 {len(priced)}/{len(items)}" + ("" if len(priced) == len(items) else " · 단가 확인 필요")]
    if priced and len(priced) == len(items):
        total = sum(item.quantity * item.unit_cost_krw for item in items)
        reasons.append(f"총액 {total:,.0f}원 (예산 상한 입력이 없어 초과 여부는 판단하지 않음)")
    # 단가 미확정은 요청하지 않는다. 기획 생성은 단가를 지어낼 수 없어 재기획 호출만 낭비된다.
    return finish("budget", composition_points + session_points + price_points, reasons, fixes)


# ── 5. 측정 가능성 ───────────────────────────────────────────────────────────────
# 통신·카드 데이터는 지역·연령 집단의 월별 집계라 참여자 개인을 구별할 수 없다.
# 데이터 KPI라면서 참여자·개인을 재겠다고 하면 실제로는 측정할 수 없으므로 데이터 KPI로 인정하지 않는다.
# (2026-10-23 첫 실제 호출에서 "참여자 대상 위치 데이터로 이동량 측정" 같은 KPI가 나왔다.)
INDIVIDUAL_TERMS = re.compile(r"참여자|개인|본인|당사자")


def measurability(plan: ProgramPlan, planning) -> AxisResult:
    data_kpis = [k for k in plan.kpis if k.measurable_by_data]
    individual = [k for k in data_kpis if INDIVIDUAL_TERMS.search(k.definition)]
    group_kpis = [k for k in data_kpis if k not in individual]
    process_kpis = [k for k in plan.kpis if not k.measurable_by_data]

    reasons = [f"집단 단위 데이터 KPI {len(group_kpis)}개" + (f": {', '.join(k.name for k in group_kpis)}" if group_kpis else ""),
               f"과정 KPI {len(process_kpis)}개" + (f": {', '.join(k.name for k in process_kpis)}" if process_kpis else "")]
    reasons += [f"'{k.name}': 참여자 개인을 재는 정의라 집계 데이터로 측정할 수 없음" for k in individual]
    fixes = []
    if individual:
        fixes.append(f"'{individual[0].name}' 지표를 참여자 개인이 아니라 대상 지역·연령 집단 전체의 월별 변화로 다시 정의하세요.")
    elif not group_kpis:
        fixes.append("통신·카드 데이터로 측정할 수 있는 집단 단위 지표(대상 지역·연령 집단의 월별 변화)를 추가하세요.")
    if not process_kpis:
        fixes.append("운영 기록·설문으로 측정할 과정 지표(참여율·재참여율 등)를 추가하세요.")
    return finish("measurability", (5 if group_kpis else 0) + (5 if process_kpis else 0), reasons, fixes)


# ── 진입점 ───────────────────────────────────────────────────────────────────────
RULE_AXES = (target_fit, novelty, grounding, budget, measurability)


def evaluate_plans(ctx: NodeContext, plans: list[ProgramPlan], planning, *, llm_call=None) -> list[PlanEvaluation]:
    """그래프 evaluate 노드의 계산 함수 (Engines.evaluate_plans 자리). 담당자 기획안도 그래프 밖에서 바로 부를 수 있다.

    규칙 5축 + LLM 1축(기획안 전체 1회 호출). LLM 축을 평가하지 못한 기획안은 규칙 85점을 100점으로 환산한다.
    총점·통과 여부는 계약의 summarize()가 계산한다 (점수를 손으로 합치지 않는다).
    llm_call: 테스트용 가짜 Gemini 호출.
    """
    llm = review_feasibility(ctx, plans, planning, call=llm_call)
    results = []
    for plan in plans:
        rule_results = [axis(plan, planning) for axis in RULE_AXES]
        llm_score, llm_requests = llm.get(plan.plan_id) or (unavailable("실현 가능성 평가 없음 (offline·호출 실패) → 규칙 축만으로 환산"), [])
        axes = [result.score for result in rule_results] + [llm_score]
        requests = [request for result in rule_results for request in result.requests] + llm_requests
        results.append(summarize(plan.plan_id, axes, requests))
    return results
