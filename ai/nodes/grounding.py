"""근거 검증 노드: 기획안이 주어진 근거만으로 쓰였는지 규칙으로 검사한다. (설계 문서 부록 A P5)

LLM을 쓰지 않는다. 쓴 쪽(LLM)이 자기 결과를 검사하면 같은 실수를 놓치기 쉽다.
없는 근거 id·검색에 없는 URL·대상 바꿔치기는 기획 생성(planner)의 스키마가 이미 막는다.
여기서는 스키마로 막을 수 없는 자유 문장과, 스키마를 거치지 않는 담당자 직접 입력 기획안을 맡는다.

1. 숫자: 문장 속 %·소수가 근거 값과 맞는지 (KPI 목표치 제외)
2. 금지 표현: 효과 보장·자격 확정·개인 진단은 제외, 결과 단정 끝맺음은 경고
3. 중복 의심: 기획안 제목·활동 이름이 기존 자원 이름과 겹치면 경고 (연계한다고 밝힌 자원은 제외)
4. 담당자 기획안: 대상 불일치는 제외, 없는 근거 id는 그 id만 제거, 검색에 없는 사례 URL은 경고

진입점 check_grounding()이 1~4를 모두 돌리고, '제외' 이슈가 하나라도 있는 기획안을 뺀다.
"""

import re

from ai.contracts import ExistingResources, GroundingIssue, GroundingReport, ProgramPlan, TargetProfile
from ai.nodes.context import NodeContext

# 문장이 아닌 필드. 코드값·식별자이거나, 검색 결과에서 그대로 옮긴 값이라 기획안이 쓴 문장이 아니다.
NON_TEXT_FIELDS = {"schema_version", "plan_id", "source", "status", "format", "target", "risk_causes_addressed",
                   "gap_causes", "data_evidence", "linked_existing_resources", "url"}
NUMBER_EXEMPT_PREFIXES = ("kpis",)  # KPI 목표치("재참여율 60% 이상")는 근거 인용이 아니라 담당자가 정할 목표다

MINUS = "-−–"  # 하이픈, 수학 기호 마이너스, en dash 모두 음수로 읽는다
PERCENT = re.compile(rf"(?<![\d.])[{MINUS}+]?\d+(?:\.\d+)?(?=\s*%)")
RATIO = re.compile(rf"(?<![\d.])[{MINUS}+]?0\.\d+(?![\d.])")  # 0.083처럼 0으로 시작하는 소수만 (500.0 등은 제외)
EPSILON = 1e-9  # 부동소수점 비교 오차


def text_fields(plan: ProgramPlan) -> list[tuple[str, str]]:
    """기획안의 문장을 (위치, 문장)으로 꺼낸다. 위치는 'activities.0.description'처럼 쓴다."""
    found = []

    def walk(value, path):
        if isinstance(value, str):
            found.append((path, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}.{index}")
        elif isinstance(value, dict):
            for key, item in value.items():
                # 참고 사례의 제목은 검색 결과에서 코드가 옮긴 값이라 기획안 문장이 아니다.
                if key in NON_TEXT_FIELDS or (key == "title" and ".trend_references." in f".{path}."):
                    continue
                walk(item, f"{path}.{key}" if path else key)

    walk(plan.model_dump(mode="json"), "")
    return found


def _matches(written: str, allowed: list[float]) -> bool:
    """쓴 숫자가 근거 값을 '쓴 자릿수'로 반올림한 값과 같은지.

    근거 -0.083 → '-8.3%'·'약 8%'·'-0.083'·'0.08'은 맞고, '-8.25%'는 근거에 없는 정밀도를 지어낸 것이라 틀리다.
    부호는 보지 않는다 ('8.3% 감소'처럼 부호 없이 쓰는 경우).
    """
    value = abs(float(written.translate({ord(c): "-" for c in MINUS[1:]})))
    digits = len(written.split(".")[1]) if "." in written else 0
    return any(abs(round(candidate, digits) - value) < EPSILON for candidate in allowed)


def allowed_values(profile: TargetProfile) -> tuple[list[float], list[float]]:
    """근거 수치를 (퍼센트 눈금, 비율 눈금)의 절댓값으로. '8.3% 감소'처럼 부호 없이 써도 맞게 절댓값으로 비교한다."""
    percent, ratio = [], []
    for item in profile.evidence:
        if item.unit == "ratio":
            percent.append(abs(item.value) * 100)
            ratio.append(abs(item.value))
        elif item.unit == "percent":
            percent.append(abs(item.value))
            ratio.append(abs(item.value) / 100)
    return percent, ratio


def check_numbers(plan: ProgramPlan, profile: TargetProfile) -> list[GroundingIssue]:
    """문장 속 %·소수 중 근거에 없는 값을 찾는다. 하나라도 있으면 기획안을 제외한다 (설계 결정 A)."""
    percent_ok, ratio_ok = allowed_values(profile)
    issues = []
    for path, text in text_fields(plan):
        if path.startswith(NUMBER_EXEMPT_PREFIXES):
            continue
        unknown = [f"{m.group()}%" for m in PERCENT.finditer(text) if not _matches(m.group(), percent_ok)]
        unknown += [m.group() for m in RATIO.finditer(text) if not _matches(m.group(), ratio_ok)]
        if unknown:
            issues.append(GroundingIssue(plan_id=plan.plan_id, kind="unknown_evidence", action="excluded",
                                         detail=f"{path}: 근거에 없는 수치 {', '.join(unknown)}"))
    return issues


# ── 2. 금지 표현 ─────────────────────────────────────────────────────────────────
# 좁게 시작한다 (설계 결정 B). 넓게 잡으면 멀쩡한 기획안이 버려진다. 실제 호출에서 놓친 표현이 보이면 추가한다.
# 단어가 아니라 '문장 형태'로 잡는다: "해소하기 위해"(목적)는 허용, "해소됩니다"(결과 단정)는 경고.
PHRASE_RULES = [
    # (분류, 처리, 패턴)
    ("효과 보장", "excluded", r"효과[가를이]?\s*(?:입증|검증|보장)"),
    ("효과 보장", "excluded", r"(?:반드시|확실히|틀림없이|100%)\s*(?:\S+\s*){0,2}?(?:해소|해결|개선|예방|감소)"),
    ("자격 확정", "excluded", r"(?:신청|지원|수급)\s*(?:자격|대상)[이에]?\s*(?:있습니다|있다|해당합니다|해당한다|됩니다|확정)"),
    ("개인 진단", "excluded", r"(?:우울증|정신질환|은둔형\s*외톨이)\s*(?:환자|진단|을\s*앓는|이\s*있는)"),
    ("결과 단정", "warned", r"(?:고립|외로움|위축|단절)\S{0,2}\s*(?:해소|해결|극복)(?:됩니다|된다|될\s*것|합니다|할\s*것)"),
    ("개인 낙인", "warned", r"고립된\s*(?:청년|사람|주민|노인|이웃|남성|여성)"),
]
PHRASES = [(label, action, re.compile(pattern)) for label, action, pattern in PHRASE_RULES]
# 바로 뒤에 부정이 오면 금지가 아니라 '하지 않는다'는 단서다 (예: "고립을 단정하지 않습니다", "확정이 아닌 가설").
NEGATION = re.compile(r"^\S{0,6}\s?(?:않|아니|아닌|아님|없|못|말)")


def check_phrases(plan: ProgramPlan) -> list[GroundingIssue]:
    """문장마다 금지 표현을 찾는다. 같은 문장·같은 분류는 한 번만 기록한다.

    규칙은 제외 → 경고 순서라, 같은 글자를 두 규칙이 잡으면 무거운(제외) 쪽만 남긴다.
    """
    issues = []
    for path, text in text_fields(plan):
        seen, spans = set(), []
        for label, action, pattern in PHRASES:
            for match in pattern.finditer(text):
                overlaps = any(match.start() < end and start < match.end() for start, end in spans)
                if label in seen or overlaps or NEGATION.match(text[match.end():]):
                    continue
                seen.add(label)
                spans.append(match.span())
                issues.append(GroundingIssue(plan_id=plan.plan_id, kind="forbidden_phrase", action=action,
                                             detail=f"{path}: {label} 표현 '{match.group()}'"))
    return issues


# ── 3. 중복 의심 ─────────────────────────────────────────────────────────────────
# 이름 끝의 사업 형태 표현은 비교에서 뺀다. "고독사 예방 사업"과 "고독사 예방 소모임"은 핵심 이름이 같다.
GENERIC_SUFFIX = re.compile(r"(?:사업|서비스|프로그램)$")
MIN_NAME_LENGTH = 4  # 너무 짧은 이름("돌봄")은 아무 제목에나 들어 있어 비교하지 않는다


def core_name(name: str) -> str:
    """비교용 핵심 이름: 공백·괄호·기호를 지우고 끝의 사업/서비스/프로그램을 뺀다."""
    return GENERIC_SUFFIX.sub("", re.sub(r"[\W_]+", "", name))


def check_duplicates(plan: ProgramPlan, existing: ExistingResources) -> list[GroundingIssue]:
    """기획안 제목·활동 이름과 기존 자원 이름이 서로 포함 관계면 중복 의심으로 경고한다 (설계 결정 C).

    판단은 평가의 신규성 축과 담당자에게 맡기므로 제외하지 않는다. 이름이 비슷해도 내용은 다를 수 있다.
    """
    if existing.status != "available":
        return []
    linked = set(plan.operation.linked_existing_resources)  # 연계는 의도된 겹침이다
    names = [("title", plan.title)] + [(f"activities.{i}.name", a.name) for i, a in enumerate(plan.activities)]
    issues = []
    for resource in existing.resources:
        resource_core = core_name(resource.name)
        if resource.id in linked or len(resource_core) < MIN_NAME_LENGTH:
            continue
        for path, name in names:
            plan_core = core_name(name)
            if resource_core in plan_core or (len(plan_core) >= MIN_NAME_LENGTH and plan_core in resource_core):
                issues.append(GroundingIssue(plan_id=plan.plan_id, kind="duplicate_suspected", action="warned",
                                             detail=f"{path}: 기존 자원 '{resource.name}'({resource.id})과 이름이 겹칩니다"))
    return issues


# ── 4. 담당자 기획안 ──────────────────────────────────────────────────────────────
def check_manual(plan: ProgramPlan, planning) -> tuple[ProgramPlan, list[GroundingIssue]]:
    """담당자가 직접 쓴 기획안(source=manual)만 검사한다. LLM 기획안은 planner 스키마가 이미 막았다 (설계 결정 D).

    반환: (근거 id를 정리한 기획안, 이슈). 원래 기획안은 바꾸지 않고 복사본을 돌려준다.
    """
    if plan.source != "manual":
        return plan, []
    issues = []
    if plan.target != planning.profile.target:
        # 다른 집단의 기획안을 이 집단 근거로 평가하면 점수가 무의미하다.
        issues.append(GroundingIssue(plan_id=plan.plan_id, kind="target_mismatch", action="excluded",
                                     detail=f"target: 기획안 대상 {plan.target.model_dump()}이 분석 대상 "
                                            f"{planning.profile.target.model_dump()}과 다릅니다"))
    known = set(planning.profile.evidence_by_id())
    unknown_ids = [item for item in plan.data_evidence if item not in known]
    if unknown_ids:
        # 사람의 오타일 가능성이 커서 기획안 전체가 아니라 그 id만 지운다.
        plan = plan.model_copy(update={"data_evidence": [item for item in plan.data_evidence if item in known]})
        issues.append(GroundingIssue(plan_id=plan.plan_id, kind="unknown_evidence", action="removed_item",
                                     detail=f"data_evidence: 분석에 없는 근거 id {', '.join(unknown_ids)}를 지웠습니다"))
    searched = {trend.url for trend in planning.trends}
    for index, ref in enumerate(plan.trend_references):
        if ref.url not in searched:
            # 담당자는 실제로 아는 자료를 인용할 수 있다. 우리 검색에 없다고 가짜는 아니므로 남기고 표시만 한다.
            issues.append(GroundingIssue(plan_id=plan.plan_id, kind="unknown_url", action="warned",
                                         detail=f"trend_references.{index}.url: 검색 결과로 확인되지 않은 출처 {ref.url}"))
    return plan, issues


# ── 진입점 ───────────────────────────────────────────────────────────────────────
def check_grounding(ctx: NodeContext, plans: list[ProgramPlan], planning) -> tuple[list[ProgramPlan], GroundingReport]:
    """그래프 grounding_check 노드의 계산 함수 (Engines.check_grounding 자리).

    반환: (통과한 기획안, 리포트). 통과한 기획안은 담당자 기획안의 없는 근거 id를 지운 수정본일 수 있다.
    '제외' 이슈가 하나라도 있으면 그 기획안은 빠지고, '경고'·'항목 제거'만 있으면 통과한다.
    같은 입력에는 항상 같은 결과를 낸다 (외부 호출 없음). ctx는 그래프 노드 공통 인자라 받기만 한다.
    """
    kept, excluded, issues = [], [], []
    for plan in plans:
        plan, found = check_manual(plan, planning)
        found += check_numbers(plan, planning.profile)
        found += check_phrases(plan)
        found += check_duplicates(plan, planning.existing)
        issues += found
        if any(issue.action == "excluded" for issue in found):
            excluded.append(plan.plan_id)
        else:
            kept.append(plan)
    return kept, GroundingReport(kept_plan_ids=[p.plan_id for p in kept], excluded_plan_ids=excluded, issues=issues)
