#!/usr/bin/env python3
"""Temporary read-only token-prefixed HTTP server for outputs/authoring_ZB-SHELF-63728335-v2."""
import argparse
import io
import secrets
import socket
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
DELIVERY_DIR = ROOT / "outputs" / "authoring_ZB-SHELF-63728335-v2"
ALLOWED_FILES = {
    "author_record.html": "text/html; charset=utf-8",
    "zb-shelf-63728335.jpg": "image/jpeg",
}
ZIP_NAME = "ZB-SHELF-63728335-v2.zip"


def detect_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    if "127.0.0.1" not in ips:
        ips.append("127.0.0.1")
    return ips


def make_handler(token: str):
    prefix = f"/{token}/"

    class DeliveryHandler(BaseHTTPRequestHandler):
        def _send_bytes(self, data: bytes, ctype: str, download_name: Optional[str] = None, head_only: bool = False):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

        def _handle(self, head_only: bool = False):
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if path == f"/{token}":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", prefix)
                self.end_headers()
                return
            if not path.startswith(prefix):
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            rel = path[len(prefix):]
            if rel in ("", "index.html"):
                html_doc = (
                    "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                    "<title>ZB-SHELF-63728335-v2 交付下载</title>"
                    "<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.7}"
                    "a{color:#1d4ed8;font-weight:600}li{margin:10px 0}</style></head><body>"
                    "<h1>ZB-SHELF-63728335-v2 交付文件</h1><ul>"
                    "<li><a href='author_record.html'>在线查看 author_record.html</a> "
                    "（<a href='author_record.html?download=1'>下载 HTML</a>）</li>"
                    "<li><a href='zb-shelf-63728335.jpg'>查看原图 zb-shelf-63728335.jpg</a> "
                    "（<a href='zb-shelf-63728335.jpg?download=1'>下载原图</a>）</li>"
                    f"<li><a href='{ZIP_NAME}'>一键打包下载 {ZIP_NAME}（含 HTML + 原图）</a></li>"
                    "</ul></body></html>"
                ).encode("utf-8")
                self._send_bytes(html_doc, "text/html; charset=utf-8", head_only=head_only)
                return

            if rel == ZIP_NAME:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
                    for fname in ALLOWED_FILES:
                        zf.write(DELIVERY_DIR / fname, arcname=f"authoring_ZB-SHELF-63728335-v2/{fname}")
                self._send_bytes(buf.getvalue(), "application/zip", download_name=ZIP_NAME, head_only=head_only)
                return

            if rel in ALLOWED_FILES:
                fp = DELIVERY_DIR / rel
                data = fp.read_bytes()
                dl = rel if "download=1" in parsed.query else None
                self._send_bytes(data, ALLOWED_FILES[rel], download_name=dl, head_only=head_only)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_GET(self):
            self._handle(head_only=False)

        def do_HEAD(self):
            self._handle(head_only=True)

    return DeliveryHandler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    token = args.token or secrets.token_urlsafe(16)
    handler = make_handler(token)
    server = None
    for port in (args.port, 18088, 18089, 0):
        try:
            server = ThreadingHTTPServer((args.host, port), handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("Failed to bind any TCP port")

    actual_port = server.server_address[1]
    ips = detect_ips()
    print(f"SERVING_DIR={DELIVERY_DIR}", flush=True)
    print(f"LISTEN={args.host}:{actual_port}", flush=True)
    print(f"TOKEN={token}", flush=True)
    print(f"IPS={','.join(ips)}", flush=True)
    for ip in ips:
        print(f"URL_INDEX=http://{ip}:{actual_port}/{token}/", flush=True)
        print(f"URL_HTML=http://{ip}:{actual_port}/{token}/author_record.html", flush=True)
        print(f"URL_IMG=http://{ip}:{actual_port}/{token}/zb-shelf-63728335.jpg", flush=True)
        print(f"URL_ZIP=http://{ip}:{actual_port}/{token}/{ZIP_NAME}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
