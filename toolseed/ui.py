"""Loopback-only, read-only ToolSeed Web UI. Python standard library only."""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import cast
from urllib.parse import parse_qs, urlsplit

from .core.inspection import InspectionError, Inspector

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def create_server(data_dir: str | None = None, port: int = 8765) -> ThreadingHTTPServer:
    inspector = Inspector(data_dir)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ToolSeedUI/0.1"

        def log_message(self, format: str, *args) -> None:
            # Request URLs can contain user searches; do not log them.
            pass

        def respond(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; img-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def json_response(self, status: int, payload: dict) -> None:
            self.respond(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

        def allowed(self) -> bool:
            authority = f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"
            # Block DNS rebinding and foreign web pages reading local management data.
            if (self.headers.get("Host") != authority
                    or self.headers.get("Origin") not in (None, f"http://{authority}")
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self.json_response(403, {"error": {"code": "LOCAL_ONLY", "message": "仅允许本机同源访问。"}})
                return False
            return True

        def do_GET(self) -> None:
            if not self.allowed():
                return
            if len(self.path) > 4096:
                self.json_response(414, {"error": {"code": "INVALID_ARGUMENT", "message": "请求过长。"}})
                return
            request = urlsplit(self.path)
            if request.path in ASSETS:
                name, mime = ASSETS[request.path]
                self.respond(200, files("toolseed").joinpath("ui_assets", name).read_bytes(), mime)
                return
            try:
                params = {key: value[-1] for key, value in parse_qs(
                    request.query, max_num_fields=12
                ).items()}
                self.json_response(200, inspector.read(request.path, params))
            except InspectionError as exc:
                status = 404 if exc.code == "NOT_FOUND" else 400 if exc.code == "INVALID_ARGUMENT" else 503
                self.json_response(status, {"error": {"code": exc.code, "message": exc.message},
                                            "data_dir": str(inspector.root)})
            except ValueError:
                self.json_response(400, {"error": {"code": "INVALID_ARGUMENT", "message": "请求参数异常。"}})

        do_HEAD = do_GET

        def reject_write(self) -> None:
            self.close_connection = True
            self.json_response(405, {"error": {"code": "READ_ONLY", "message": "面板仅支持只读查询。"}})

        do_POST = reject_write
        do_PUT = reject_write
        do_PATCH = reject_write
        do_DELETE = reject_write
        do_OPTIONS = reject_write

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolseed-ui", description="ToolSeed 本地只读面板")
    parser.add_argument("--data-dir", default=None, help="沿用 TOOLSEED_DATA_DIR / ~/.toolseed")
    parser.add_argument("--port", type=int, default=8765, help="本机端口，默认 8765")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port 必须在 0–65535 之间（0 表示自动选择）")
    try:
        server = create_server(args.data_dir, args.port)
    except (OSError, ValueError):
        print("无法启动本地面板：检查端口是否占用，以及数据目录参数。", file=sys.stderr)
        return 1
    print(f"ToolSeed UI  http://127.0.0.1:{server.server_port}", flush=True)
    print("只读 · 数据目录 " + str(Inspector(args.data_dir).root), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
