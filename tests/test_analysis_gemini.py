"""실제 키 없이 검색 경계·모델 실패·수치 보존을 검증한다."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.analysis_agent.gemini_provider import (
    GeminiTavilyProvider, ExternalCallError, DEFAULT_MODEL, official_url, sources_from,
)
from ai.analysis_agent.workflow import run_analysis
from ai.analysis_agent.reviewer import review_cohort
from tests.test_analysis_agent import rows

CONFIG = dict(GEMINI_API_KEY="test-key-not-real", TAVILY_API_KEY="test-search-not-real")


def dataset():
    return rows(["202507", "202508", "202509"], [3100, 2700, 2400], [None, -.1, -.1], [None, -.1, -.1])


def model_response(proposal=None, finish="STOP"):
    if proposal is None:
        proposal = dict(observation_ids=["E1"], hypothesis_codes=[], question_codes=["calendar"], source_ids=["S1"])
    return dict(responseId="fake-response", usageMetadata=dict(promptTokenCount=100, candidatesTokenCount=30),
                candidates=[dict(finishReason=finish, content=dict(parts=[dict(text=json.dumps(proposal))]))])


def search_response():
    return dict(results=[dict(url="https://www.chuncheon.go.kr/news?id=1", title="지역 통계",
                             content="공식 자료의 검색 발췌", published_date="2025-09-10")], usage=dict(credits=1))


class GeminiAnalysisTests(unittest.TestCase):
    def cohort(self):
        return run_analysis(dataset(), {}, [], period="202509")["cohorts"][-1]

    def provider(self, transport, **kwargs):
        return GeminiTavilyProvider(config=CONFIG, transport=transport, **kwargs)

    def test_search_then_model_single_call_and_no_raw_data_to_search(self):
        calls = []
        def transport(url, headers, body):
            calls.append((url, headers, body))
            return search_response() if "tavily" in url else model_response()
        review, execution = review_cohort(self.cohort(), self.provider(transport))
        self.assertEqual(review["status"], "fixture_only")
        self.assertEqual(execution["confirmed_llm_responses"], 0)
        self.assertEqual(len(calls), 2)
        search = calls[0][2]
        self.assertEqual(search["end_date"], "2025-09-30")
        self.assertEqual(search["search_depth"], "basic")
        self.assertFalse(search["auto_parameters"])
        self.assertNotIn("risk", json.dumps(search))
        model_input = json.loads(calls[1][2]["contents"][0]["parts"][0]["text"])
        self.assertEqual(set(model_input), {"profile", "hypotheses", "allowed_question_codes", "external_sources"})
        self.assertNotIn("test-key-not-real", json.dumps(execution))
        self.assertEqual(execution["receipts"][0]["selected_source_ids"], ["S1"])

    def test_domain_and_protocol_spoofing_rejected(self):
        for url in ["https://chuncheon.go.kr.evil.test/x", "http://chuncheon.go.kr/x",
                    "https://evil.test/chuncheon.go.kr", "https://user:pass@chuncheon.go.kr",
                    "https://chuncheon.go.kr:8080/x", "file:///secret"]:
            self.assertIsNone(official_url(url), url)
        self.assertEqual(official_url("https://www.chuncheon.go.kr/news#x"), "https://www.chuncheon.go.kr/news")

    def test_future_dated_source_filtered_and_unknown_dates_explicit(self):
        response = search_response()
        response["results"] += [dict(url="https://kosis.kr/future",content="future",published_date="2026-01-01"),
                                dict(url="https://kostat.go.kr/unknown",content="unknown")]
        sources = sources_from(response,"2025-09-30")
        self.assertEqual(len(sources),2)
        self.assertEqual(sources[1]["temporal_status"],"date_unverified")

    def test_duplicate_and_unofficial_sources_filtered(self):
        response = search_response()
        response["results"] += response["results"] + [dict(url="https://blog.example/a",content="wrong")]
        self.assertEqual(len(sources_from(response,"2025-09-30")),1)

    def test_unknown_source_cannot_be_saved_as_accepted_review(self):
        def transport(url, headers, body):
            return search_response() if "tavily" in url else model_response(dict(
                observation_ids=[],hypothesis_codes=[],question_codes=[],source_ids=["S999"]))
        review, execution = review_cohort(self.cohort(),self.provider(transport))
        self.assertEqual(review["status"],"failed")
        self.assertEqual(execution["receipts"][0]["selected_source_ids"],[])

    def test_search_failure_stops_model_and_preserves_original(self):
        calls=[]
        def transport(*args):
            calls.append(args)
            raise ExternalCallError("http_429")
        cohort=self.cohort(); original=copy.deepcopy(cohort)
        provider=self.provider(transport)
        review, execution=review_cohort(cohort,provider)
        self.assertEqual(cohort,original)
        self.assertEqual(review["status"],"failed")
        self.assertEqual(len(calls),1)
        self.assertEqual(execution["receipts"][0]["gemini_attempts"],0)
        self.assertEqual(execution["receipts"][0]["search_status"],"failed")
        review_cohort(cohort,provider)
        self.assertEqual(len(calls),1)

    def test_model_failure_keeps_search_evidence_and_no_retry(self):
        calls=[]
        def transport(url, headers, body):
            calls.append(url)
            if "tavily" in url: return search_response()
            raise ExternalCallError("http_503")
        review, execution=review_cohort(self.cohort(),self.provider(transport))
        self.assertEqual(review["status"],"failed")
        self.assertEqual(len(calls),2)
        self.assertEqual(len(execution["receipts"][0]["sources"]),1)

    def test_truncated_response_rejected(self):
        def transport(url,headers,body):
            return search_response() if "tavily" in url else model_response(finish="MAX_TOKENS")
        review,_=review_cohort(self.cohort(),self.provider(transport))
        self.assertEqual(review["status"],"failed")

    def test_invented_risk_field_rejected(self):
        def transport(url,headers,body):
            if "tavily" in url: return search_response()
            return model_response(dict(observation_ids=[],hypothesis_codes=[],question_codes=[],source_ids=[],level=5))
        review,_=review_cohort(self.cohort(),self.provider(transport))
        self.assertEqual(review["status"],"failed")

    def test_empty_search_still_allows_existing_evidence_review(self):
        def transport(url,headers,body):
            if "tavily" in url: return dict(results=[])
            return model_response(dict(observation_ids=["E1"],hypothesis_codes=[],question_codes=[],source_ids=[]))
        review,execution=review_cohort(self.cohort(),self.provider(transport))
        self.assertEqual(review["status"],"fixture_only")
        self.assertEqual(execution["receipts"][0]["search_status"],"no_usable_results")

    def test_gemini_only_does_not_require_search_key(self):
        provider=GeminiTavilyProvider(config=dict(GEMINI_API_KEY="fake"),use_search=False,
            transport=lambda *args:model_response(dict(observation_ids=[],hypothesis_codes=[],question_codes=[],source_ids=[])))
        review,execution=review_cohort(self.cohort(),provider)
        self.assertEqual(review["status"],"fixture_only")
        self.assertEqual(execution["receipts"][0]["search_attempts"],0)

    def test_bad_model_or_missing_key_makes_no_call(self):
        with self.assertRaises(ValueError):
            self.provider(lambda *args:self.fail(),model="arbitrary-paid-model")
        with self.assertRaises(ValueError):
            GeminiTavilyProvider(config={},transport=lambda *args:self.fail())

    def test_entire_workflow_keeps_risk_profile_and_priority_identical(self):
        before=run_analysis(dataset(),{},[],period="202509")
        def transport(url,headers,body):
            return search_response() if "tavily" in url else model_response()
        after=run_analysis(dataset(),{},[],period="202509",provider=self.provider(transport),
                           model_analysis_id=before["cohorts"][-1]["analysis_id"])
        self.assertEqual(before["priority_review"],after["priority_review"])
        for a,b in zip(before["cohorts"],after["cohorts"]):
            for key in ("assessment","profile","profile_hash","sensitivity","team_causes"):
                self.assertEqual(a[key],b[key],key)
        self.assertEqual(after["execution"]["search_attempts"],1)
        self.assertEqual(after["execution"]["gemini_attempts"],1)
        self.assertEqual(after["execution"]["confirmed_llm_responses"],0)

    def test_http_errors_do_not_leak_headers_or_body(self):
        from urllib.error import HTTPError
        from ai.analysis_agent.gemini_provider import post_json
        with patch("ai.analysis_agent.gemini_provider.build_opener") as opener:
            opener.return_value.open.side_effect=HTTPError("https://api.tavily.com/search",429,"secret-detail",None,None)
            with self.assertRaises(ExternalCallError) as result:
                post_json("https://api.tavily.com/search",{"Authorization":"secret-key"},{})
            self.assertEqual(str(result.exception),"http_429")

    def test_saved_research_is_verified_against_bundle(self):
        from tests.test_analysis_agent import write_fixture
        from ai.analysis_agent.inputs import load_inputs, source_path, digest
        from scripts.integration.run_analysis_agent import save_results
        from scripts.integration.verify_analysis_agent import verify
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            baseline,contexts=write_fixture(root)
            paths={entry["role"]:source_path(entry) for entry in baseline["source_manifest"]}
            data,contexts,manifest=load_inputs(paths["features"],paths["industry_sensitivity"],paths["context_packet"])
            def transport(url,headers,body):
                return search_response() if "tavily" in url else model_response()
            bundle=run_analysis(data,contexts,manifest,period="202509",provider=self.provider(transport),
                                model_analysis_id=baseline["cohorts"][-1]["analysis_id"])
            bundle.pop("bundle_hash")
            bundle["implementation_manifest"]=baseline["implementation_manifest"]
            bundle["bundle_hash"]=digest(bundle)
            result=save_results(bundle,contexts,root/"out")
            folder=Path(result["output"])
            records=json.loads((folder/"external_research.json").read_text(encoding="utf-8"))
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]["selected_source_ids"],["S1"])
            (folder/"external_research.json").write_text("[]",encoding="utf-8")
            with self.assertRaises(ValueError): verify(folder)


if __name__ == "__main__":
    unittest.main()
