"""제공 자료에서 활동 위축 단계를 계산한다. 언어모델은 판정에 관여하지 않는다."""
from collections import defaultdict
from calendar import monthrange
from decimal import Decimal
from ai.analysis_agent.inputs import REGIONS, AGES, DEFAULT_BASIS, DECLINE_THRESHOLD, SEVERE_THRESHOLD, age_code
from ai.analysis_agent.inputs import number, month_number, validate_rows

def tri_and(*values):
    return False if any(v is False for v in values) else None if any(v is None for v in values) else True

def declined(value, threshold):
    return None if value is None else value <= -threshold

def assess(rows: list[dict], *, basis=DEFAULT_BASIS, decline=DECLINE_THRESHOLD, severe=SEVERE_THRESHOLD) -> list[dict]:
    """인접 월만 비교하고, 상위 조건 미확인은 부분판정으로 보존한다."""
    rows = validate_rows(rows)
    threshold, big = number(decline), number(severe)
    if basis not in ("daily", "monthly") or threshold is None or big is None or not Decimal(0) < threshold <= big < Decimal(1):
        raise ValueError("invalid policy")
    grouped = defaultdict(list)
    for row in rows:
        month_number(row["month"])
        grouped[(row["region"], row["age"], row["sex"])].append(row)
    output = []
    for key, group in sorted(grouped.items()):
        previous, previous_calc = None, None
        seen = set()
        for row in sorted(group, key=lambda r: r["month"]):
            month = row["month"]
            if month in seen:
                raise ValueError("duplicate group month")
            seen.add(month)
            current_month = month_number(month)
            adjacent = previous is not None and current_month - month_number(previous["month"]) == 1
            days = monthrange(int(month[:4]), int(month[4:]))[1]
            prev_days = monthrange(int(previous["month"][:4]), int(previous["month"][4:]))[1] if adjacent else None
            card_change = None
            if adjacent and row["card"] is not None and previous["card"] is not None and previous["card"] > 0:
                ratio = row["card"] / previous["card"]
                card_change = ratio * Decimal(prev_days) / Decimal(days) - 1 if basis == "daily" else ratio - 1
            movement = row["movement"] if adjacent else None
            filtered = row["filtered_daily"] if adjacent else None
            if filtered is not None and basis == "monthly":
                filtered = (filtered + 1) * Decimal(days) / Decimal(prev_days) - 1
            if basis == "daily" and adjacent:
                stored = row.get("stored_daily")
                if (stored is None) != (card_change is None) or stored is not None and abs(stored - card_change) > Decimal("0.000000001"):
                    raise ValueError("stale daily sensitivity input")
            c, m = declined(card_change, threshold), declined(movement, threshold)
            joint = tri_and(c, m)
            prior_joint = previous_calc["joint"] if adjacent else None
            persistent = tri_and(joint, prior_joint)
            filtered_persistent = tri_and(declined(filtered, threshold),
                declined(previous_calc["filtered"], threshold) if adjacent else None)
            large = tri_and(declined(card_change, big), declined(movement, big))
            fifth = tri_and(persistent, large, filtered_persistent)
            if c is None or m is None:
                level, status, reason = None, "held", "필수 지표의 전월 비교 불가"
            elif fifth is True:
                level, status, reason = 5, "complete", "동시 감소 지속·현재 큰 감소·업종 제외 후 지속 조건 충족"
            elif persistent is True:
                level, status = 4, "partial" if fifth is None else "complete"
                reason = "두 번 연속 동시 감소" + ("; 상위 업종 조건 미확인" if status == "partial" else "")
            elif joint is True:
                level, status = 3, "partial" if persistent is None else "complete"
                reason = "소비·유동량 동시 감소" + ("; 지속성 이력 부족" if status == "partial" else "")
            elif c or m:
                level, status, reason = 2, "complete", "한 지표만 기준 이상 감소"
            else:
                level, status, reason = 1, "complete", "기준 이상 감소 신호 없음; 고립 없음·안전 확정 아님"
            warnings = []
            for name, value, cutoff in (("공통 관측 위치", row["common_location"], Decimal(".90")),
                                       ("연령 관측률", row["age_coverage"], Decimal(".75"))):
                if value is None or value < cutoff:
                    warnings.append(name + " 확인 필요; 진단용 기준이며 단계 차단에 사용하지 않음")
            streak = 0 if joint is not True else 1 + (previous_calc["streak"] if adjacent and previous_calc["joint"] is True else 0)
            aid = month + "_" + REGIONS[key[0]][1] + "_" + age_code(key[1])
            if key[2] != "all":
                aid += "_" + key[2]
            calc = dict(analysis_id=aid, month=month, region=key[0], age=key[1],
                sex=key[2],
                policy=dict(basis=basis, decline_ratio=float(threshold), severe_ratio=float(big)),
                level=level, status=status, reason=reason,
                card_change=None if card_change is None else float(card_change),
                movement_change=None if movement is None else float(movement),
                filtered_change=None if filtered is None else float(filtered),
                conditions=dict(consumption_decline=c, movement_decline=m, joint_decline=joint,
                    persistent=persistent, severe=large, filtered_persistent=filtered_persistent, fifth=fifth),
                consecutive_joint_comparisons=streak, quality_warnings=warnings,
                age_coverage=None if row["age_coverage"] is None else float(row["age_coverage"]),
                common_location=None if row["common_location"] is None else float(row["common_location"]))
            output.append(calc)
            previous, previous_calc = row, dict(joint=joint, filtered=filtered, streak=streak)
    return output
