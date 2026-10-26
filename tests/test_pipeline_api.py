"""통합 실행 API (설계 문서 6.1·10장 백엔드 완료 기준). 외부 API는 호출하지 않는다 (offline)."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai.graph.pipeline import Engines
from ai.nodes import causes as cause_rules
from backend.server import LIVE_SLOT, create_server
from tests.test_planning_handoff import planning_fixture

PROFILE = json.loads((Path(__file__).parent / "fixtures" / "target_profile_example.json").read_text(encoding="utf-8"))


class ApiCase(unittest.TestCase):
    """임시 폴더에 서버를 띄우는 공통 준비. 테스트는 아래 두 클래스에 있다."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.engines = Engines()
        self.server = create_server(0, planning_root=root / "inbox", runs_root=root / "runs",
                                    pipeline_engines=self.engines)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def post(self, path, data):
        request = Request(self.base + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as response:
            return json.load(response)

    def wait(self, run_id):
        for _ in range(200):
            body = self.get(f"/api/pipeline/runs/{run_id}")
            if body["status"] != "running":
                return body
            time.sleep(0.05)
        self.fail("통합 실행이 끝나지 않았습니다.")


class PipelineApiTests(ApiCase):
    def test_manual_profile_runs_to_report_and_is_saved(self):
        status, started = self.post("/api/pipeline/runs", {"mode": "offline", "profile": PROFILE,
                                                            "officer_request": "주말 활동을 우선 검토"})
        self.assertEqual(status, 202)
        self.assertRegex(started["run_id"], r"^run-[0-9a-f]{12}$")
        done = self.wait(started["run_id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["report"]["status"], "completed")
        self.assertEqual(done["result"]["officer_request"], "주말 활동을 우선 검토")
        self.assertTrue(done["is_example"])
        seqs = [event["seq"] for event in done["events"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(seqs[0], 0)
        # after_seq 이후 기록만 돌려준다.
        later = self.get(f"/api/pipeline/runs/{started['run_id']}?after_seq=3")["events"]
        self.assertEqual([e["seq"] for e in later], [s for s in seqs if s > 3])

        saved = self.get("/api/pipeline/saved")["runs"]
        self.assertEqual([item["run_id"] for item in saved], [started["run_id"]])
        self.assertTrue(saved[0]["summary"])
        # 서버 메모리를 비워도 저장 파일로 다시 볼 수 있다.
        self.server.pipeline.runs.clear()
        reloaded = self.get(f"/api/pipeline/runs/{started['run_id']}")
        self.assertEqual(reloaded["result"]["report"], done["result"]["report"])
        self.assertEqual(len(reloaded["events"]), len(done["events"]))

    def test_planning_request_reuses_welfare_snapshot_and_selected_resources(self):
        request = planning_fixture()
        self.post("/api/planning/requests", request)
        with patch("ai.nodes.welfare.recommend") as offline_lookup, \
                patch("ai.nodes.welfare.recommend_live") as live_lookup:
            _, started = self.post("/api/pipeline/runs", {"mode": "offline", "request_id": request["request_id"]})
            done = self.wait(started["run_id"])
        offline_lookup.assert_not_called()
        live_lookup.assert_not_called()
        self.assertEqual(done["source"]["kind"], "planning_request")
        self.assertEqual(done["officer_request"], request["officer_prompt"])
        existing = done["result"]["existing_resources"]
        self.assertEqual([r["id"] for r in existing["resources"]], [r["id"] for r in request["selected_resources"]])
        self.assertEqual(done["result"]["profile"]["target"]["sex"], "female")
        self.assertEqual(done["status"], "completed")

    def test_failed_lookup_request_still_plans_with_unavailable_resources(self):
        request = planning_fixture()
        request.update(planning_type="preventive_new", selected_resources=[])
        request["welfare_lookup"].update(status="unavailable", candidate_status="unavailable", total_candidates=None,
                                         error="검색 한도 초과", recommendation_snapshot=None)
        self.post("/api/planning/requests", request)
        _, started = self.post("/api/pipeline/runs", {"mode": "offline", "request_id": request["request_id"]})
        done = self.wait(started["run_id"])
        self.assertEqual(done["result"]["existing_resources"]["status"], "unavailable")
        self.assertIn("검색 한도 초과", done["result"]["existing_resources"]["reason"])

    def test_invalid_inputs_are_rejected_in_korean(self):
        cases = [({"mode": "offline"}, 400), ({"mode": "batch", "profile": PROFILE}, 400),
                 ({"mode": "offline", "profile": {**PROFILE, "extra": 1}}, 400),
                 ({"mode": "offline", "profile": PROFILE, "request_id": "x"}, 400),
                 ({"mode": "offline", "request_id": "../bad"}, 400),
                 ({"mode": "offline", "request_id": "00000000-0000-4000-8000-000000000000"}, 404)]
        for body, code in cases:
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                self.post("/api/pipeline/runs", body)
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(json.load(caught.exception)["error"])
        for path in ("/api/pipeline/runs/run-000000000000", "/api/pipeline/runs/..%2Fsecret"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.get(path)
            self.assertEqual(caught.exception.code, 404)

    def test_live_requires_keys(self):
        with patch("backend.pipeline.config_status", return_value={"configured": False}), \
                self.assertRaises(HTTPError) as caught:
            self.post("/api/pipeline/runs", {"mode": "live", "profile": PROFILE})
        self.assertEqual(caught.exception.code, 503)

    def test_one_run_at_a_time_and_live_slot_is_shared(self):
        gate = Event()

        def slow_causes(ctx, profile):
            gate.wait(5)
            return cause_rules.analyze_causes(ctx, profile)

        self.server.pipeline.engines = replace(self.engines, analyze_causes=slow_causes)
        _, started = self.post("/api/pipeline/runs", {"mode": "offline", "profile": PROFILE})
        try:
            with self.assertRaises(HTTPError) as caught:
                self.post("/api/pipeline/runs", {"mode": "offline", "profile": PROFILE})
            self.assertEqual(caught.exception.code, 409)
        finally:
            gate.set()
        self.wait(started["run_id"])

        # 복지 추천·분석이 LIVE_SLOT을 쓰는 중이면 live 통합 실행은 시작하지 않는다.
        self.assertTrue(LIVE_SLOT.acquire(blocking=False))
        try:
            with patch("backend.pipeline.config_status", return_value={"configured": True}), \
                    self.assertRaises(HTTPError) as caught:
                self.post("/api/pipeline/runs", {"mode": "live", "profile": PROFILE})
            self.assertEqual(caught.exception.code, 409)
        finally:
            LIVE_SLOT.release()


class ManualEvaluateApiTests(ApiCase):
    """POST /api/program/evaluate: 저장된 실행의 맥락으로 담당자 기획안을 채점한다 (설계 문서 6.1)."""

    def completed_run(self):
        _, started = self.post("/api/pipeline/runs", {"mode": "offline", "profile": PROFILE})
        return self.wait(started["run_id"])

    def test_edited_plan_is_scored_as_manual_and_compared_with_original(self):
        run = self.completed_run()
        plan = dict(run["result"]["plans"][0])
        plan["kpis"] = [{"name": "참여율", "definition": "등록 인원 대비 출석 비율", "data_source": "운영 기록",
                         "measurable_by_data": False}]
        status, body = self.post("/api/program/evaluate", {"mode": "offline", "run_id": run["run_id"], "plan": plan})
        self.assertEqual(status, 200)
        self.assertEqual(body["plan"]["source"], "manual")
        self.assertEqual(body["original_evaluation"]["plan_id"], plan["plan_id"])
        self.assertFalse(body["evaluation"]["llm_axis_available"])  # offline이면 규칙 85점을 100점으로 환산
        self.assertEqual(body["external_calls"], {})
        axes = {axis["axis"]: axis for axis in body["evaluation"]["axes"]}
        self.assertEqual(axes["measurability"]["score"], 5)  # 집단 단위 데이터 KPI가 빠져 5점 감점

    def test_rejects_other_target_unknown_run_and_bad_plan(self):
        run = self.completed_run()
        plan = run["result"]["plans"][0]
        other = {**plan, "target": {**plan["target"], "age_group": 10 if plan["target"]["age_group"] != 10 else 20}}
        cases = [({"run_id": run["run_id"], "plan": other}, 400, "대상"),
                 ({"run_id": "run-000000000000", "plan": plan}, 404, "저장된"),
                 ({"run_id": run["run_id"], "plan": {**plan, "kpis": []}}, 400, "kpis"),
                 ({"run_id": run["run_id"]}, 400, "plan")]
        for data, code, word in cases:
            with self.subTest(code=code, word=word), self.assertRaises(HTTPError) as caught:
                self.post("/api/program/evaluate", data)
            self.assertEqual(caught.exception.code, code)
            self.assertIn(word, json.load(caught.exception)["error"])

    def test_live_uses_shared_slot(self):
        run = self.completed_run()
        plan = run["result"]["plans"][0]
        self.assertTrue(LIVE_SLOT.acquire(blocking=False))
        try:
            with patch("backend.pipeline.config_status", return_value={"configured": True}), \
                    self.assertRaises(HTTPError) as caught:
                self.post("/api/program/evaluate", {"mode": "live", "run_id": run["run_id"], "plan": plan})
            self.assertEqual(caught.exception.code, 409)
        finally:
            LIVE_SLOT.release()


if __name__ == "__main__":
    unittest.main()
