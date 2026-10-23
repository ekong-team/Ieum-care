"""신청 날짜 검사 회귀: 지급 기간·마감 당일·불명확한 연장을 접수 종료로 확정하지 않는다."""
import json
from pathlib import Path
import unittest

from ai.welfare_agent.application_period import application_period_info
from ai.welfare_agent.live_agent import checked_result
from tests.test_welfare_live_agent import example_decision, URL


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/welfare_application_period_case.json').read_text(encoding='utf-8'))


def info(text, today='2026-10-24'):
    return application_period_info({'content':text}, today)


class ApplicationPeriodTests(unittest.TestCase):
    def test_recorded_application_deadline_is_separate_from_payment_end(self):
        result = info(FIXTURE['content'])
        self.assertEqual(result['status'], 'deadline_passed')
        self.assertEqual(result['deadline'], FIXTURE['expected_deadline'])
        self.assertNotIn('2028', result['evidence'])

    def test_model_uncertainty_does_not_bypass_explicit_deadline(self):
        decision = example_decision()
        resource = decision['resources'][0]
        resource.update(name='청년월세 지원', availability_status='needs_confirmation',
            schedule='2026. 5. ~ 2028. 12. 지급', schedule_evidence='2026. 5. ~ 2028. 12. 최대 24개월(최대 480만원) 지급',
            check='신청이 마감되었을 수 있어 확인이 필요합니다.')
        evidence = [dict(url=URL, title='사업 안내', content=FIXTURE['content'], source_kind='web_page')]
        result = checked_result(decision, {'target':dict(region='춘천시', age_group=30, purpose='all')},
                                {URL}, FIXTURE['review_date'], 'fake-model', evidence)
        self.assertEqual(result['resources'], [])
        self.assertEqual(result['exclusion_counts'], {'application_deadline_passed':1})
        self.assertEqual(result['candidate_exclusions'][0]['application_period']['deadline'], '2026-05-29')
        self.assertNotEqual(result['review']['summary'], decision['summary'])

    def test_payment_operation_and_publication_dates_do_not_close_applications(self):
        for text in ('지급기간: 2024.1.1.~2024.12.31.', '운영기간: 2024.1.1.~2024.12.31.',
                     '게시일: 2024.1.1. / 선정발표: 2024.2.1.', '연 1회 지원, 예산 소진 시 종료'):
            with self.subTest(text=text):
                self.assertEqual(info(text)['status'], 'unconfirmed')

    def test_deadline_day_future_and_next_day_are_distinct_without_promising_open(self):
        text = '신청기간: 2026.10.1.~2026.10.24.'
        self.assertEqual(info(text, '2026-10-23')['status'], 'deadline_not_passed')
        self.assertEqual(info(text, '2026-10-24')['status'], 'deadline_not_passed')
        self.assertEqual(info(text, '2026-10-25')['status'], 'deadline_passed')

    def test_short_end_date_korean_dates_and_single_explicit_deadline(self):
        for text in ('접수기간: 2026.6.1.~6.8.', '신청기한: 2026년 6월 8일까지',
                     '모집기간: 2026-06-01 - 2026-06-08',
                     '접수기간: 2026.06.01.(월) ∼ 2026.06.08.(월)'):
            with self.subTest(text=text):
                self.assertEqual(info(text)['deadline'], '2026-06-08')

    def test_ambiguous_missing_or_invalid_dates_are_not_guessed(self):
        for text in ('신청기간: 6.1.~6.8.', '신청기간: 2026.5.1.~2026.5.',
                     '신청기간: 2026.2.1.~2026.2.30.', '접수기간: 2026.12.20.~1.10.',
                     '신청기간: 2026.5.1.~2026.5.29.\n추가 모집기간: 2026.11.1.~2026.11.30.',
                     '신청기간: 2026.5.1.~2026.5.29.\n신청기간: 추후 공지'):
            with self.subTest(text=text):
                self.assertEqual(info(text)['status'], 'unconfirmed')

    def test_relative_announcement_date_and_duplicate_quotes_do_not_block_real_deadline(self):
        text = '신청 마감일로부터 약 12주 이후 개별 발표\n접수기간: 2026.06.08. ∼ 2026.06.12.'
        self.assertEqual(info(text + '\n' + text)['deadline'], '2026-06-12')

