"""Unit and integration tests for img_server.py."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlencode
import zipfile

from PIL import Image

import img_server


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


@contextmanager
def running_server(**config_kwargs):
    config = img_server.resolve_config(host="127.0.0.1", port=0, **config_kwargs)
    httpd = img_server.create_server(config)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, config, httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def http_request(port: int, method: str, path: str, *, headers=None, body: bytes | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, dict(resp.getheaders()), data
    finally:
        conn.close()


class ImgServerConfigTests(unittest.TestCase):
    def test_config_priority_and_dotenv_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "img").mkdir()
            (root / ".env").write_text(
                "# comment\n"
                "IMG_SERVER_TOKEN='dotenv-secret'\n"
                "IMG_SERVER_HOST=127.0.0.1\n"
                "IMG_SERVER_PORT=9001\n",
                encoding="utf-8",
            )
            cfg = img_server.resolve_config(root=root, env={})
            self.assertEqual(cfg.token, "dotenv-secret")
            self.assertEqual(cfg.token_source, ".env")
            self.assertEqual(cfg.host, "127.0.0.1")
            self.assertEqual(cfg.port, 9001)

            cfg_env = img_server.resolve_config(
                root=root,
                env={"IMG_SERVER_TOKEN": "env-secret", "IMG_SERVER_PORT": "9002"},
            )
            self.assertEqual(cfg_env.token, "env-secret")
            self.assertEqual(cfg_env.token_source, "env")
            self.assertEqual(cfg_env.port, 9002)

            cfg_cli = img_server.resolve_config(
                root=root,
                env={"IMG_SERVER_TOKEN": "env-secret"},
                token="cli-secret",
                port=9003,
            )
            self.assertEqual(cfg_cli.token, "cli-secret")
            self.assertEqual(cfg_cli.token_source, "cli")
            self.assertEqual(cfg_cli.port, 9003)

    def test_generates_token_when_unset_and_rejects_bad_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("IMG_SERVER_TOKEN=\n", encoding="utf-8")
            cfg = img_server.resolve_config(root=root, env={})
            self.assertEqual(cfg.token_source, "generated")
            self.assertGreaterEqual(len(cfg.token), 32)
            self.assertTrue((root / "img").is_dir())

            with self.assertRaises(ValueError):
                img_server.resolve_config(root=root, env={}, token="bad token with space")

    def test_redact_path_for_log(self):
        self.assertEqual(
            img_server.redact_path_for_log("/download/a.png?download=1&token=mysecret123&sha256=1"),
            "/download/a.png?download=1&token=***&sha256=1",
        )


class ImgServerHTTPTests(unittest.TestCase):
    def test_token_authentication_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp) / "img"
            img_dir.mkdir()
            (img_dir / "sample.png").write_bytes(TINY_PNG)
            token = "test-secret-token-123"

            with running_server(img_dir=img_dir, token=token, root=Path(tmp)) as (_, _, port):
                status, _, data = http_request(port, "GET", "/health")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data), {"status": "ok"})

                status, headers, _ = http_request(port, "GET", "/api/images")
                self.assertEqual(status, 401)
                self.assertIn("Bearer", headers.get("WWW-Authenticate", ""))

                status, _, data = http_request(port, "HEAD", "/api/images")
                self.assertEqual(status, 401)
                self.assertEqual(data, b"")

                for hdrs in (
                    {"Authorization": f"Bearer {token}"},
                    {"Authorization": f"bearer {token}"},
                    {"X-Token": token},
                    {"X-API-Key": token},
                ):
                    status, _, data = http_request(port, "GET", "/api/images", headers=hdrs)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(data)["count"], 1)

                status, _, _ = http_request(port, "GET", f"/api/images?token={token}")
                self.assertEqual(status, 200)

                status, _, _ = http_request(
                    port,
                    "GET",
                    f"/api/images?token={token}",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(status, 401)

            with running_server(img_dir=img_dir, token=token, allow_query_token=False, root=Path(tmp)) as (_, _, port):
                status, _, _ = http_request(port, "GET", f"/api/images?token={token}")
                self.assertEqual(status, 401)
                status, _, _ = http_request(port, "GET", "/api/images", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(status, 200)

    def test_swagger_docs_describe_public_and_authenticated_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir = root / "img"
            img_dir.mkdir()
            with running_server(img_dir=img_dir, token="swagger-test-token", root=root) as (_, _, port):
                status, headers, page = http_request(port, "GET", "/docs")
                self.assertEqual(status, 200)
                self.assertIn(b'/docs/swagger-ui-bundle.js', page)
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertEqual(http_request(port, "GET", "/docs/")[2], page)
                self.assertEqual(http_request(port, "HEAD", "/docs")[2], b"")
                for path, mime in (("/docs/swagger-ui-bundle.js", "text/javascript"), ("/docs/init.js", "text/javascript"),
                                   ("/docs/swagger-ui.css", "text/css")):
                    status, headers, body = http_request(port, "GET", path)
                    self.assertEqual(status, 200)
                    self.assertTrue(headers["Content-Type"].startswith(mime))
                    self.assertTrue(body)
                self.assertEqual(http_request(port, "GET", "/docs/../.env")[0], 401)

                status, _, raw = http_request(port, "GET", "/openapi.json")
                self.assertEqual(status, 200)
                self.assertNotIn(b"swagger-test-token", raw)
                spec = json.loads(raw)
                actual = {path: set(operations) - {"options"} for path, operations in spec["paths"].items()}
                get_head = {"get", "head"}
                self.assertEqual(actual, {
                    path: get_head for path in (
                        "/", "/health", "/docs", "/docs/", "/openapi.json", "/img", "/img/", "/api/images", "/api/files",
                        "/download/{relpath}", "/api/meta/{relpath}", "/api/thumb/{relpath}", "/api/queue",
                        "/api/archive", "/download-all", "/api/tags/schema",
                    )
                } | {
                    "/img/{relpath}": {"get", "head", "put"}, "/api/claims": {"post", "put", "patch", "delete"},
                    "/api/claims/update": {"post"}, "/api/claims/batch": {"post"}, "/api/tags": {"patch"},
                    "/api/tags/batch": {"post"}, "/api/upload": {"post"},
                })
                self.assertIn({"QueryToken": []}, spec["security"])
                self.assertEqual(spec["paths"]["/health"]["get"]["security"], [])
                self.assertNotIn("security", spec["paths"]["/api/images"]["get"])
                self.assertEqual(spec["paths"]["/api/images"]["options"]["security"], [])
                self.assertEqual(http_request(port, "GET", "/api/images")[0], 401)
                self.assertEqual(http_request(port, "GET", "/api/images", headers={"Authorization": "Bearer swagger-test-token"})[0], 200)

            with running_server(img_dir=img_dir, token="swagger-test-token", allow_query_token=False, root=root) as (_, _, port):
                _, _, raw = http_request(port, "GET", "/openapi.json")
                spec = json.loads(raw)
                self.assertNotIn("QueryToken", spec["components"]["securitySchemes"])
                self.assertEqual(http_request(port, "GET", "/api/images?token=swagger-test-token")[0], 401)

    def test_listing_download_chinese_paths_range_etag_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir = root / "img"
            nested = img_dir / "居家场景"
            nested.mkdir(parents=True)
            img_path = nested / "示例图.png"
            payload = TINY_PNG + b"0123456789ABCDEF"
            img_path.write_bytes(payload)
            (img_dir / ".hidden.png").write_bytes(TINY_PNG)
            (img_dir / "notes.txt").write_text("not an image", encoding="utf-8")
            (img_dir / "vector.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")

            outside = root / "secret.png"
            outside.write_bytes(TINY_PNG)
            try:
                (img_dir / "escape.png").symlink_to(outside)
            except OSError:
                pass

            token = "transfer-token-abc"
            auth = {"Authorization": f"Bearer {token}"}

            with running_server(img_dir=img_dir, token=token, root=root) as (_, _, port):
                status, _, data = http_request(port, "GET", "/api/images", headers=auth)
                self.assertEqual(status, 200)
                listing = json.loads(data)
                listed_paths = [item["path"] for item in listing["images"]]
                self.assertEqual(listed_paths, ["vector.svg", "居家场景/示例图.png"])

                # Path traversal and disallowed files must be blocked
                for bad_path in (
                    "/img/../secret.png",
                    "/img/%2e%2e/secret.png",
                    "/img/.hidden.png",
                    "/img/notes.txt",
                    "/img/escape.png",
                ):
                    status, _, _ = http_request(port, "GET", bad_path, headers=auth)
                    self.assertIn(status, (400, 403, 404))

                # Inline view vs forced attachment download
                encoded_rel = quote("居家场景/示例图.png", safe="/")
                status, headers, body = http_request(port, "GET", f"/img/{encoded_rel}?sha256=1", headers=auth)
                self.assertEqual(status, 200)
                self.assertEqual(body, payload)
                self.assertEqual(headers["Content-Type"], "image/png")
                self.assertTrue(headers["Content-Disposition"].startswith("inline;"))
                self.assertEqual(headers["X-File-SHA256"], hashlib.sha256(payload).hexdigest())

                status, headers, body = http_request(port, "GET", f"/download/{encoded_rel}", headers=auth)
                self.assertEqual(status, 200)
                self.assertEqual(body, payload)
                self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
                self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])

                # SVG forces attachment and CSP sandbox
                status, headers, _ = http_request(port, "GET", "/img/vector.svg", headers=auth)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
                self.assertIn("sandbox", headers.get("Content-Security-Policy", ""))

                # HEAD request sends headers with empty body
                status, headers, body = http_request(port, "HEAD", f"/download/{encoded_rel}", headers=auth)
                self.assertEqual(status, 200)
                self.assertEqual(int(headers["Content-Length"]), len(payload))
                self.assertEqual(body, b"")

                # ETag conditional request
                etag = headers["ETag"]
                status, _, body = http_request(
                    port,
                    "GET",
                    f"/img/{encoded_rel}",
                    headers={**auth, "If-None-Match": etag},
                )
                self.assertEqual(status, 304)
                self.assertEqual(body, b"")

                # Byte Range requests
                status, headers, body = http_request(
                    port,
                    "GET",
                    f"/download/{encoded_rel}",
                    headers={**auth, "Range": "bytes=0-7"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, payload[:8])
                self.assertEqual(headers["Content-Range"], f"bytes 0-7/{len(payload)}")

                status, _, body = http_request(
                    port,
                    "GET",
                    f"/download/{encoded_rel}",
                    headers={**auth, "Range": "bytes=-6"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, payload[-6:])

                status, headers, _ = http_request(
                    port,
                    "GET",
                    f"/download/{encoded_rel}",
                    headers={**auth, "Range": "bytes=99999-"},
                )
                self.assertEqual(status, 416)
                self.assertEqual(headers["Content-Range"], f"bytes */{len(payload)}")

                # Metadata endpoint
                status, _, data = http_request(port, "GET", f"/api/meta/{encoded_rel}", headers=auth)
                self.assertEqual(status, 200)
                meta = json.loads(data)
                self.assertEqual(meta["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(meta["size"], len(payload))

                # HTML gallery does not embed the secret token
                status, headers, html_body = http_request(
                    port,
                    "GET",
                    "/",
                    headers={**auth, "Accept": "text/html"},
                )
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers["Content-Type"])
                self.assertNotIn(token.encode("utf-8"), html_body)

    def test_batch_archive_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir = root / "img"
            (img_dir / "a").mkdir(parents=True)
            (img_dir / "b").mkdir(parents=True)
            (img_dir / "a" / "one.png").write_bytes(TINY_PNG)
            (img_dir / "b" / "two.jpg").write_bytes(b"\xff\xd8\xff\xe0testjpg")

            token = "zip-token"
            auth = {"Authorization": f"Bearer {token}"}
            with running_server(img_dir=img_dir, token=token, root=root) as (_, _, port):
                status, headers, data = http_request(port, "GET", "/api/archive", headers=auth)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/zip")
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    self.assertEqual(sorted(zf.namelist()), ["a/one.png", "b/two.jpg"])
                    self.assertEqual(zf.read("a/one.png"), TINY_PNG)

                status, _, data = http_request(port, "GET", "/api/archive?prefix=b", headers=auth)
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    self.assertEqual(zf.namelist(), ["b/two.jpg"])

                status, _, data = http_request(port, "GET", "/api/archive?path=a/one.png&prefix=b", headers=auth)
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    self.assertEqual(zf.namelist(), ["a/one.png"])

                status, _, _ = http_request(port, "GET", "/api/archive?prefix=missing", headers=auth)
                self.assertEqual(status, 404)

    def test_upload_disabled_by_default_and_works_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir = root / "img"
            img_dir.mkdir()
            token = "upload-token"
            auth = {"Authorization": f"Bearer {token}"}

            with running_server(img_dir=img_dir, token=token, root=root) as (_, _, port):
                status, _, _ = http_request(port, "PUT", "/img/test.png", headers=auth, body=TINY_PNG)
                self.assertEqual(status, 403)
                status, _, _ = http_request(port, "POST", "/api/upload?path=test.png", headers=auth, body=TINY_PNG)
                self.assertEqual(status, 403)

            with running_server(
                img_dir=img_dir,
                token=token,
                allow_upload=True,
                max_upload_mb=0.001,  # ~1024 bytes
                root=root,
            ) as (_, _, port):
                # PUT upload creates file
                status, _, data = http_request(
                    port,
                    "PUT",
                    "/img/sub/uploaded.png",
                    headers={**auth, "Content-Length": str(len(TINY_PNG))},
                    body=TINY_PNG,
                )
                self.assertEqual(status, 201)
                self.assertEqual((img_dir / "sub" / "uploaded.png").read_bytes(), TINY_PNG)
                self.assertEqual(json.loads(data)["uploaded"][0]["path"], "sub/uploaded.png")

                # Overwrite returns 200
                status, _, _ = http_request(
                    port,
                    "PUT",
                    "/img/sub/uploaded.png",
                    headers={**auth, "Content-Length": str(len(TINY_PNG))},
                    body=TINY_PNG,
                )
                self.assertEqual(status, 200)

                # Reject non-image and path traversal and oversize
                status, _, _ = http_request(port, "PUT", "/img/evil.sh", headers=auth, body=b"echo hi")
                self.assertEqual(status, 400)

                status, _, _ = http_request(port, "PUT", "/img/../outside.png", headers=auth, body=TINY_PNG)
                self.assertEqual(status, 403)

                status, _, _ = http_request(port, "PUT", "/img/big.png", headers=auth, body=b"x" * 2048)
                self.assertEqual(status, 413)

                # Multipart POST upload
                boundary = "----TestBoundary789"
                multipart_body = (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="dir"\r\n\r\n'
                    "batch\r\n"
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="file"; filename="photo.jpg"\r\n'
                    "Content-Type: image/jpeg\r\n\r\n"
                ).encode("utf-8") + b"\xff\xd8\xff\xe0abc" + f"\r\n--{boundary}--\r\n".encode("utf-8")
                status, _, data = http_request(
                    port,
                    "POST",
                    "/api/upload",
                    headers={
                        **auth,
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                        "Content-Length": str(len(multipart_body)),
                    },
                    body=multipart_body,
                )
                self.assertEqual(status, 201)
                self.assertEqual(json.loads(data)["uploaded"][0]["path"], "batch/photo.jpg")
                self.assertEqual((img_dir / "batch" / "photo.jpg").read_bytes(), b"\xff\xd8\xff\xe0abc")


class ClaimTrackingTests(unittest.TestCase):
    def _request(self, port, method, url, data=None):
        headers = {"Authorization": "Bearer test-tag-token"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode() if data is not None else None
        return http_request(port, method, url, headers=headers, body=body)

    def _setup_project(self, root: Path):
        img_dir = root / "img"
        (img_dir / "居家场景" / "工具五金").mkdir(parents=True)
        (img_dir / "居家场景" / "工具五金" / "zb-hardware-1234.png").write_bytes(TINY_PNG + b"AA")
        (img_dir / "local_only.png").write_bytes(TINY_PNG + b"BB")

        url1 = "https://commons.wikimedia.org/wiki/File:Tools%2C_Wall.jpg"
        url2 = "https://commons.wikimedia.org/wiki/File:Second_Image.jpg"
        ledger_record = {
            "page_id": 1234,
            "category": "居家场景/工具五金",
            "file": "images/居家场景/工具五金/zb-hardware-1234.png",
            "source_page": "https://commons.wikimedia.org/wiki/File:Tools,_Wall.jpg",
        }
        (root / "来源与许可.jsonl").write_text(json.dumps(ledger_record, ensure_ascii=False) + "\n", encoding="utf-8")

        db_path = root / "采集数据.sqlite"
        with sqlite3.connect(db_path) as db:
            db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            db.executemany(
                "INSERT INTO collection_queue (id, file_url, category) VALUES (?, ?, ?)",
                [(1, url1, "居家场景/工具五金"), (2, url2, "居家场景/工具五金")],
            )
        return img_dir, db_path, url1, url2

    def test_download_auto_claims_and_blocks_duplicate_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            token = "claim-token"
            auth = {"Authorization": f"Bearer {token}"}
            encoded_rel = quote("居家场景/工具五金/zb-hardware-1234.png", safe="/")

            with running_server(img_dir=img_dir, db_path=db_path, token=token, root=root) as (_, _, port):
                # HEAD does not claim
                status, _, _ = http_request(port, "HEAD", f"/download/{encoded_rel}", headers=auth)
                self.assertEqual(status, 200)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT claimed_by FROM collection_queue WHERE id=1").fetchone()[0], "")

                # First GET download with Chinese claimer claims the queue row
                status, headers, body = http_request(
                    port,
                    "GET",
                    f"/download/{encoded_rel}?claimer={quote('张三')}",
                    headers=auth,
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, TINY_PNG + b"AA")
                self.assertIn("X-Claimed-By", headers)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT claimed_by FROM collection_queue WHERE id=1").fetchone()[0], "张三")

                # Different user or anonymous GET is blocked with 409
                status, _, err_body = http_request(port, "GET", f"/download/{encoded_rel}?claimer={quote('李四')}", headers=auth)
                self.assertEqual(status, 409)
                self.assertEqual(json.loads(err_body)["claimed_by"], "张三")

                status, _, _ = http_request(port, "GET", f"/img/{encoded_rel}", headers=auth)
                self.assertEqual(status, 409)

                # Original claimer can resume/re-download using X-Claimer header
                status, _, range_body = http_request(
                    port,
                    "GET",
                    f"/download/{encoded_rel}",
                    headers={**auth, "X-Claimer": "张三".encode("utf-8").decode("latin-1"), "Range": "bytes=-2"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(range_body, b"AA")

                # Archive fails with 409 if claimed file belongs to someone else, succeeds with only_unclaimed=1
                status, _, _ = http_request(port, "GET", "/api/archive?claimer=bob", headers=auth)
                self.assertEqual(status, 409)

                status, _, zip_data = http_request(port, "GET", "/api/archive?only_unclaimed=1&claimer=bob", headers=auth)
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                    self.assertEqual(zf.namelist(), ["local_only.png"])

                # local_only.png is now claimed by bob; anonymous download gets 409
                status, _, _ = http_request(port, "GET", "/download/local_only.png", headers=auth)
                self.assertEqual(status, 409)

    def test_claim_modify_transfer_release_batch_and_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, url1, url2 = self._setup_project(root)
            with sqlite3.connect(db_path) as db:
                db.execute(
                    "INSERT INTO collection_queue (id, file_url, category) VALUES (?, ?, ?)",
                    (3, "https://commons.wikimedia.org/wiki/File:Third_Image.jpg", "公共场景/市场摊位"),
                )
            token = "api-claim-token"
            auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            with running_server(img_dir=img_dir, db_path=db_path, token=token, root=root) as (_, _, port):
                # Claim next atomically across two concurrent threads on id=1? Let's race id=1 specifically!
                results = []
                barrier = threading.Barrier(2)

                def race(name: str):
                    barrier.wait()
                    st, _, raw = http_request(
                        port,
                        "POST",
                        "/api/claims",
                        headers=auth,
                        body=json.dumps({"id": 1, "claimer": name}).encode("utf-8"),
                    )
                    results.append((name, st, json.loads(raw)))

                t1 = threading.Thread(target=race, args=("alice",))
                t2 = threading.Thread(target=race, args=("bob",))
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                statuses = sorted(r[1] for r in results)
                self.assertEqual(statuses, [200, 409])
                winner = next(r[0] for r in results if r[1] == 200)
                loser = next(r[0] for r in results if r[1] == 409)

                # Non-claimer cannot modify/transfer
                status, _, _ = http_request(
                    port,
                    "PATCH",
                    "/api/claims",
                    headers=auth,
                    body=json.dumps({"id": 1, "claimer": loser, "new_claimed_by": loser}).encode("utf-8"),
                )
                self.assertEqual(status, 409)

                # Winner transfers claim to charlie
                status, _, data = http_request(
                    port,
                    "PATCH",
                    "/api/claims",
                    headers=auth,
                    body=json.dumps({"id": 1, "claimer": winner, "new_claimed_by": "charlie"}).encode("utf-8"),
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["claimed_by"], "charlie")

                # Charlie can now download; winner cannot
                encoded_rel = quote("居家场景/工具五金/zb-hardware-1234.png", safe="/")
                status, _, _ = http_request(port, "GET", f"/download/{encoded_rel}?claimer={winner}", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(status, 409)
                status, _, _ = http_request(port, "GET", f"/download/{encoded_rel}?claimer=charlie", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(status, 200)

                # Charlie releases claim via DELETE
                status, _, data = http_request(
                    port,
                    "DELETE",
                    "/api/claims",
                    headers=auth,
                    body=json.dumps({"id": 1, "claimer": "charlie"}).encode("utf-8"),
                )
                self.assertEqual(status, 200)
                self.assertFalse(json.loads(data)["claimed"])

                # Claim next unclaimed item (picks id=1 now that it was released)
                status, _, data = http_request(
                    port,
                    "POST",
                    "/api/claims",
                    headers=auth,
                    body=json.dumps({"next": True, "claimer": "dave"}).encode("utf-8"),
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)["id"], 1)

                # Batch mark remaining items and check queue summary
                status, _, data = http_request(
                    port,
                    "POST",
                    "/api/claims/batch",
                    headers=auth,
                    body=json.dumps({"claimer": "historical_user", "ids": [1, 2, 3], "skip_claimed": True}).encode("utf-8"),
                )
                self.assertEqual(status, 200)
                batch_res = json.loads(data)
                self.assertEqual(batch_res["updated_count"], 2)
                self.assertEqual(batch_res["skipped_count"], 1)

                status, _, q_data = http_request(port, "GET", "/api/queue?status=claimed", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(status, 200)
                q_json = json.loads(q_data)
                self.assertEqual(q_json["claimed_count"], 3)
                self.assertEqual(q_json["unclaimed_count"], 0)

    def test_auto_migrates_legacy_sqlite_table_without_claimed_by(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir = root / "img"
            img_dir.mkdir()
            db_path = root / "legacy.sqlite"
            with sqlite3.connect(db_path) as db:
                db.execute(
                    "CREATE TABLE collection_queue (id INTEGER PRIMARY KEY, file_url TEXT NOT NULL UNIQUE, category TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO collection_queue (id, file_url, category) VALUES (1, 'https://commons.wikimedia.org/wiki/File:Old.jpg', '居家场景/工具五金')"
                )
                db.execute("CREATE TABLE img_claims (file_path TEXT PRIMARY KEY, claimed_by TEXT NOT NULL, updated_at TEXT NOT NULL)")
                db.execute("INSERT INTO img_claims VALUES ('old-local.png', 'alice', '')")
            store = img_server.ClaimStore(db_path, img_dir)
            self.assertEqual(store.list_queue()["unclaimed_count"], 1)
            img_server.ClaimStore(db_path, img_dir)
            with sqlite3.connect(db_path) as db:
                for table in ("collection_queue", "img_claims"):
                    columns = {row[1]: row[2:5] for row in db.execute(f"PRAGMA table_info({table})")}
                    for field in ("question_types", "difficulty", "difficulty_tags", "tag_notes", "authored_status", "authored_ref"):
                        self.assertEqual(columns[field], ("TEXT", 1, "''"))
                self.assertEqual(db.execute(
                    "SELECT file_path, claimed_by, question_types, authored_status, authored_ref FROM img_claims"
                ).fetchone(), ("old-local.png", "alice", "", "", ""))

    def test_tag_api_validation_and_canonical_batch_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, url1, _ = self._setup_project(root)
            path = "居家场景/工具五金/zb-hardware-1234.png"
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                for method, endpoint in (("GET", "/api/tags/schema"), ("PATCH", "/api/tags"), ("POST", "/api/tags/batch")):
                    self.assertEqual(http_request(port, method, endpoint)[0], 401)

                status, _, body = self._request(port, "GET", "/api/tags/schema")
                self.assertEqual(status, 200)
                schema = json.loads(body)
                self.assertEqual(len(schema["question_types"]), 8)
                self.assertEqual(len(schema["difficulty_tags"]), 9)
                self.assertEqual(schema["difficulty"][2]["label"], "困难")

                for invalid in ({"id": True}, {"id": 2**100}, {"path": ""}, {"id": 1, "file_url": ""}, {},
                                {"id": 1, "difficulty": "very-hard"}, {"id": 1, "difficulty_tags": "small_target"},
                                {"id": 1, "question_types": ["typo"]}):
                    with self.subTest(invalid=invalid):
                        self.assertEqual(self._request(port, "PATCH", "/api/tags", {"tag_notes": "x", **invalid})[0], 400)
                for duplicate in ({"file_url": url1}, {"path": quote(path, safe="/")}):
                    status, _, body = self._request(port, "POST", "/api/tags/batch", {"items": [
                        {"id": 1, "difficulty": "easy"}, {**duplicate, "difficulty": "hard"},
                    ]})
                    self.assertEqual(status, 400)
                    self.assertEqual(json.loads(body)["index"], 1)
                self.assertEqual(self._request(port, "PATCH", "/api/tags", {"path": "../outside.png", "tag_notes": "x"})[0], 403)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT difficulty FROM collection_queue WHERE id=1").fetchone(), ("",))

                status, _, body = self._request(port, "POST", "/api/tags/batch", {"items": [
                    {"path": path, "question_types": ["robust_ocr", "counting", "counting"], "tag_notes": "看价签"},
                    {"id": 2, "difficulty": "easy"},
                ]})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["updated_count"], 2)
                self.assertEqual(self._request(port, "PATCH", "/api/tags", {"file_url": url1, "difficulty_tags": ["small_target"]})[0], 200)
                _, _, body = self._request(port, "GET", "/api/meta/" + quote(path, safe="/"))
                item = json.loads(body)
                self.assertEqual(item["question_types"], ["counting", "robust_ocr"])
                self.assertEqual(item["difficulty_tags"], ["small_target"])
                self.assertEqual(item["tag_notes"], "看价签")
                self.assertFalse(item["claimed"])
                self.assertEqual(self._request(port, "PATCH", "/api/tags", {"id": 1, "question_types": [], "tag_notes": ""})[0], 200)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT question_types, difficulty_tags, tag_notes FROM collection_queue WHERE id=1").fetchone(),
                                     ("", "small_target", ""))
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM img_claims").fetchone(), (0,))

    def test_local_release_keeps_tags_and_does_not_claim_on_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            local_path = "local_only.png"
            fields = {"question_types": ["counting"], "difficulty": "hard", "difficulty_tags": ["high_density"],
                      "tag_notes": "第一层", "authored_status": "draft", "authored_ref": "ZB-001"}
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                status, _, raw = self._request(port, "PATCH", "/api/tags", {"path": local_path, **fields})
                self.assertEqual(status, 200)
                self.assertFalse(json.loads(raw)["claimed"])
                self.assertEqual(self._request(port, "GET", f"/download/{local_path}?claimer=alice")[0], 200)
                self.assertEqual(self._request(port, "PATCH", "/api/claims", {"path": local_path, "claimer": "alice", "new_claimed_by": "bob"})[0], 200)
                status, _, raw = self._request(port, "DELETE", "/api/claims", {"path": local_path, "claimer": "bob"})
                result = json.loads(raw)
                self.assertEqual(status, 200)
                self.assertFalse(result["claimed"])
                self.assertEqual({field: result[field] for field in fields}, fields)
                _, _, raw = self._request(port, "GET", "/api/images?tagged=1&status=unclaimed")
                self.assertEqual([item["path"] for item in json.loads(raw)["images"]], [local_path])
                self.assertEqual(self._request(port, "GET", f"/download/{local_path}?claimer=charlie")[0], 200)

    def test_authored_updates_and_filters_share_queue_and_local_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, url1, _ = self._setup_project(root)
            path = "居家场景/工具五金/zb-hardware-1234.png"
            reference = "ZB-001 | outputs/题目材料"
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                def patch_tags(data):
                    status, _, raw = self._request(port, "PATCH", "/api/tags", data)
                    self.assertEqual(status, 200, raw)
                    return json.loads(raw)

                patch_tags({"id": 1, "authored_status": "draft"})
                self.assertEqual(patch_tags({"path": path, "authored_ref": reference})["authored_status"], "draft")
                self.assertEqual(patch_tags({"file_url": url1, "authored_status": "authored"})["authored_ref"], reference)
                patch_tags({"path": "local_only.png", "authored_status": "discarded"})
                for invalid in ("done", " authored", None, 1):
                    self.assertEqual(self._request(port, "PATCH", "/api/tags", {"id": 1, "authored_status": invalid})[0], 400)
                self.assertEqual(self._request(port, "PATCH", "/api/tags", {"id": 1, "authored_ref": []})[0], 400)
                self.assertEqual(self._request(port, "POST", "/api/tags/batch", {"items": [
                    {"id": 1, "authored_status": "discarded"}, {"id": 999, "authored_ref": "missing"},
                ]})[0], 404)
                status, _, raw = self._request(port, "GET", "/api/meta/" + quote(path, safe="/"))
                self.assertEqual(status, 200)
                meta = json.loads(raw)
                self.assertEqual((meta["authored_status"], meta["authored_ref"]), ("authored", reference))

                for endpoint, key, unstarted, discarded in (
                    ("/api/images", "images", [], ["discarded"]),
                    ("/api/queue", "items", [""], []),
                ):
                    for suffix, expected in (
                        ("", ["authored", *unstarted, *discarded]),
                        ("?authored=1", ["authored"]),
                        ("?authored=0", unstarted),
                        ("?authored_status=", unstarted),
                        ("?authored_status=discarded", discarded),
                    ):
                        with self.subTest(endpoint=endpoint, suffix=suffix):
                            status, _, raw = self._request(port, "GET", endpoint + suffix)
                            self.assertEqual(status, 200)
                            items = json.loads(raw)[key]
                            self.assertCountEqual([item["authored_status"] for item in items], expected)
                            if suffix == "?authored=1":
                                self.assertEqual(items[0]["authored_ref"], reference)
                    for query in ("authored_status=done", "authored=2", "authored_status=draft&authored=1"):
                        self.assertEqual(self._request(port, "GET", endpoint + "?" + query)[0], 400)

                for query in ("authored_status=authored", "authored=1"):
                    status, _, raw = self._request(port, "GET", "/api/archive?" + query + "&claimer=alice")
                    self.assertEqual(status, 200)
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        self.assertEqual(archive.namelist(), [path])
                patch_tags({"path": "local_only.png", "authored_status": "", "authored_ref": ""})
                status, _, raw = self._request(port, "GET", "/api/images?authored=0")
                self.assertEqual(status, 200)
                self.assertEqual([item["path"] for item in json.loads(raw)["images"]], ["local_only.png"])
                for query in ("authored_status=", "authored=0"):
                    status, _, raw = self._request(port, "GET", "/api/archive?" + query + "&claimer=bob")
                    self.assertEqual(status, 200)
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        self.assertEqual(archive.namelist(), ["local_only.png"])
                self.assertEqual(self._request(port, "GET", "/api/archive?authored_status=invalid")[0], 400)

    def test_next_claim_filters_by_authored_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE collection_queue SET authored_status = 'authored' WHERE id = 1")
                db.execute("UPDATE collection_queue SET authored_status = 'draft' WHERE id = 2")
                db.execute("INSERT INTO collection_queue (id, file_url, category) VALUES (3, 'File:Third.jpg', 'other')")
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                payload = {"next": True, "claimer": "alice"}
                self.assertEqual(self._request(port, "POST", "/api/claims?authored_status=bad", payload)[0], 400)
                self.assertEqual(self._request(port, "POST", "/api/claims?authored=1", {
                    **payload, "authored_status": "",
                })[0], 400)
                for suffix, fields, expected_id in (("?authored=0", {}, 3), ("?authored_status=draft", {}, 2),
                                                    ("", {"authored_status": "authored"}, 1)):
                    status, _, raw = self._request(port, "POST", "/api/claims" + suffix, {**payload, **fields})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)["id"], expected_id)
                for released_id, fields in ((3, {"authored_status": ""}), (1, {})):
                    self.assertEqual(self._request(port, "DELETE", "/api/claims", {"id": released_id, "claimer": "alice"})[0], 200)
                    status, _, raw = self._request(port, "POST", "/api/claims", {**payload, **fields})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)["id"], released_id)

    def test_combined_filters_prefix_and_claimed_by_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE collection_queue SET question_types=?, difficulty=?, difficulty_tags=?, claimed_by=? WHERE id=1",
                           (" robust_ocr, counting, counting, invalid ", "hard", "small_target, high_density", "alice"))
                db.execute("UPDATE collection_queue SET question_types='counting', difficulty='medium' WHERE id=2")
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                self._request(port, "PATCH", "/api/tags", {"path": "local_only.png", "difficulty_tags": ["small_target"]})
                for endpoint, key in (("/api/images", "images"), ("/api/queue", "items")):
                    base = endpoint + "?question_type=counting,robust_ocr&difficulty_tag=small_target&difficulty=medium,hard"
                    status, _, raw = self._request(port, "GET", base + "&match=all&claimed_by=alice&claimer=bob")
                    self.assertEqual(status, 200)
                    items = json.loads(raw)[key]
                    self.assertEqual(len(items), 1)
                    self.assertEqual(items[0]["question_types"], ["counting", "robust_ocr"])
                    self.assertEqual(items[0]["claimed_by"], "alice")
                    status, _, raw = self._request(port, "GET", endpoint + "?claimer=alice")
                    self.assertEqual(len(json.loads(raw)[key]), 1)
                    status, _, raw = self._request(port, "GET", endpoint + "?question_type=counting,robust_ocr&match=any&status=unclaimed")
                    self.assertEqual(len(json.loads(raw)[key]), 0 if key == "images" else 1)
                    for field, value in (("question_type", "typo"), ("difficulty_tag", "typo"), ("difficulty", "typo"),
                                         ("match", "typo"), ("tagged", "2"), ("status", "typo")):
                        self.assertEqual(self._request(port, "GET", f"{endpoint}?{field}={value}")[0], 400)
                    self.assertEqual(self._request(port, "GET", endpoint + "?question_type=&difficulty=&status=&match=&tagged=")[0], 200)
                    self.assertEqual(self._request(port, "GET", endpoint + "?prefix=%2e%2e")[0], 403)

                for suffix, expected in (("居家场景/工具五金", 1), ("居家场景/工具", 0), ("居家场景/工具五金X", 0)):
                    status, _, raw = self._request(port, "GET", "/api/queue?prefix=" + quote(suffix))
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(raw)["matched_count"], expected)
                combined = urlencode({"category": "居家场景/工具五金", "prefix": "居家场景", "question_type": "counting",
                                      "difficulty_tag": "small_target,high_density", "status": "claimed"})
                status, _, raw = self._request(port, "GET", "/api/images?" + combined)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)["count"], 1)
                for query in ("difficulty=typo", "match=bad", "status=bad", "tagged=bad"):
                    self.assertEqual(self._request(port, "GET", "/api/archive?" + query)[0], 400)

    def test_filtered_claims_and_atomic_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            (img_dir / "second_local.png").write_bytes(TINY_PNG)
            with sqlite3.connect(db_path) as db:
                db.executemany("INSERT INTO collection_queue (id, file_url, category, question_types, difficulty) VALUES (?, ?, ?, ?, ?)", [
                    (3, "File:Third.jpg", "other", "counting", "hard"),
                    (4, "File:Fourth.jpg", "other", "counting", "hard"),
                ])
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (server, _, port):
                def next_claim(name):
                    status, _, raw = self._request(port, "POST", "/api/claims", {
                        "next": True, "claimer": name, "question_types": ["counting"], "difficulty": "hard",
                        "authored_status": "",
                    })
                    return status, json.loads(raw)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(next_claim, ("alice", "bob")))
                self.assertEqual({result[1]["id"] for result in results}, {3, 4})
                self.assertTrue(all(result[0] == 200 for result in results))
                self.assertEqual(self._request(port, "POST", "/api/claims", {"next": True, "claimer": "a", "difficulty": "invalid"})[0], 400)

                for path in ("local_only.png", "second_local.png"):
                    self.assertEqual(self._request(port, "PATCH", "/api/tags", {"path": path, "question_types": ["counting"]})[0], 200)

                status, _, raw = self._request(port, "HEAD", "/api/archive?question_type=counting&status=unclaimed")
                self.assertEqual((status, raw), (200, b""))
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM img_claims WHERE claimed_by <> ''").fetchone(), (0,))

                original = server.claim_store.acquire_batch_for_download
                def acquire_after_race(*args, **kwargs):
                    server.claim_store.claim_item(claimer="other", relpath="local_only.png")
                    return original(*args, **kwargs)

                with patch.object(server.claim_store, "acquire_batch_for_download", side_effect=acquire_after_race):
                    status, _, raw = self._request(port, "GET", "/api/archive?question_type=counting&status=unclaimed&claimer=alice")
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(archive.namelist(), ["second_local.png"])
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(dict(db.execute("SELECT file_path, claimed_by FROM img_claims")),
                                     {"local_only.png": "other", "second_local.png": "alice"})
                    self.assertEqual(db.execute("SELECT claimed_by FROM collection_queue WHERE id=1").fetchone(), ("",))

                status, _, raw = self._request(port, "HEAD", "/api/archive?question_type=counting&status=claimed")
                self.assertEqual((status, raw), (200, b""))
                self.assertEqual(self._request(port, "GET", "/api/archive?question_type=counting&claimer=alice")[0], 409)
                status, _, raw = self._request(port, "GET", "/api/archive?question_type=counting&only_unclaimed=1&claimer=alice")
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(archive.namelist(), ["second_local.png"])
                status, _, raw = self._request(port, "GET", "/api/archive?claimed_by=other&claimer=other")
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(archive.namelist(), ["local_only.png"])

    def test_archive_rechecks_tags_and_rolls_back_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            (img_dir / "second_local.png").write_bytes(TINY_PNG)
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (server, _, port):
                for path in ("local_only.png", "second_local.png"):
                    self.assertEqual(self._request(port, "PATCH", "/api/tags", {"path": path, "question_types": ["counting"]})[0], 200)
                self.assertEqual(self._request(port, "GET", "/download/second_local.png?claimer=other")[0], 200)
                self.assertEqual(self._request(port, "GET", "/api/archive?question_type=counting&claimer=alice")[0], 409)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(dict(db.execute("SELECT file_path, claimed_by FROM img_claims")),
                                     {"local_only.png": "", "second_local.png": "other"})
                original = server.claim_store.acquire_batch_for_download

                def update_before_transaction(*args, **kwargs):
                    self._request(port, "PATCH", "/api/tags", {"path": "local_only.png", "question_types": []})
                    return original(*args, **kwargs)

                with patch.object(server.claim_store, "acquire_batch_for_download", side_effect=update_before_transaction):
                    status, _, _ = self._request(port, "GET", "/api/archive?question_type=counting&status=unclaimed&claimer=alice")
                self.assertEqual(status, 404)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT claimed_by FROM img_claims WHERE file_path='local_only.png'").fetchone(), ("",))

                def author_before_transaction(*args, **kwargs):
                    self._request(port, "PATCH", "/api/tags", {"path": "local_only.png", "authored_status": "authored"})
                    return original(*args, **kwargs)

                with patch.object(server.claim_store, "acquire_batch_for_download", side_effect=author_before_transaction):
                    status, _, _ = self._request(port, "GET", "/api/archive?path=local_only.png&authored=0&claimer=alice")
                    self.assertEqual(status, 404)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT claimed_by FROM img_claims WHERE file_path='local_only.png'").fetchone(), ("",))

    def test_safe_thumbnails_and_no_db_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img_dir, db_path, _, _ = self._setup_project(root)
            Image.new("RGBA", (500, 200), (255, 0, 0, 128)).save(img_dir / "transparent.png")
            with Image.new("P", (100, 50)) as palette:
                palette.info["transparency"] = 0
                palette.save(img_dir / "palette.png")
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (3000, 1000), "green").save(img_dir / "large.jpg", exif=exif)
            Image.new("RGB", (60, 20), "blue").save(img_dir / "small.png")
            (img_dir / "bad.png").write_bytes(b"broken")
            (img_dir / "vector.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            (img_dir / "unsupported.heic").write_bytes(b"not a heic")
            with running_server(img_dir=img_dir, db_path=db_path, token="test-tag-token", root=root) as (_, _, port):
                self.assertEqual(http_request(port, "GET", "/api/thumb/small.png")[0], 401)
                self.assertEqual(self._request(port, "GET", "/api/thumb/%2e%2e/secret.png")[0], 403)
                self.assertEqual(self._request(port, "GET", "/api/thumb/small.png?width=1000")[0], 400)
                self.assertEqual(self._request(port, "GET", "/api/thumb/missing.png")[0], 404)
                for name, size in (("transparent.png", (360, 144)), ("palette.png", (100, 50)),
                                   ("large.jpg", (120, 360)), ("small.png", (60, 20))):
                    status, headers, body = self._request(port, "GET", "/api/thumb/" + name)
                    self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
                    with Image.open(io.BytesIO(body)) as image:
                        self.assertEqual(image.size, size)
                        self.assertEqual(image.mode, "RGB")
                        self.assertFalse(image.getexif())
                        if name == "transparent.png":
                            self.assertNotEqual(image.getpixel((5, 5)), (0, 0, 0))
                for name in ("bad.png", "vector.svg", "unsupported.heic"):
                    status, headers, body = self._request(port, "GET", "/api/thumb/" + name)
                    self.assertEqual((status, headers["Content-Type"], body), (200, "image/jpeg", img_server.THUMB_PLACEHOLDER))
                with patch.dict(sys.modules, {"PIL": None}):
                    self.assertEqual(self._request(port, "GET", "/api/thumb/small.png")[2], img_server.THUMB_PLACEHOLDER)
                with patch.object(img_server, "MAX_THUMB_PIXELS", 100):
                    self.assertEqual(self._request(port, "GET", "/api/thumb/small.png")[2], img_server.THUMB_PLACEHOLDER)
                with sqlite3.connect(db_path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM img_claims").fetchone(), (0,))
                self.assertEqual(self._request(port, "GET", "/download/small.png?claimer=alice")[0], 200)
                self.assertEqual(self._request(port, "GET", "/api/thumb/small.png")[0], 200)
                self.assertEqual(self._request(port, "GET", "/download/small.png?claimer=bob")[0], 409)

            with running_server(img_dir=img_dir, no_db=True, token="test-tag-token", root=root) as (_, _, port):
                status, _, raw = self._request(port, "GET", "/api/images?tagged=0")
                self.assertEqual(status, 200)
                self.assertTrue(all(item["question_types"] == [] and item["difficulty"] == "" for item in json.loads(raw)["images"]))
                status, _, raw = self._request(port, "GET", "/api/meta/small.png")
                self.assertEqual(status, 200)
                meta = json.loads(raw)
                self.assertEqual((meta["authored_status"], meta["authored_ref"]), ("", ""))
                self.assertEqual(self._request(port, "PATCH", "/api/tags", {"path": "small.png", "difficulty": "hard"})[0], 503)
                self.assertEqual(self._request(port, "GET", "/api/archive?question_type=counting")[0], 404)


if __name__ == "__main__":
    unittest.main()
