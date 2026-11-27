"""Unit tests for ZeroBench visual benchmark skill scripts."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "skills" / "zerobench-visual-benchmark" / "scripts"
SCHEMA_PATH = PROJECT_ROOT / "collection_schema.sql"
for p in (str(PROJECT_ROOT), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_trials
import inspect_images
import review_case
import sqlite_ledger


def clean_openai_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")}


def make_image(path: Path, size: tuple[int, int] = (520, 696), color: tuple[int, int, int] = (180, 90, 60)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    im.save(path, format="JPEG" if path.suffix.lower() in (".jpg", ".jpeg") else "PNG")
    return path


def make_minimal_html_case(
    case_dir: Path,
    *,
    qid: str = "ZB-TEST-0001-v1",
    img_name: str = "sample.jpg",
    img_size: tuple[int, int] = (520, 696),
    embed_data_uri: bool = True,
    prompt: str = "统计图中可见圆点个数并输出整数。",
    response: str = "3",
    point_xy: tuple[int, int] = (260, 348),
) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    img_path = make_image(case_dir / img_name, size=img_size)
    if embed_data_uri:
        b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
        src = f"data:image/jpeg;base64,{b64}"
    else:
        src = img_name

    w, h = img_size
    px, py = point_xy
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{qid}</title></head><body><main>
<h1>{qid} · 测试题目</h1>
<section id="basic"><h2>基本信息</h2><table>
<tr><th>题号</th><td id="meta-0">{qid}</td></tr>
<tr><th>题名</th><td id="meta-1">测试题目</td></tr>
<tr><th>题型</th><td id="meta-2">计数聚合链</td></tr>
<tr><th>难度</th><td id="meta-3">中等 / medium</td></tr>
<tr><th>来源</th><td id="meta-4">https://commons.wikimedia.org/wiki/File:Test.jpg</td></tr>
<tr><th>许可</th><td id="meta-5">CC BY 4.0</td></tr>
</table></section>
<section id="comparison"><h2>原图与打点对照</h2>
<div class="images">
<figure><div class="frame"><img src="{src}" width="{w}" height="{h}" alt="原图"></div></figure>
<figure><div class="frame"><img src="{src}" width="{w}" height="{h}" alt="打点图">
<span class="point" style="left:{100 * px / w:.6f}%;top:{100 * py / h:.6f}%">1</span>
</div></figure>
</div>
<pre id="points-text">1. ({px}, {py}) 关键目标</pre>
</section>
<section id="prompt"><h2>题目（prompt）</h2><pre id="prompt-text">{prompt}</pre></section>
<section id="thinking"><h2>出题思路（thinking）</h2><pre id="thinking-text">需核对低分辨率小图的完整边界。</pre></section>
<section id="understanding"><h2>图像识别（cot_image_understanding）</h2><pre id="understanding-text">图中共见 3 个区域。</pre></section>
<section id="reasoning"><h2>题目推理（cot_reasoning）</h2><pre id="reasoning-text">汇总为 3。</pre></section>
<section id="response"><h2>标准答案（response）</h2><pre id="response-text">{response}</pre></section>
</main></body></html>
"""
    html_path = case_dir / "author_record.html"
    html_path.write_text(html_text, encoding="utf-8")
    return html_path


class InspectImagesTests(unittest.TestCase):
    def test_low_resolution_image_triggers_no_size_advisory_or_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img = make_image(root / "small.png", size=(520, 696))
            manifest = {
                "items": [
                    {
                        "id": "ZB-SMALL-1",
                        "image": img.name,
                        "min_native_short_px": 1080,
                        "image_geometry": {"kind": "native"},
                        "source": {
                            "kind": "real_photo",
                            "url": "https://commons.wikimedia.org/wiki/File:Small.png",
                            "license_url": "https://creativecommons.org/licenses/by/4.0",
                            "authorization": "verified",
                        },
                        "objects": [{"id": "o1", "bbox": [10, 10, 50, 50], "category": "dot"}],
                        "category_level": "verified_task_classes",
                        "object_unit": "physical_instance",
                        "annotation_complete": True,
                        "critical_rois": [
                            {"id": "r1", "bbox": [10, 10, 60, 60], "human_readable": True},
                            {"id": "r2", "bbox": [100, 100, 60, 60], "human_readable": True},
                        ],
                        "ocr": {"han_bboxes": [], "reviewed": True},
                        "platform_points": [{"xy": [30, 30], "label": "p1"}],
                        "human_checks": {
                            "source_fidelity": True,
                            "annotation_correct": True,
                            "critical_evidence_visible": True,
                            "no_answer_leakage": True,
                            "counting_rules_clear": True,
                        },
                        "task": {
                            "active_object_ids": ["o1"],
                            "dependencies": [
                                {"roi_id": "r1", "parameter": "p1", "output": "ans"},
                                {"roi_id": "r2", "parameter": "p2", "output": "ans"},
                            ],
                            "counterfactuals": [
                                {"field": "ans", "baseline": 1, "alternative": 2, "verified": True, "evidence": "ok"}
                            ],
                            "bypass_review": "passed",
                            "reasoning_graph": {
                                "nodes": [
                                    {"id": "r1", "kind": "visual", "roi_id": "r1"},
                                    {"id": "ans", "kind": "output"},
                                ],
                                "edges": [["r1", "ans"]],
                            },
                        },
                    }
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            out_dir = root / "out"
            rc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "inspect_images.py"), str(manifest_path), "--out", str(out_dir)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(rc.returncode, 0)
            report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            row = report["items"][0]
            self.assertEqual(row["metrics"]["submitted_width"], 520)
            self.assertEqual(row["metrics"]["submitted_height"], 696)
            self.assertEqual(row["metrics"]["native_width"], 520)
            self.assertEqual(row["metrics"]["native_height"], 696)
            self.assertFalse(any("native_resolution_below_profile" in a for a in row["advisory"]))
            self.assertEqual(row["blockers"], [])
            self.assertEqual(row["decision"], "authoring_candidate")


class ReviewCaseTests(unittest.TestCase):
    def test_real_authoring_directories_have_zero_blockers(self):
        dirs = sorted(p for p in (PROJECT_ROOT / "outputs").glob("authoring_*") if p.is_dir())
        self.assertGreaterEqual(len(dirs), 9)
        with tempfile.TemporaryDirectory() as tmp:
            for idx, case_dir in enumerate(dirs):
                out_json = Path(tmp) / f"report_{idx}.json"
                rep = review_case.Reviewer(case_dir, 1080, 1920).run()
                self.assertEqual(rep["machine_blockers"], 0, f"{case_dir.name}: {rep['checks']}")
                by_code = {c["code"]: c["status"] for c in rep["checks"]}
                self.assertEqual(by_code["delivery_file_contract"], "pass", case_dir.name)
                self.assertEqual(by_code["native_resolution"], "not_applicable", case_dir.name)
                self.assertEqual(by_code["oracle_presence"], "not_applicable", case_dir.name)
                self.assertEqual(by_code["prompt"], "pass", case_dir.name)
                self.assertEqual(by_code["author_answer"], "pass", case_dir.name)
                # Verify CLI invocation with direct author_record.html path works too
                if idx == 0:
                    res = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPTS_DIR / "review_case.py"),
                            "--case",
                            str(case_dir / "author_record.html"),
                            "--out",
                            str(out_json),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(res.returncode, 0, res.stderr)

    def test_extra_third_file_in_html_delivery_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "authoring_ZB-TEST-0001-v1"
            make_minimal_html_case(case_dir)
            (case_dir / "extra_notes.txt").write_text("not allowed", encoding="utf-8")
            out_json = Path(tmp) / "review.json"
            res = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "review_case.py"), "--case", str(case_dir), "--out", str(out_json)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            rep = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertGreaterEqual(rep["machine_blockers"], 1)
            contracts = [c for c in rep["checks"] if c["code"] == "delivery_file_contract"]
            self.assertEqual(contracts[0]["status"], "blocked")

    def test_low_resolution_image_not_blocked_and_eval_4x_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outputs"
            case_dir = root / "authoring_ZB-TEST-LOWRES-v1"
            work_dir = root / "_work" / "ZB-TEST-LOWRES-v1"
            work_dir.mkdir(parents=True, exist_ok=True)
            make_minimal_html_case(case_dir, qid="ZB-TEST-LOWRES-v1", img_size=(320, 240), point_xy=(160, 120))
            (work_dir / "eval_4x.json").write_text(
                json.dumps(
                    {
                        "model": "gpt-6.2-sol",
                        "reasoning_effort": "max",
                        "api_mode": "responses",
                        "requested_trials": 4,
                        "counts": {"correct": 3, "incorrect": 1, "error": 0, "completed_valid": 4},
                        "difficulty_qualified": True,
                        "verdict": "qualified",
                    }
                ),
                encoding="utf-8",
            )
            rep = review_case.Reviewer(case_dir, 1080, 1920, "gpt-6.2-sol", "max").run()
            self.assertEqual(rep["machine_blockers"], 0, rep["checks"])
            by_code = {c["code"]: c["status"] for c in rep["checks"]}
            self.assertEqual(by_code["main_image"], "pass")
            self.assertEqual(by_code["native_resolution"], "not_applicable")
            self.assertEqual(by_code["embedded_data_uri"], "pass")
            self.assertEqual(by_code["evaluation_evidence"], "pass")

    def test_corrupted_data_uri_and_winner_label_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "authoring_ZB-TEST-BAD-v1"
            html_path = make_minimal_html_case(
                case_dir,
                qid="ZB-TEST-BAD-v1",
                prompt="请选择其中的真模型并输出编号。",
                embed_data_uri=True,
            )
            # Corrupt embedded base64 to mismatch image dimensions
            other_img = make_image(Path(tmp) / "other.jpg", size=(120, 120))
            bad_b64 = base64.b64encode(other_img.read_bytes()).decode("ascii")
            orig_b64 = base64.b64encode((case_dir / "sample.jpg").read_bytes()).decode("ascii")
            html_path.write_text(html_path.read_text(encoding="utf-8").replace(orig_b64, bad_b64), encoding="utf-8")
            rep = review_case.Reviewer(case_dir, 1080, 1920).run()
            by_code = {c["code"]: c["status"] for c in rep["checks"]}
            self.assertEqual(by_code["embedded_data_uri"], "blocked")
            self.assertEqual(by_code["candidate_winner_label"], "blocked")


class SqliteLedgerTests(unittest.TestCase):
    def _setup_sandbox(self, tmp_dir: Path) -> dict[str, Path]:
        db_path = tmp_dir / "test.sqlite"
        prov_path = tmp_dir / "来源与许可.jsonl"
        img_dir = tmp_dir / "img"
        outputs_dir = tmp_dir / "outputs"
        img_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # id=1: existing outputs conflict; id=2: eligible small image; id=3: claimed; id=4: another eligible
        conn.execute(
            """
            INSERT INTO collection_queue (id, file_url, category, claimed_by, question_types, difficulty, difficulty_tags, authored_status)
            VALUES
              (1, 'https://commons.wikimedia.org/wiki/File:Existing_Case.jpg', '居家场景/工具五金', '', 'counting', 'hard', 'high_density', ''),
              (2, 'https://commons.wikimedia.org/wiki/File:Tiny_Tool.jpg', '居家场景/工具五金', '', 'counting,robust_ocr', 'medium', 'small_target', ''),
              (3, 'https://commons.wikimedia.org/wiki/File:Claimed_Item.jpg', '居家场景/工具五金', 'other_author', 'counting', 'hard', '', 'draft'),
              (4, 'https://commons.wikimedia.org/wiki/File:Market_Stall.jpg', '公共场景/市场摊位', '', 'localization_measurement', 'hard', 'high_similarity', '')
            """
        )
        make_image(img_dir / "居家场景/工具五金/zb-hardware-111.jpg", size=(200, 150))
        make_image(img_dir / "居家场景/工具五金/zb-hardware-222.jpg", size=(320, 240))
        make_image(img_dir / "公共场景/市场摊位/zb-market-444.jpg", size=(400, 300))
        make_image(img_dir / "科学图像/BBBC039/PNG/sample_cell.png", size=(128, 128))
        # Mask dir should be ignored
        make_image(img_dir / "科学图像/BBBC039/掩膜/sample_cell_mask.png", size=(128, 128))

        conn.execute(
            """
            INSERT INTO img_claims (file_path, claimed_by, updated_at, question_types, difficulty, difficulty_tags, authored_status, authored_ref)
            VALUES ('科学图像/BBBC039/PNG/sample_cell.png', '', '2026-11-27T00:00:00Z', 'counting', 'hard', 'high_density', '', '')
            """
        )
        conn.commit()
        conn.close()

        # Two provenance lines for page_id=222 to test "latest record" wins
        prov_lines = [
            {
                "page_id": 111,
                "category": "居家场景/工具五金",
                "file": "img/居家场景/工具五金/zb-hardware-111.jpg",
                "source_page": "https://commons.wikimedia.org/wiki/File:Existing_Case.jpg",
                "license": {"LicenseShortName": "CC BY 4.0", "LicenseUrl": "https://creativecommons.org/licenses/by/4.0"},
            },
            {
                "page_id": 222,
                "category": "居家场景/工具五金",
                "file": "images/居家场景/工具五金/zb-hardware-222.png",
                "source_page": "https://commons.wikimedia.org/wiki/File:Tiny_Tool.jpg",
                "width": 100,
                "height": 100,
                "license": {"LicenseShortName": "CC BY 4.0", "LicenseUrl": "https://creativecommons.org/licenses/by/4.0"},
            },
            {
                "page_id": 222,
                "category": "居家场景/工具五金",
                "file": "img/居家场景/工具五金/zb-hardware-222.jpg",
                "source_page": "https://commons.wikimedia.org/wiki/File:Tiny_Tool.jpg",
                "width": 320,
                "height": 240,
                "license": {"LicenseShortName": "CC BY-SA 4.0", "LicenseUrl": "https://creativecommons.org/licenses/by-sa/4.0"},
            },
            {
                "page_id": 444,
                "category": "公共场景/市场摊位",
                "file": "img/公共场景/市场摊位/zb-market-444.jpg",
                "source_page": "https://commons.wikimedia.org/wiki/File:Market_Stall.jpg",
                "license": {"LicenseShortName": "CC0", "LicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/"},
            },
        ]
        prov_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in prov_lines) + "\n", encoding="utf-8")

        # Put page_id=111 in outputs/ to test deduplication conflict detection
        make_minimal_html_case(outputs_dir / "authoring_ZB-OLD-111-v1", qid="ZB-OLD-111-v1", img_name="zb-hardware-111.jpg")
        return {"db": db_path, "prov": prov_path, "img": img_dir, "outputs": outputs_dir}

    def _run_ledger(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "sqlite_ledger.py"), *args],
            capture_output=True,
            text=True,
        )

    def test_list_claim_next_and_mark_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            paths = self._setup_sandbox(tmp_dir)
            common = ["--db", str(paths["db"]), "--provenance", str(paths["prov"]), "--img-dir", str(paths["img"]), "--outputs-dir", str(paths["outputs"])]

            # 1. List unclaimed, unauthored items (ignores masks, associates latest JSONL record)
            res = self._run_ledger("list", *common)
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            listed = json.loads(res.stdout)
            ids_and_paths = [(it["id"], it["path"]) for it in listed["items"]]
            self.assertNotIn((None, "科学图像/BBBC039/掩膜/sample_cell_mask.png"), ids_and_paths)
            self.assertEqual(listed["matched_count"], 4)  # id 1, 2, 4 + sample_cell.png
            item1 = next(it for it in listed["items"] if it["id"] == 1)
            self.assertTrue(item1["outputs_conflict"])
            self.assertEqual(item1["outputs_conflict_refs"], ["ZB-OLD-111-v1"])
            item2 = next(it for it in listed["items"] if it["id"] == 2)
            self.assertFalse(item2["outputs_conflict"])
            self.assertEqual(item2["local_path"], "img/居家场景/工具五金/zb-hardware-222.jpg")
            self.assertEqual(item2["provenance"]["license"]["LicenseShortName"], "CC BY-SA 4.0")

            # 2. Filter by category + difficulty
            res_flt = self._run_ledger("list", *common, "--category", "居家场景/工具五金", "--difficulty", "medium")
            self.assertEqual(res_flt.returncode, 0)
            flt_data = json.loads(res_flt.stdout)
            self.assertEqual([it["id"] for it in flt_data["items"]], [2])

            # 3. Claim --next in category (MUST skip id=1 due to outputs_conflict and pick id=2!)
            work_dir = tmp_dir / "work_222"
            res_claim = self._run_ledger(
                "claim", *common, "--next", "--category", "居家场景/工具五金",
                "--claimer", "agent_a", "--qid", "ZB-TOOLS-222-v1", "--work-dir", str(work_dir)
            )
            self.assertEqual(res_claim.returncode, 0, res_claim.stdout)
            claimed_data = json.loads(res_claim.stdout)
            self.assertEqual(claimed_data["item"]["id"], 2)
            self.assertEqual(claimed_data["item"]["claimed_by"], "agent_a")
            self.assertEqual(claimed_data["item"]["authored_status"], "draft")
            self.assertTrue((work_dir / "reservation.json").is_file())
            self.assertTrue((work_dir / "source.json").is_file())
            self.assertTrue((work_dir / "manifest.json").is_file())

            # Verify both collection_queue and img_claims were synced
            conn = sqlite3.connect(str(paths["db"]))
            q_row = conn.execute("SELECT claimed_by, authored_status, authored_ref FROM collection_queue WHERE id = 2").fetchone()
            c_row = conn.execute("SELECT claimed_by, authored_status, authored_ref FROM img_claims WHERE file_path = '居家场景/工具五金/zb-hardware-222.jpg'").fetchone()
            conn.close()
            self.assertEqual(tuple(q_row), ("agent_a", "draft", "ZB-TOOLS-222-v1 | outputs/authoring_ZB-TOOLS-222-v1"))
            self.assertEqual(tuple(c_row), ("agent_a", "draft", "ZB-TOOLS-222-v1 | outputs/authoring_ZB-TOOLS-222-v1"))

            # 4. Second claimer trying to claim id=2 MUST fail atomically
            res_conflict = self._run_ledger("claim", *common, "--id", "2", "--claimer", "agent_b")
            self.assertEqual(res_conflict.returncode, 1)
            self.assertEqual(json.loads(res_conflict.stdout)["error"], "already_claimed")

            # 5. Claim local-only image via --path
            res_local = self._run_ledger("claim", *common, "--path", "img/科学图像/BBBC039/PNG/sample_cell.png", "--claimer", "agent_c", "--qid", "ZB-BIO-1-v1")
            self.assertEqual(res_local.returncode, 0, res_local.stdout)
            self.assertEqual(json.loads(res_local.stdout)["item"]["claimed_by"], "agent_c")

            # 6. Mark id=2 as authored
            res_mark = self._run_ledger("mark", *common, "--id", "2", "--authored-status", "authored", "--authored-ref", "ZB-TOOLS-222-v1 | outputs/authoring_ZB-TOOLS-222-v1")
            self.assertEqual(res_mark.returncode, 0, res_mark.stdout)
            self.assertEqual(json.loads(res_mark.stdout)["item"]["authored_status"], "authored")


class EvalTrialsTests(unittest.TestCase):
    @contextmanager
    def _mock_openai_server(self, handler_fn):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                status, resp = handler_fn(self.path, dict(self.headers), body)
                payload = json.dumps(resp, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2)

    def test_grade_answer_numeric_and_leading_zero_rules(self):
        expected = "5,25,29,5|83|1692|3,5,2,2|3,6,3,010610,040509"
        self.assertTrue(eval_trials.grade_answer(expected, expected)["matched"])
        self.assertTrue(eval_trials.grade_answer(expected, "```\n5,25,29,5|83|1692|3,5,2,2|3.0,6,3,010610,040509\n```")["matched"])
        self.assertTrue(eval_trials.grade_answer(expected, "推理过程略\n最终答案：5,25,29,5|83|1692|3,5,2,2|3,6,3,010610,040509")["matched"])
        # Dropping leading zero in 010610 MUST fail
        self.assertFalse(eval_trials.grade_answer(expected, "5,25,29,5|83|1692|3,5,2,2|3,6,3,10610,040509")["matched"])
        # Key-value format (e.g. ZB-FERRULES-0318-v1)
        kv_exp = 'counts=[5,4,3]\nmode0=[30,1,"A1B/B2K"]\nchanged=1'
        kv_act = 'counts=[5, 4.0, 3]\nmode0=[30.0,1,"A1B/B2K"]\nchanged=1.0'
        self.assertTrue(eval_trials.grade_answer(kv_exp, kv_act)["matched"])

    def test_responses_3_correct_1_incorrect_qualifies(self):
        lock = threading.Lock()
        captured = []
        counter = {"n": 0}
        secret_key = "sk-test-secret-never-leak-12345"

        def handler(path, headers, body):
            with lock:
                counter["n"] += 1
                idx = counter["n"]
                captured.append((path, headers.get("Authorization"), body))
            ans = "5,25,29,5|83|1692|3,5,2,2|3,6,3,010610,040509" if idx <= 3 else "5,25,29,5|83|1692|3,5,2,2|3,6,3,999999,040509"
            return 200, {
                "model": body["model"],
                "reasoning": {"effort": body["reasoning"]["effort"]},
                "output_text": ans,
            }

        with tempfile.TemporaryDirectory() as tmp, self._mock_openai_server(handler) as base_url:
            tmp_dir = Path(tmp)
            env_file = tmp_dir / ".env"
            env_file.write_text(f"OPENAI_API_KEY={secret_key}\nOPENAI_BASE_URL={base_url}/\n", encoding="utf-8")
            out_json = tmp_dir / "eval_4x.json"
            res = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "eval_trials.py"),
                    "--case",
                    str(PROJECT_ROOT / "outputs" / "authoring_ZB-TOOLS-143443313-v1"),
                    "--env-file",
                    str(env_file),
                    "--out",
                    str(out_json),
                ],
                env=clean_openai_env(),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn(secret_key, res.stdout)
            self.assertNotIn(secret_key, res.stderr)
            self.assertNotIn(secret_key, out_json.read_text(encoding="utf-8"))

            summary = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(summary["model"], "gpt-6.2-sol")
            self.assertEqual(summary["reasoning_effort"], "max")
            self.assertEqual(summary["counts"], {"correct": 3, "incorrect": 1, "error": 0, "completed_valid": 4})
            self.assertIs(summary["difficulty_qualified"], True)
            self.assertEqual(summary["verdict"], "qualified")

            self.assertEqual(len(captured), 4)
            for path, auth, body in captured:
                self.assertEqual(path, "/v1/responses")
                self.assertEqual(auth, f"Bearer {secret_key}")
                self.assertEqual(body["model"], "gpt-6.2-sol")
                self.assertEqual(body["reasoning"], {"effort": "max"})
                parts = body["input"][0]["content"]
                self.assertEqual(parts[0]["type"], "input_text")
                self.assertIn("红色工具盒", parts[0]["text"])
                self.assertEqual(parts[1]["type"], "input_image")
                self.assertTrue(parts[1]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_chat_fallback_4_of_4_correct_is_too_easy_and_errors_inconclusive(self):
        captured_paths = []
        mode = {"err": False}

        def handler(path, headers, body):
            captured_paths.append(path)
            if path == "/v1/responses":
                return 404, {"error": {"message": "not found"}}
            if mode["err"]:
                return 500, {"error": {"message": "upstream failure"}}
            return 200, {
                "model": body["model"],
                "reasoning_effort": body["reasoning_effort"],
                "choices": [{"message": {"content": "42"}}],
            }

        with tempfile.TemporaryDirectory() as tmp, self._mock_openai_server(handler) as base_url:
            tmp_dir = Path(tmp)
            case_dir = tmp_dir / "authoring_ZB-TEST-4X-v1"
            make_minimal_html_case(case_dir, qid="ZB-TEST-4X-v1", response="42")
            env_file = tmp_dir / ".env"
            env_file.write_text(f"OPENAI_API_KEY=sk-test-chat\nOPENAI_BASE_URL={base_url}/v1\n", encoding="utf-8")

            # 4/4 all correct -> too_easy_all_correct
            out_easy = tmp_dir / "easy.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "eval_trials.py"), "--case", str(case_dir), "--env-file", str(env_file), "--out", str(out_easy)],
                env=clean_openai_env(),
                capture_output=True, text=True, check=True,
            )
            easy = json.loads(out_easy.read_text(encoding="utf-8"))
            self.assertEqual(easy["counts"], {"correct": 4, "incorrect": 0, "error": 0, "completed_valid": 4})
            self.assertIs(easy["difficulty_qualified"], False)
            self.assertEqual(easy["verdict"], "too_easy_all_correct")
            self.assertIn("/v1/responses", captured_paths)
            self.assertIn("/v1/chat/completions", captured_paths)

            # All errors -> inconclusive_errors (errors are NOT counted as incorrect)
            mode["err"] = True
            out_err = tmp_dir / "err.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "eval_trials.py"), "--case", str(case_dir), "--env-file", str(env_file), "--out", str(out_err)],
                env=clean_openai_env(),
                capture_output=True, text=True, check=True,
            )
            err_doc = json.loads(out_err.read_text(encoding="utf-8"))
            self.assertEqual(err_doc["counts"], {"correct": 0, "incorrect": 0, "error": 4, "completed_valid": 0})
            self.assertIsNone(err_doc["difficulty_qualified"])
            self.assertEqual(err_doc["verdict"], "inconclusive_errors")

    def test_dry_run_parses_real_html_cases_without_network(self):
        for name in ("authoring_ZB-0244-v4", "authoring_ZB-TOOLS-143443313-v1"):
            res = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "eval_trials.py"), "--case", str(PROJECT_ROOT / "outputs" / name), "--dry-run"],
                capture_output=True,
                text=True,
                check=True,
            )
            doc = json.loads(res.stdout)
            self.assertTrue(doc["dry_run"])
            self.assertGreater(doc["prompt_characters"], 500)
            self.assertTrue(doc["expected_response"])
            self.assertEqual(doc["preview_payload"]["model"], "gpt-6.2-sol")
            self.assertEqual(doc["preview_payload"]["reasoning"], {"effort": "max"})


if __name__ == "__main__":
    unittest.main()
