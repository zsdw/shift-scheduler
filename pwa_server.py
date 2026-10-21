"""홈 화면 앱(PWA) 설치용 파일 서버 (2026-10-22).

Tailscale은 폴더를 직접 공유하려면 Windows 관리자 권한이 필요해서, 근무표 앱이 켜질 때 pwa/ 폴더만 내주는
작은 서버를 PC 안(127.0.0.1:8510)에 함께 띄운다. 폰은 Tailscale `/pwa` → 8510으로 들어온다.
앱이 다시 실행돼도 이미 떠 있으면(포트 사용 중) 그대로 둔다.
"""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8510
ROOT = Path(__file__).resolve().parent / "pwa"


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".json": "application/manifest+json",
                      ".js": "text/javascript"}

    def translate_path(self, path):
        # Tailscale이 '/pwa'를 떼고 넘기든 그대로 넘기든 같은 파일을 준다
        if path == "/pwa" or path.startswith("/pwa/") or path.startswith("/pwa?"):
            path = path[4:] or "/"
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Service-Worker-Allowed", "/pwa/")
        super().end_headers()

    def log_message(self, *args):          # 앱 콘솔을 어지럽히지 않게
        pass


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False            # Windows에서는 재사용 허용이면 같은 포트에 두 번 붙는다

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start() -> bool:
    """서버를 띄운다. 이미 떠 있으면 False."""
    try:
        server = _Server(("127.0.0.1", PORT), partial(_Handler, directory=str(ROOT)))
    except OSError:
        return False
    threading.Thread(target=server.serve_forever, name="pwa-server", daemon=True).start()
    return True


if __name__ == "__main__":                 # launch_night_shift.ps1이 PC 시작 때 따로 띄운다
    import time
    if start():
        while True:
            time.sleep(3600)
