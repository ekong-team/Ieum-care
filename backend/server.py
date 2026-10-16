"""화면과 복지자원 후보 API를 함께 제공하는 로컬 개발 서버. 외부 배포용이 아니다."""

import argparse
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.welfare_agent.recommender import recommend, validate_request  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
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
            # 서버 내부 오류와 사용자 입력 오류를 구분한다.
            validate_request(payload)
        except (ValueError, UnicodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "요청 형식 또는 값이 올바르지 않습니다."})
            return
        try:
            result = recommend(payload)
        except Exception:
            self.log_error("복지자원 후보 처리 중 오류가 발생했습니다.")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "추천 처리에 실패했습니다. 서버 상태를 확인해주세요."})
            return
        self.send_json(HTTPStatus.OK, result)


def create_server(port=5175):
    # 프로젝트 루트·원본 데이터가 아니라 frontend 폴더만 정적 제공한다.
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT / "frontend")))


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
