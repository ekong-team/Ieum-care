"""신청·접수 기간의 명시된 날짜만 검사한다. 지급·운영 기간으로 접수 가능 여부를 추정하지 않는다."""
from datetime import date
import re

FULL_DATE = re.compile(r"(?<!\d)(20\d{2}|[‘’'`]\s*\d{2})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*[.일]?")
SHORT_DATE = re.compile(r'(?<![\d.])(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*[.일]?')
PERIOD = re.compile(r'(?:신청|접수|모집)\s*(?:기간|기한|마감)(?:\s*변경)?\s*[:：|]?\s*([^\n]{0,240})')
NEXT_FIELD = re.compile(r'(?:지급|지원|운영|교육|사업)\s*기간|신청방법|접수장소|제출서류|선정발표')


def end_date(text):
    """연도 포함 날짜와 범위 끝 날짜를 해석한다. 연도·일자가 불명확하면 확정하지 않는다."""
    text = text.split('→')[-1]  # 명시적인 변경 표기에서는 변경 후 범위만 읽는다.
    dates = list(FULL_DATE.finditer(text))
    if not dates:
        return None
    try:
        parsed = []
        for match in dates:
            year = re.sub(r'\D', '', match[1])
            parsed.append(date(int(year) if len(year) == 4 else 2000 + int(year), int(match[2]), int(match[3])))
        if len(parsed) >= 2 and re.search(r'[~∼～–—-]|부터', text[dates[0].end():dates[-1].start()]):
            return parsed[-1] if parsed[-1] >= parsed[0] else None
        if len(parsed) == 1:
            suffix = text[dates[0].end():]
            separator = re.search(r'[~∼～–—-]|부터', suffix)
            if separator:
                short = SHORT_DATE.search(suffix[separator.end():])
                if not short:
                    return None
                ending = date(parsed[0].year, int(short[1]), int(short[2]))
                return ending if ending >= parsed[0] else None
            if '까지' in suffix or '마감' in text or '기한' in text:
                return parsed[0]
    except ValueError:
        pass
    return None


def application_period_info(evidence, today):
    """서로 다른 종료일이 있거나 연장·재공고 가능성이 있으면 자동 종료 판정을 보류한다."""
    text = evidence.get('content', '')
    periods = []
    unresolved = False
    for match in PERIOD.finditer(text):
        excerpt = NEXT_FIELD.split(match[0], maxsplit=1)[0].strip()
        if re.search(r'마감일\s*(?:로부터|기준)', excerpt):
            continue  # '마감일로부터 12주 뒤 발표'는 신청 마감 날짜가 아니다.
        # 날짜 없이 '예산 소진 시' 등으로만 정한 기간은 자동 종료하지 않는다.
        ending = end_date(excerpt)
        if ending:
            periods.append((ending, excerpt))
        elif re.sub(r'(?:신청|접수|모집)\s*(?:기간|기한|마감)\s*[:：|]?', '', excerpt).strip():
            unresolved = True
    endings = {ending for ending, _ in periods}
    if len(endings) != 1 or unresolved:
        return dict(status='unconfirmed', deadline=None, evidence=None, evaluated_at=today,
                    reason='ambiguous_or_missing_application_dates')
    ending = next(iter(endings))
    return dict(status='deadline_passed' if ending < date.fromisoformat(today) else 'deadline_not_passed',
                deadline=ending.isoformat(), evidence=periods[-1][1], evaluated_at=today,
                reason='explicit_application_period_only')
