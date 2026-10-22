"""화면과 복지자원 후보 API를 함께 제공하는 로컬 개발 서버. 외부 배포용이 아니다."""

import argparse
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import BoundedSemaphore
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.welfare_agent.recommender import recommend, validate_request  # noqa: E402
from ai.welfare_agent.live_agent import recommend_live, config_status, AgentError  # noqa: E402
from ai.contracts import ExistingResources  # noqa: E402
from ai.nodes.welfare import attach_response_routes, to_existing_resources  # noqa: E402
from ai.welfare_agent.analysis_input import prepare_analysis_inputs, latest_analysis_inputs  # noqa: E402
from ai.welfare_agent.planning_handoff import PlanningInbox  # noqa: E402

LIVE_SLOT = BoundedSemaphore(1)


def unavailable_routing():
    """HTTP 오류에서도 후보 0개와 조회 실패를 구분해 전달한다."""
    return attach_response_routes(ExistingResources(status="unavailable")).response_routing.model_dump(mode="json")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/planning/requests':
            try:
                self.send_json(HTTPStatus.OK, {'schema_version': 'planning-inbox-0.1', 'agent_connected': False,
                                              'requests': self.server.planning_inbox.list_requests()})
            except OSError:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': '기획 전달함을 읽지 못했습니다.'})
            return
        if self.path == "/api/welfare/analysis-inputs":
            try:
                result = self.server.analysis_inputs or latest_analysis_inputs(ROOT / 'data/processed/analysis_current')
                self.send_json(HTTPStatus.OK, deepcopy(result))
            except FileNotFoundError:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "아직 완료된 분석 결과가 없습니다. 분석 실행 후 다시 불러와주세요."})
            except (ValueError, KeyError, TypeError):
                self.send_json(HTTPStatus.CONFLICT, {"error": "분석 결과와 1차 순위의 검증에 실패했습니다. 분석을 다시 완료해주세요."})
            return
        if self.path == "/api/welfare/status":
            self.send_json(HTTPStatus.OK, config_status())
            return
        if not (ROOT / 'frontend/dist/index.html').exists():
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, 'Build the React frontend first: cd frontend && npm ci && npm run build')
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == '/api/planning/requests':
            if self.headers.get_content_type() != 'application/json':
                self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {'error': 'application/json 요청이 필요합니다.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2 * 1024 * 1024:
                    self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'error': '기획 요청 크기를 확인해주세요.'})
                    return
                envelope = self.server.planning_inbox.save(json.loads(self.rfile.read(length)))
            except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {'error': '기획 요청의 대상·근거·선택 자원·조회 상태가 일치하지 않습니다.'})
                return
            except OSError:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': '기획 요청을 저장하지 못했습니다. 다시 시도해주세요.'})
                return
            self.send_json(HTTPStatus.OK, envelope)
            return
        if self.path == '/api/welfare/analysis-inputs':
            # 분석 프로세스가 run_analysis() 반환값을 직접 전달하는 수신점.
            if self.headers.get_content_type() != 'application/json':
                self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {'error': 'application/json 요청이 필요합니다.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16 * 1024 * 1024:
                    self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'error': '분석 결과 크기를 확인해주세요.'})
                    return
                prepared = prepare_analysis_inputs(json.loads(self.rfile.read(length)))
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {'error': '분석 결과·해시·집단·1차 순위가 일치하지 않습니다.'})
                return
            self.server.analysis_inputs = prepared
            self.send_json(HTTPStatus.OK, {'batch_id': prepared['batch_id'], 'targets': len(prepared['entries'])})
            return
        if self.path != "/api/welfare/recommendations":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "API 경로를 찾을 수 없습니다."})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "application/json 요청이 필요합니다."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "본문은 1~16384바이트여야 합니다."})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("요청 객체가 필요합니다.")
            mode = payload.pop("mode", "live")
            if mode not in ("live", "offline"):
                raise ValueError("지원하지 않는 실행 모드입니다.")
            # 서버 내부 오류와 사용자 입력 오류를 구분한다.
            validate_request(payload)
        except (ValueError, UnicodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "요청 형식 또는 값이 올바르지 않습니다."})
            return
        try:
            if mode == "live":
                if not LIVE_SLOT.acquire(blocking=False):
                    self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "다른 AI 추천 요청이 처리 중입니다. 잠시 후 다시 시도해주세요.", "response_routing": unavailable_routing()})
                    return
                try:
                    result = recommend_live(payload)
                finally:
                    LIVE_SLOT.release()
            else:
                result = {**recommend(payload), "schema_version": "welfare-0.4", "mode": "offline"}
                result["warnings"].insert(0, "저장된 자료의 조회 테스트입니다. 외부 검색·LLM을 실행하지 않았습니다.")
            # 그래프와 화면이 같은 대응 기준을 사용한다. 추가 검색·LLM 호출은 없다.
            result["response_routing"] = to_existing_resources(result, []).response_routing.model_dump(mode="json")
        except AgentError as error:
            body = {"error": str(error), "response_routing": unavailable_routing()}
            if error.retry_after_seconds is not None:
                body["retry_after_seconds"] = error.retry_after_seconds
            self.send_json(error.status, body)
            return
        except Exception:
            self.log_error("복지자원 후보 처리 중 오류가 발생했습니다.")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "추천 처리에 실패했습니다. 서버 상태를 확인해주세요.", "response_routing": unavailable_routing()})
            return
        self.send_json(HTTPStatus.OK, result)


def create_server(port=5175, *, planning_root=None):
    # React 빌드 결과만 제공한다. 소스·설정·원본 데이터는 정적 경로에 포함하지 않는다.
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT / "frontend/dist")))
    server.analysis_inputs = None
    server.planning_inbox = PlanningInbox(planning_root or ROOT / 'data/processed/planning_requests')
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5175)
    args = parser.parse_args()
    with create_server(args.port) as server:
        print(f"Ieum care: http://127.0.0.1:{args.port}/#recommendations", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
