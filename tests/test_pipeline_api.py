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


class PipelineApiTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
