#!/usr/bin/env python3
"""Read-only ZeroBench case review. No oracle execution, model API, OCR or installs."""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import re
import struct
import sys

PUBLIC_KEYS = {"prompt", "question", "options", "candidates", "candidate_models", "output_spec", "metric_definitions", "rule_conventions"}
PRIVATE_KEYS = {"answer", "response", "gt", "facts", "gt_structured", "thinking", "cot_image_understanding", "cot_reasoning", "cot1", "cot2", "oracle", "source", "measurement_tolerance", "counterfactual", "answer_fields"}
WINNER_LABEL = re.compile(r"真模型|真实全耦合模型|唯一真实模型|正确模型|\b(?:true\s+model|ground\s+truth\s+model|correct\s+model)\b", re.I)
CANDIDATE_ID = re.compile(r"^[A-Z]{1,3}\d{1,3}$")
METRIC = re.compile(r"\b(?:N_cov92|N_naive_92|N_decoy|high_cov_decoys?)\b|(?:朴素|表面|轮廓)覆盖率|高覆盖诱饵", re.I)
LOOKUP = re.compile(r"\b(?:PDB\s*(?:ID)?\s*[:=]?\s*[0-9][A-Za-z0-9]{3}|COD\s*(?:ID)?\s*[:=]?\s*\d{5,}|CID\s*(?:ID)?\s*[:=]?\s*\d{3,}|CHEMBL\d+|arXiv\s*:\s*\d{4}\.\d+|10\.\d{4,9}/\S+)\b", re.I)
MAIN_TYPES = {"计数聚合链", "游戏／谜题规则求解", "游戏·谜题规则求解", "复杂指令遵循", "小众知识解码", "抗干扰文本读取", "定位度量", "拓扑／图结构追踪", "拓扑·图结构追踪", "空间变换"}
REAL_KINDS = {"real_photo", "real_photograph", "real_observation", "real_photograph_with_reference_panel", "photograph", "microscopy", "video_frame"}
RENDER_KINDS = {"scientific_data_rendering", "structure_data_rendering", "data_rendering"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
PRIVATE_OVERRIDES = {"naive_pass_cps", "naive_pass_checks", "naive_hits_override", "naive_coverage_override"}
QID_RE = re.compile(r"\b(ZB-[A-Za-z0-9-]+-v\d+)\b")
COORD_PAIR_RE = re.compile(r"[(\（]\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[)\）]")
DATA_URI_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.S)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def image_size_from_bytes(data: bytes) -> tuple[tuple[int, int], str]:
    """Inspect PNG/JPEG dimensions from raw bytes in stdlib; fallback to Pillow."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24]), "PNG_header"
    if data[:2] == b"\xff\xd8":
        pos = 2
        n_total = len(data)
        while pos < n_total:
            if data[pos] != 0xFF:
                pos += 1
                continue
            while pos < n_total and data[pos] == 0xFF:
                pos += 1
            if pos >= n_total:
                break
            code = data[pos]
            pos += 1
            if code in (0xD9, 0xDA):
                break
            if code in (0, 1, 0xD8) or 0xD0 <= code <= 0xD7:
                continue
            if pos + 2 > n_total:
                break
            seg_len = struct.unpack(">H", data[pos:pos + 2])[0]
            if seg_len < 2 or pos + seg_len > n_total:
                break
            if code in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if pos + 7 <= n_total:
                    h, w = struct.unpack(">HH", data[pos + 3:pos + 7])
                    return (w, h), "JPEG_header"
                break
            pos += seg_len
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return tuple(im.size), "installed_Pillow"
    except Exception as exc:
        raise ValueError(f"cannot read image dimensions ({type(exc).__name__}); no dependency installed") from exc


def image_size(path):
    """PNG/JPEG headers in stdlib; installed Pillow only for other formats."""
    with path.open("rb") as f:
        header = f.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) == 24:
            return struct.unpack(">II", header[16:24]), "PNG_header"
        if header[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                c = f.read(1)
                if not c:
                    break
                if c != b"\xff":
                    continue
                marker = f.read(1)
                while marker == b"\xff":
                    marker = f.read(1)
                if not marker or marker in (b"\xd9", b"\xda"):
                    break
                code = marker[0]
                if code in (0, 1, 0xD8) or 0xD0 <= code <= 0xD7:
                    continue
                length = f.read(2)
                if len(length) != 2:
                    break
                n = struct.unpack(">H", length)[0]
                if n < 2:
                    break
                if code in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    dimensions = f.read(5)
                    if len(dimensions) == 5:
                        h, w = struct.unpack(">HH", dimensions[1:5])
                        return (w, h), "JPEG_header"
                    break
                f.seek(n - 2, 1)
    try:
        from PIL import Image
        with Image.open(path) as im:
            return tuple(im.size), "installed_Pillow"
    except Exception as exc:
        raise ValueError(f"cannot read image dimensions ({type(exc).__name__}); no dependency installed") from exc


class _AuthorRecordHTMLParser(HTMLParser):
    """Single-pass stdlib HTMLParser extracting metadata, sections, images, and markers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1 = ""
        self.elements_by_id: dict[str, tuple[str, str]] = {}
        self.sections: list[dict] = []
        self.meta_items: list[tuple[str, str]] = []
        self.tables: list[dict] = []
        self.lists: list[dict] = []
        self.imgs: list[dict] = []
        self.dom_markers: list[dict] = []
        self.svg_groups: list[list[dict]] = []
        self.links: list[tuple[str, str]] = []

        self._stack: list[dict] = []
        self._in_title = False
        self._title_buf: list[str] = []
        self._in_h1 = False
        self._h1_buf: list[str] = []
        self._cur_section: dict | None = None
        self._in_h2 = False
        self._h2_buf: list[str] = []
        self._in_meta_item = False
        self._meta_k: list[str] | None = None
        self._meta_v: list[str] | None = None
        self._cur_meta_role: str | None = None
        self._cur_table: dict | None = None
        self._cur_row: list[tuple[str, str]] | None = None
        self._cur_cell: dict | None = None
        self._cur_list: dict | None = None
        self._cur_li: list[str] | None = None
        self._in_svg = False
        self._cur_svg_group: list[dict] | None = None
        self._in_a: tuple[str, list[str]] | None = None
        self._skip_depth = 0  # skip <style>/<script> text

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        el_id = d.get("id")
        cls_raw = d.get("class", "")
        classes = set(cls_raw.split())

        if tag in ("style", "script"):
            self._skip_depth += 1

        if tag == "title":
            self._in_title = True
            self._title_buf = []
        elif tag == "h1":
            self._in_h1 = True
            self._h1_buf = []
        elif tag == "section":
            self._cur_section = {"id": el_id, "h2": "", "buf": []}
        elif tag == "h2":
            self._in_h2 = True
            self._h2_buf = []
        elif tag == "a" and d.get("href"):
            self._in_a = (d["href"], [])

        if "meta-item" in classes:
            self._in_meta_item = True
            self._meta_k = []
            self._meta_v = []
        elif self._in_meta_item:
            if "k" in classes:
                self._cur_meta_role = "k"
            elif "v" in classes:
                self._cur_meta_role = "v"

        if tag == "table":
            sec_h2 = self._cur_section["h2"] if self._cur_section else ""
            sec_id = self._cur_section["id"] if self._cur_section else None
            self._cur_table = {"section_h2": sec_h2, "section_id": sec_id, "rows": []}
        elif tag == "tr" and self._cur_table is not None:
            self._cur_row = []
        elif tag in ("th", "td") and self._cur_row is not None:
            self._cur_cell = {"tag": tag, "buf": [], "ignore_depth": 0}
        elif self._cur_cell is not None and tag in ("textarea", "button"):
            self._cur_cell["ignore_depth"] += 1

        if tag in ("ol", "ul"):
            sec_h2 = self._cur_section["h2"] if self._cur_section else ""
            sec_id = self._cur_section["id"] if self._cur_section else None
            self._cur_list = {"section_h2": sec_h2, "section_id": sec_id, "items": []}
        elif tag == "li" and self._cur_list is not None:
            self._cur_li = []

        if tag == "img":
            self.imgs.append({
                "id": el_id,
                "src": d.get("src", ""),
                "width": d.get("width"),
                "height": d.get("height"),
                "alt": d.get("alt", ""),
            })

        if classes & {"point", "marker"}:
            self.dom_markers.append({
                "tag": tag,
                "class": cls_raw,
                "style": d.get("style", ""),
                "title": d.get("title", ""),
                "aria_label": d.get("aria-label", ""),
                "data_x": d.get("data-x"),
                "data_y": d.get("data-y"),
                "text_buf": [],
            })

        if tag == "svg":
            self._in_svg = True
        elif self._in_svg and tag == "g":
            self._cur_svg_group = []
        elif self._in_svg and tag == "circle":
            circle = {
                "cx": d.get("cx"),
                "cy": d.get("cy"),
                "r": d.get("r"),
                "fill": d.get("fill", ""),
            }
            if self._cur_svg_group is not None:
                self._cur_svg_group.append(circle)
            else:
                self.svg_groups.append([circle])

        self._stack.append({
            "tag": tag,
            "id": el_id,
            "classes": classes,
            "buf": [] if el_id else None,
            "is_marker": bool(classes & {"point", "marker"}),
        })

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_buf.append(data)
        if self._in_h1:
            self._h1_buf.append(data)
        if self._in_h2:
            self._h2_buf.append(data)
        elif self._cur_section is not None:
            self._cur_section["buf"].append(data)
        if self._in_a is not None:
            self._in_a[1].append(data)
        if self._in_meta_item:
            if self._cur_meta_role == "k" and self._meta_k is not None:
                self._meta_k.append(data)
            elif self._cur_meta_role == "v" and self._meta_v is not None:
                self._meta_v.append(data)
        if self._cur_cell is not None and self._cur_cell["ignore_depth"] == 0:
            self._cur_cell["buf"].append(data)
        if self._cur_li is not None:
            self._cur_li.append(data)
        for frame in self._stack:
            if frame["buf"] is not None:
                frame["buf"].append(data)
        if self._stack and self._stack[-1]["is_marker"] and self.dom_markers:
            self.dom_markers[-1]["text_buf"].append(data)

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skip_depth > 0:
            self._skip_depth -= 1

        if tag == "title" and self._in_title:
            self.title = "".join(self._title_buf).strip()
            self._in_title = False
        elif tag == "h1" and self._in_h1:
            self.h1 = " ".join("".join(self._h1_buf).split())
            self._in_h1 = False
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
            h2_text = " ".join("".join(self._h2_buf).split())
            if self._cur_section is not None and not self._cur_section["h2"]:
                self._cur_section["h2"] = h2_text
        elif tag == "a" and self._in_a is not None:
            href, buf = self._in_a
            self.links.append((href, " ".join("".join(buf).split())))
            self._in_a = None

        if self._in_meta_item and tag == "span":
            self._cur_meta_role = None

        if self._cur_cell is not None:
            if tag in ("textarea", "button") and self._cur_cell["ignore_depth"] > 0:
                self._cur_cell["ignore_depth"] -= 1
            elif tag == self._cur_cell["tag"]:
                cell_text = " ".join("".join(self._cur_cell["buf"]).split())
                if self._cur_row is not None:
                    self._cur_row.append((tag, cell_text))
                self._cur_cell = None
        elif tag == "tr" and self._cur_row is not None:
            if self._cur_table is not None and self._cur_row:
                self._cur_table["rows"].append(self._cur_row)
            self._cur_row = None
        elif tag == "table" and self._cur_table is not None:
            self.tables.append(self._cur_table)
            self._cur_table = None

        if tag == "li" and self._cur_li is not None:
            txt = " ".join("".join(self._cur_li).split())
            if self._cur_list is not None and txt:
                self._cur_list["items"].append(txt)
            self._cur_li = None
        elif tag in ("ol", "ul") and self._cur_list is not None:
            self.lists.append(self._cur_list)
            self._cur_list = None

        if self._in_svg and tag == "g" and self._cur_svg_group is not None:
            if self._cur_svg_group:
                self.svg_groups.append(self._cur_svg_group)
            self._cur_svg_group = None
        elif tag == "svg":
            self._in_svg = False

        if tag == "section" and self._cur_section is not None:
            self._cur_section["text"] = "".join(self._cur_section.pop("buf")).strip()
            self.sections.append(self._cur_section)
            self._cur_section = None

        for idx in range(len(self._stack) - 1, -1, -1):
            frame = self._stack[idx]
            if frame["tag"] == tag:
                self._stack.pop(idx)
                if "meta-item" in frame["classes"] and self._in_meta_item:
                    k_txt = " ".join("".join(self._meta_k or []).split())
                    v_txt = " ".join("".join(self._meta_v or []).split())
                    if k_txt:
                        self.meta_items.append((k_txt, v_txt))
                    self._in_meta_item = False
                    self._meta_k = None
                    self._meta_v = None
                if frame["id"] and frame["buf"] is not None:
                    raw_text = "".join(frame["buf"]).strip()
                    # Avoid overwriting inner element text with outer section wrapper if same id wasn't used
                    if frame["id"] not in self.elements_by_id or frame["tag"] != "section":
                        self.elements_by_id[frame["id"]] = (frame["tag"], raw_text)
                break


def _parse_kv_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in ("：", ":"):
            if sep in line:
                k, v = line.split(sep, 1)
                k = k.strip()
                v = v.strip()
                if k and k not in result:
                    result[k] = v
                break
    return result


def _parse_css_pct(style: str) -> tuple[float, float] | None:
    mx = re.search(r"(?:--x|left)\s*:\s*(-?\d+(?:\.\d+)?)%", style)
    my = re.search(r"(?:--y|top)\s*:\s*(-?\d+(?:\.\d+)?)%", style)
    if mx and my:
        return float(mx.group(1)), float(my.group(1))
    return None


def _parse_pixel_points_from_text(text: str) -> list[dict]:
    points: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = COORD_PAIR_RE.search(line)
        if not m:
            continue
        x, y = float(m.group(1)), float(m.group(2))
        label = line[m.end():].strip(" |：:.\t") or line[:m.start()].strip(" |：:.\t") or f"point_{len(points) + 1}"
        points.append({"xy": [x, y], "label": label, "source": "text"})
    return points


def parse_author_record_html(html_path: Path) -> dict:
    """Parse an author_record.html deliverable using stdlib html.parser across known templates."""
    content = html_path.read_text(encoding="utf-8")
    parser = _AuthorRecordHTMLParser()
    parser.feed(content)
    parser.close()

    by_id = parser.elements_by_id

    def pick_field(id_candidates: tuple[str, ...], heading_keywords: tuple[str, ...]) -> str:
        # Prefer explicit non-section content nodes first
        for cid in id_candidates:
            if cid in by_id and by_id[cid][0] != "section" and by_id[cid][1].strip():
                return by_id[cid][1].strip()
        for cid in id_candidates:
            if cid in by_id and by_id[cid][1].strip():
                return by_id[cid][1].strip()
        for sec in parser.sections:
            h2 = sec["h2"].lower()
            if any(kw in h2 for kw in heading_keywords):
                text = sec["text"].strip()
                if text.startswith("复制"):
                    text = text[2:].strip()
                if text:
                    return text
        return ""

    # Basic metadata extraction
    basic_meta: dict[str, str] = {}
    for k, v in parser.meta_items:
        basic_meta[k] = v
    for tbl in parser.tables:
        h2 = tbl["section_h2"]
        if tbl["section_id"] in ("basic", "sec-basic") or "基本信息" in h2 or (not h2 and tbl["rows"] and len(tbl["rows"][0]) >= 2 and tbl["rows"][0][0][0] == "th"):
            for row in tbl["rows"]:
                if len(row) >= 2 and row[0][0] == "th":
                    k = row[0][1].strip()
                    v = row[1][1].strip()
                    if k and k not in basic_meta:
                        basic_meta[k] = v
    for basic_id in ("copy-basic", "basic"):
        if basic_id in by_id and by_id[basic_id][0] != "section":
            for k, v in _parse_kv_lines(by_id[basic_id][1]).items():
                basic_meta.setdefault(k, v)

    # Expand combined basic fields (e.g. 题号与题名 / 题型与难度)
    if "题号与题名" in basic_meta and "｜" in basic_meta["题号与题名"]:
        parts = [p.strip() for p in basic_meta["题号与题名"].split("｜", 1)]
        basic_meta.setdefault("题号", parts[0])
        if len(parts) > 1:
            basic_meta.setdefault("题名", parts[1])
    if "题型与难度" in basic_meta and "｜" in basic_meta["题型与难度"]:
        parts = [p.strip() for p in basic_meta["题型与难度"].split("｜", 1)]
        basic_meta.setdefault("题型", parts[0])
        if len(parts) > 1:
            basic_meta.setdefault("难度", parts[1])

    qid = (
        (by_id.get("question_id", ("", ""))[1].strip())
        or (by_id.get("number", ("", ""))[1].strip())
        or basic_meta.get("题号", "").strip()
    )
    if not qid:
        for text_src in (parser.h1, parser.title, html_path.parent.name):
            m = QID_RE.search(text_src)
            if m:
                qid = m.group(1)
                break
    version = None
    if qid:
        vm = re.search(r"-(v\d+)$", qid)
        if vm:
            version = vm.group(1)

    title = (
        (by_id.get("title", ("", ""))[1].strip())
        or (by_id.get("name", ("", ""))[1].strip())
        or basic_meta.get("题名", "").strip()
        or parser.h1
        or parser.title
    )
    question_type = (
        basic_meta.get("一级题型 / 候选题型")
        or basic_meta.get("题型")
        or (by_id.get("question_types", ("", ""))[1].strip())
        or (by_id.get("type", ("", ""))[1].strip())
    )
    difficulty = (
        basic_meta.get("难度")
        or (by_id.get("difficulty", ("", ""))[1].strip())
        or (by_id.get("level", ("", ""))[1].strip())
    )
    source_url = (
        (by_id.get("source", ("", ""))[1].strip())
        or basic_meta.get("来源")
        or basic_meta.get("来源页与资产编号")
        or basic_meta.get("来源与作者")
        or ""
    )
    if not source_url.startswith(("http://", "https://")):
        for href, _ in parser.links:
            if "commons.wikimedia.org" in href or "metmuseum.org" in href or "wellcome" in href:
                source_url = href
                break
    license_text = (
        (by_id.get("license", ("", ""))[1].strip())
        or basic_meta.get("许可")
        or basic_meta.get("许可协议")
        or basic_meta.get("许可原文")
        or ""
    )
    author_name = (
        (by_id.get("artist", ("", ""))[1].strip())
        or (by_id.get("photographer", ("", ""))[1].strip())
        or basic_meta.get("作者")
        or basic_meta.get("作者署名")
        or ""
    )

    prompt = pick_field(("prompt-text", "copy-prompt", "prompt", "field0"), ("prompt", "题目"))
    thinking = pick_field(("thinking-text", "copy-thinking", "thinking", "field1"), ("thinking", "出题思路"))
    understanding = pick_field(("understanding-text", "copy-cot-img", "cot_image_understanding", "understanding", "field2"), ("cot_image_understanding", "图像识别"))
    reasoning = pick_field(("reasoning-text", "copy-cot-reason", "cot_reasoning", "reasoning", "field3"), ("cot_reasoning", "题目推理"))
    response = pick_field(("response-text", "copy-response", "response", "answer", "field4"), ("response", "标准答案"))
    qa_summary = pick_field(("qa-text", "copy-qa", "qa_summary", "qa"), ("质检", "qa"))

    # Point extraction across all template conventions
    pixel_points: list[dict] = []
    for pid in ("points-text", "platform_points", "copy-points"):
        if pid in by_id and by_id[pid][1].strip():
            pts = _parse_pixel_points_from_text(by_id[pid][1])
            if pts:
                pixel_points = pts
                break

    if not pixel_points:
        # Look for table in comparison section
        for tbl in parser.tables:
            h2 = tbl["section_h2"]
            if tbl["section_id"] in ("comparison", "sec-images") or "打点" in h2:
                pts = []
                for row in tbl["rows"]:
                    row_text = " ".join(c[1] for c in row)
                    m = COORD_PAIR_RE.search(row_text)
                    if m:
                        x, y = float(m.group(1)), float(m.group(2))
                        label = row[-1][1] if len(row) >= 2 else f"point_{len(pts) + 1}"
                        pts.append({"xy": [x, y], "label": label, "source": "table"})
                if pts:
                    pixel_points = pts
                    break

    if not pixel_points:
        # Look for <ol> list items in comparison section (e.g. ZB-0230-v1)
        for lst in parser.lists:
            if lst["section_id"] in ("comparison", "sec-images") or "打点" in lst["section_h2"] or not lst["section_h2"]:
                pts = _parse_pixel_points_from_text("\n".join(lst["items"]))
                if pts:
                    pixel_points = pts
                    break

    dom_pct_points: list[dict] = []
    dom_attr_points: list[dict] = []
    for mk in parser.dom_markers:
        pct = _parse_css_pct(mk["style"])
        label = mk["title"] or mk["aria_label"] or "".join(mk["text_buf"]).strip() or f"point_{len(dom_pct_points) + 1}"
        if pct is not None:
            dom_pct_points.append({"pct_xy": list(pct), "label": label, "source": "css_pct"})
        if mk["data_x"] is not None and mk["data_y"] is not None:
            try:
                dom_attr_points.append({"xy": [float(mk["data_x"]), float(mk["data_y"])], "label": label, "source": "data_attr"})
            except ValueError:
                pass

    svg_points: list[dict] = []
    for grp in parser.svg_groups:
        first_circle = grp[0]
        if first_circle.get("cx") is not None and first_circle.get("cy") is not None:
            try:
                svg_points.append({
                    "xy": [float(first_circle["cx"]), float(first_circle["cy"])],
                    "label": f"svg_point_{len(svg_points) + 1}",
                    "source": "svg_circle",
                })
            except ValueError:
                pass

    if not pixel_points and dom_attr_points:
        pixel_points = dom_attr_points
    elif not pixel_points and svg_points:
        pixel_points = svg_points

    return {
        "id": qid or html_path.parent.name.removeprefix("authoring_"),
        "version": version,
        "title": title,
        "question_type": question_type,
        "difficulty": difficulty,
        "source_url": source_url,
        "license": license_text,
        "author": author_name,
        "basic_meta": basic_meta,
        "prompt": prompt,
        "thinking": thinking,
        "cot_image_understanding": understanding,
        "cot_reasoning": reasoning,
        "response": response,
        "qa_summary": qa_summary,
        "images": parser.imgs,
        "pixel_points": pixel_points,
        "dom_pct_points": dom_pct_points,
        "svg_points": svg_points,
    }


def walk_strings(obj, prefix="public"):
    if isinstance(obj, str):
        yield prefix, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk_strings(value, f"{prefix}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk_strings(value, f"{prefix}[{i}]")


def static_render_labels(path):
    """Limited literal-to-text flow, not execution or proof about a saved image."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    results = []

    def value(node, env):
        if isinstance(node, ast.Name):
            return env.get(node.id)
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError):
            return None

    def bind(node, val, env):
        if isinstance(node, ast.Name):
            env[node.id] = val
        elif isinstance(node, (ast.Tuple, ast.List)) and isinstance(val, (tuple, list)) and len(node.elts) == len(val):
            for part, item in zip(node.elts, val):
                bind(part, item, env)

    def statements(body, env):
        env = dict(env)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                statements(statement.body, env)
            elif isinstance(statement, ast.Assign):
                val = value(statement.value, env)
                for target in statement.targets:
                    bind(target, val, env)
            elif isinstance(statement, ast.For):
                iterator = statement.iter
                enumerated = isinstance(iterator, ast.Call) and isinstance(iterator.func, ast.Name) and iterator.func.id == "enumerate" and iterator.args
                rows = value(iterator.args[0] if enumerated else iterator, env)
                if isinstance(rows, (list, tuple)) and len(rows) <= 100:
                    for i, row in enumerate(rows):
                        child = dict(env)
                        bind(statement.target, (i, row) if enumerated else row, child)
                        statements(statement.body, child)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                if isinstance(call.func, ast.Attribute) and call.func.attr in {"text", "annotate"}:
                    # Pillow text(xy,text), Matplotlib text(x,y,text), annotate(text,xy).
                    texts = [value(node, env) for node in call.args[:3]]
                    texts += [value(k.value, env) for k in call.keywords if k.arg in {"text", "s"}]
                    ids = [v for v in env.values() if isinstance(v, str) and CANDIDATE_ID.fullmatch(v)]
                    for text in texts:
                        if isinstance(text, str) and WINNER_LABEL.search(text) and ids:
                            results.append({"file": str(path), "line": call.lineno, "candidate_ids": sorted(set(ids)), "rendered_text_expression_value": text,
                                            "evidence_limit": "literal candidate-loop value reaches text(); current PNG pixels and execution path still require inspection"})
    statements(tree.body, {})
    return list({(r["line"], r["rendered_text_expression_value"]): r for r in results}.values())


def private_score_accesses(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    result = []
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            key = node.args[0]
        elif isinstance(node, ast.Subscript):
            key = node.slice
        if isinstance(key, ast.Constant) and key.value in PRIVATE_OVERRIDES:
            result.append({"file": str(path), "line": node.lineno, "accessed_key": key.value})
    return result


class Reviewer:
    def __init__(self, case_path, min_short, min_long, expected_model=None, expected_effort=None):
        self.input_path = case_path.resolve()
        self.directory = self.input_path if self.input_path.is_dir() else self.input_path.parent
        self.checks = []
        self.min_short, self.min_long = min_short, min_long
        self.expected_model, self.expected_effort = expected_model, expected_effort
        self.metadata = {}
        self.html_mode = (
            (self.input_path.is_file() and self.input_path.suffix.lower() in {".html", ".htm"})
            or (self.input_path.is_dir() and (self.directory / "author_record.html").is_file())
        )
        self._html_record = None
        self._html_image_path = None

    def add(self, code, status, message, evidence=None):
        self.checks.append({"code": code, "status": status, "message": message, "evidence": evidence or {}})

    def read(self, path, required=False):
        if not path.is_file():
            if required:
                self.add("missing_file", "blocked", "Required input does not exist", {"path": str(path)})
            return {}
        try:
            data = load(path)
            if not isinstance(data, dict):
                raise ValueError("expected JSON object")
            return data
        except (OSError, ValueError) as exc:
            self.add("invalid_json", "blocked", "Cannot interpret case JSON", {"path": str(path), "error_type": type(exc).__name__})
            return {}

    def _html_inputs(self):
        html_path = self.input_path if self.input_path.is_file() else self.directory / "author_record.html"
        entries = sorted(self.directory.iterdir(), key=lambda p: p.name)
        dirs = [p.name for p in entries if not p.is_file()]
        files = [p for p in entries if p.is_file()]
        html_files = [p for p in files if p.name == "author_record.html"]
        image_files = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
        other_files = [p.name for p in files if p.name != "author_record.html" and p.suffix.lower() not in IMAGE_EXTS]

        contract_ok = (not dirs) and len(files) == 2 and len(html_files) == 1 and len(image_files) == 1 and (not other_files)
        if contract_ok:
            self._html_image_path = image_files[0]
            self.add(
                "delivery_file_contract",
                "pass",
                "交付目录严格仅包含 author_record.html 与 1 张图片文件",
                {"files": [p.name for p in files]},
            )
        else:
            if image_files:
                self._html_image_path = image_files[0]
            self.add(
                "delivery_file_contract",
                "blocked",
                "HTML 交付目录必须严格只有 2 个文件：author_record.html 和 1 张图片文件",
                {
                    "file_count": len(files),
                    "files": [p.name for p in files],
                    "subdirectories": dirs,
                    "extra_files": other_files,
                    "image_files": [p.name for p in image_files],
                },
            )

        parsed = {}
        if html_path.is_file():
            try:
                parsed = parse_author_record_html(html_path)
            except Exception as exc:
                self.add("invalid_html", "blocked", "Cannot parse author_record.html", {"path": str(html_path), "error": f"{type(exc).__name__}: {exc}"})
        else:
            self.add("missing_file", "blocked", "author_record.html does not exist", {"path": str(html_path)})

        self._html_record = parsed
        author = {
            "id": parsed.get("id"),
            "version": parsed.get("version"),
            "title": parsed.get("title"),
            "question_type": parsed.get("question_type"),
            "difficulty": parsed.get("difficulty"),
            "prompt": parsed.get("prompt", ""),
            "thinking": parsed.get("thinking", ""),
            "cot_image_understanding": parsed.get("cot_image_understanding", ""),
            "cot_reasoning": parsed.get("cot_reasoning", ""),
            "response": parsed.get("response", ""),
            "qa_summary": parsed.get("qa_summary", ""),
            "image_path": self._html_image_path.name if self._html_image_path else None,
            "source": {
                "url": parsed.get("source_url", ""),
                "license": parsed.get("license", ""),
                "author": parsed.get("author", ""),
                "kind": "real_photo",
            },
            "platform_points": parsed.get("pixel_points") or [],
        }
        public = {"prompt": parsed.get("prompt", "")}
        self.metadata["input_schema"] = {
            "mode": "html_delivery",
            "primary": str(html_path),
            "image": str(self._html_image_path) if self._html_image_path else None,
            "public_exposure_basis": "HTML prompt section extracted via stdlib html.parser",
            "public_keys_checked": ["prompt"],
        }
        self.add("public_scope", "pass", "Public prompt and author sections were separated from author_record.html", self.metadata["input_schema"])
        return author, public

    def inputs(self):
        if self.html_mode:
            return self._html_inputs()
        primary_path = self.input_path if self.input_path.is_file() else self.directory / "author.json"
        if not primary_path.exists():
            primary_path = self.directory / "question.json"
        data = self.read(primary_path, True)
        author = self.read(self.directory / "author.json") or data
        question = self.read(self.directory / "question.json")
        public_path = next((self.directory / name for name in ("public.json", "public_question.json") if (self.directory / name).is_file()), None)
        declared = self.read(public_path) if public_path else data.get("public")
        if isinstance(declared, dict):
            public = declared
            exposure = "explicit public JSON/block"
        else:
            source = question or data
            public = {k: v for k, v in source.items() if k in PUBLIC_KEYS}
            # A declared public field list takes precedence over the fallback.
            names = source.get("public_fields")
            if isinstance(names, list):
                public = {k: source[k] for k in names if isinstance(k, str) and k in source}
                exposure = "explicit public_fields allowlist"
            else:
                exposure = "fallback allowlist; prompt/options/candidates only, title and answer fields are not assumed public"
        self.metadata["input_schema"] = {"mode": "json_case", "primary": str(primary_path), "author": str(self.directory / "author.json") if (self.directory / "author.json").is_file() else str(primary_path),
                                          "public_exposure_basis": exposure, "public_keys_checked": sorted(public),
                                          "not_scanned_for_public_leaks": ["private facts.json", "author answers/CoT", "source provenance", "code comments", "unrendered Python literals"]}
        self.add("public_scope", "pass", "Public and author material were separated before semantic checks", self.metadata["input_schema"])
        return author, public

    def public_review(self, public):
        text = "\n".join(s for _, s in walk_strings(public))
        prompt = public.get("prompt", public.get("question", ""))
        if not isinstance(prompt, str) or not prompt.strip():
            self.add("prompt", "blocked", "No public prompt text found")
            prompt = ""
        else:
            self.add("prompt", "pass", "Public prompt is present", {"characters": len(prompt)})
        for key in ("answer", "response", "gt", "gt_structured", "cot_image_understanding", "cot_reasoning"):
            if key in public:
                self.add("explicit_private_field_public", "blocked", "An explicitly public block includes a solution/author field", {"key": key})
        label_hits = []
        for key in ("options", "candidates", "candidate_models"):
            candidates = public.get(key, [])
            if isinstance(candidates, dict):
                candidates = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "label": v} for k, v in candidates.items()]
            if not isinstance(candidates, list):
                continue
            for i, item in enumerate(candidates):
                item = item if isinstance(item, dict) else {"label": item}
                for field in ("label", "name", "title", "summary", "description"):
                    value = item.get(field)
                    if isinstance(value, str) and WINNER_LABEL.search(value):
                        label_hits.append({"field": f"public.{key}[{i}].{field}", "candidate": item.get("id"), "value": value})
        if prompt and WINNER_LABEL.search(prompt):
            for m in WINNER_LABEL.finditer(prompt):
                label_hits.append({"field": "public.prompt", "value": m.group(0)})
        if label_hits:
            self.add("candidate_winner_label", "blocked", "Explicitly public prompt or candidate label identifies a true/correct model", label_hits)
        else:
            self.add("candidate_winner_label", "pass", "No explicit winner label found in the checked public fields/prompt; image text remains unverified")
        for script in ("render.py", "build.py"):
            hits = static_render_labels(self.directory / script)
            if hits:
                self.add("rendered_candidate_label", "needs_review", "Candidate winner words flow into a drawing text call; inspect the saved main image before declaring pixel-level leakage", hits)
        lookup_hits = [{"field": k, "value": m.group(0)} for k, s in walk_strings(public) for m in LOOKUP.finditer(s)]
        if lookup_hits:
            self.add("database_lookup_route", "needs_review", "Public identifier may enable direct lookup; establish whether it actually replaces required visual evidence", lookup_hits)
        if METRIC.search(text):
            definitions = public.get("metric_definitions")
            accesses = private_score_accesses(self.directory / "oracle.py") if not self.html_mode else []
            self.add("coverage_metric_contract", "needs_review", "Coverage/decoy count is requested. Verify the public checklist, denominator, weights, threshold, winner inclusion and every exemption; a variable name alone is not a violation.",
                     {"structured_public_definitions_present": bool(definitions), "private_override_accesses": accesses,
                      "prompt_mentions_denominator": bool(re.search(r"分母|denominator|\d+\s*/\s*\d+", prompt, re.I)),
                      "prompt_mentions_winner_scope": bool(re.search(r"非赢家|不含.*(?:真模型|赢家)|含.*(?:真模型|赢家)|exclude.*winner|include.*winner", prompt, re.I)),
                      "limit": "Images may carry definitions; absence from parsed JSON is not proof of absence from the whole question."})
        if re.search(r"最优|最大|最小|赢家|胜出|代表|optimal|winner|argmin|argmax", prompt, re.I):
            ties = bool(re.search(r"并列|平局|字典序|相等时|tie|lexicograph", prompt, re.I))
            empty = bool(re.search(r"空集|无可行|不存在.*(?:解|方案|路径)|无解|无.*(?:候选|路径).*时|empty|infeasible|no feasible", prompt, re.I))
            conventions = public.get("rule_conventions", {})
            self.add("tie_and_empty_contract", "needs_review", "Check tie, empty feasible set/path and no-winner branches; wording presence does not prove every branch is defined", {"tie_wording_present": ties, "empty_wording_present": empty, "public_rule_conventions": conventions})
        self.add("language_false_positive_policy", "pass", "Ordinary 忽略/真实/唯一/混淆 wording, source IDs in private provenance, and author facts are not automatically rejected")

    def _check_html_images(self, main_path: Path | None, dimensions: tuple[int, int] | None):
        if self._html_record is None:
            return
        imgs = self._html_record.get("images") or []
        if not imgs:
            self.add("html_image_elements", "blocked", "author_record.html does not contain any <img> element")
            return
        disk_bytes = main_path.read_bytes() if (main_path and main_path.is_file()) else None
        data_uri_checked = 0
        for idx, im in enumerate(imgs):
            src = (im.get("src") or "").strip()
            w_attr, h_attr = im.get("width"), im.get("height")
            if dimensions and w_attr and h_attr:
                try:
                    if (int(w_attr), int(h_attr)) != tuple(dimensions):
                        self.add("html_image_attributes", "blocked", "<img> width/height attributes do not match image file dimensions", {"index": idx, "attr": [w_attr, h_attr], "file_dimensions": list(dimensions)})
                        return
                except ValueError:
                    self.add("html_image_attributes", "blocked", "Non-integer <img> width/height attributes", {"index": idx, "attr": [w_attr, h_attr]})
                    return

            dm = DATA_URI_RE.match(src)
            if dm:
                data_uri_checked += 1
                try:
                    raw = base64.b64decode(dm.group(2).strip(), validate=True)
                except Exception as exc:
                    self.add("embedded_data_uri", "blocked", "Invalid base64 data:image URI in author_record.html", {"index": idx, "error": str(exc)})
                    return
                if disk_bytes is not None and raw == disk_bytes:
                    continue
                try:
                    emb_size, _ = image_size_from_bytes(raw)
                except ValueError as exc:
                    self.add("embedded_data_uri", "blocked", "Embedded data:image cannot be decoded as an image", {"index": idx, "error": str(exc)})
                    return
                if dimensions and tuple(emb_size) != tuple(dimensions):
                    self.add("embedded_data_uri", "blocked", "Embedded data:image dimensions differ from directory image file", {"index": idx, "embedded_dimensions": list(emb_size), "file_dimensions": list(dimensions)})
                    return
            elif src:
                if main_path is None or Path(src).name != main_path.name or src.startswith(("http://", "https://", "/", "..")):
                    self.add("html_image_src", "blocked", "HTML <img> src must reference the sibling image file or a valid embedded data URI", {"index": idx, "src": src[:120], "expected_file": main_path.name if main_path else None})
                    return
        if data_uri_checked:
            self.add("embedded_data_uri", "pass", "Embedded data:image base64 matches sibling image file bytes/dimensions", {"count": data_uri_checked})
        else:
            self.add("embedded_data_uri", "not_applicable", "author_record.html references the sibling image file directly", {"img_count": len(imgs)})

    def image_review(self, author):
        if self.html_mode:
            main = self._html_image_path if self._html_image_path is not None else (self.directory / "main.png")
        else:
            main_ref = author.get("image_path")
            main = self.directory / main_ref if isinstance(main_ref, str) else next((p for p in self.directory.glob("main.*") if p.suffix.lower() in IMAGE_EXTS), self.directory / "main.png")
        dimensions = None
        if not main.is_file():
            self.add("main_image", "blocked", "Main image reference is missing", {"path": str(main)})
        else:
            try:
                dimensions, method = image_size(main)
                self.add("main_image", "pass", "Main image is readable; per project policy image pixel/file size is recorded without size gating", {"path": str(main), "dimensions": dimensions, "method": method})
            except ValueError as exc:
                self.add("main_image", "blocked" if self.html_mode else "needs_review", str(exc), {"path": str(main)})

        if self.html_mode:
            self._check_html_images(main if main.is_file() else None, dimensions)

        source = author.get("source", {}) if self.html_mode else (self.read(self.directory / "source.json") or author.get("source", {}))
        source = source if isinstance(source, dict) else {}
        provenance = author.get("image_provenance", {})
        provenance = provenance if isinstance(provenance, dict) else {}
        kind = source.get("kind", provenance.get("nature", "unknown"))

        native = []
        if not self.html_mode:
            native_files = set()
            for pattern in ("source_raw.*", "source_original.*", "raw.*", "original.*"):
                native_files.update(p for p in self.directory.glob(pattern) if p.suffix.lower() in IMAGE_EXTS)
            for container in (author, source, provenance):
                for key in ("native_image", "native_path", "original_image", "original_path", "raw_image", "raw_path"):
                    if isinstance(container.get(key), str):
                        native_files.add(self.directory / container[key])
            for path in sorted(native_files):
                if not path.is_file():
                    continue
                try:
                    size, method = image_size(path)
                    native.append({"path": str(path), "dimensions": size, "method": method})
                except ValueError:
                    pass

        self.metadata["image"] = {
            "main_path": str(main),
            "main_dimensions": dimensions,
            "declared_source_kind": kind,
            "native_rasters": native,
            "declared_native_dimensions": source.get("native_dimensions", provenance.get("native_dimensions")),
            "size_check_policy": "disabled (按项目规则不检查图片尺寸)",
            "compat_cli_profile": {"min_short_px": self.min_short, "min_long_px": self.min_long, "enforced": False},
        }
        self.add("native_resolution", "not_applicable", "按项目规则不检查图片尺寸", {"kind": kind, "main_dimensions": dimensions, "native_rasters": native})
        self.add("source_license_and_fidelity", "needs_review", "Verify source bytes, license/attribution and whether each panel is observation, data rendering or simulated measurement; metadata declarations alone are not proof", {"source": source, "image_provenance": provenance})
        if kind in RENDER_KINDS and re.search(r"实拍|实测|真实观测", str(author.get("prompt", ""))):
            self.add("mixed_observation_claim", "needs_review", "Prompt claims measured/observed evidence within a rendering; check each panel against actual recorded data, especially simulated assays")
        return dimensions

    def _html_point_review(self, dimensions):
        rec = self._html_record or {}
        pixel_pts = rec.get("pixel_points") or []
        pct_pts = rec.get("dom_pct_points") or []
        points = pixel_pts if pixel_pts else []
        if not points and pct_pts and dimensions:
            points = [
                {"xy": [p["pct_xy"][0] / 100.0 * dimensions[0], p["pct_xy"][1] / 100.0 * dimensions[1]], "label": p["label"], "source": "css_pct"}
                for p in pct_pts
            ]

        count = len(points) if points else len(pct_pts)
        if not 1 <= count <= 3:
            self.add("platform_point_count", "blocked", "Platform points must contain 1–3 key positions", {"pixel_count": len(pixel_pts), "dom_marker_count": len(pct_pts)})
            return

        self.add("platform_point_count", "pass", "Platform key-point count is 1–3", {"count": count})
        seen_xy = set()
        for i, pt in enumerate(points):
            xy = pt.get("xy", [])
            if len(xy) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xy):
                self.add("platform_point_coordinate", "blocked", "Coordinates must be two finite numeric values", {"index": i})
            elif dimensions and not (0 <= xy[0] < dimensions[0] and 0 <= xy[1] < dimensions[1]):
                self.add("platform_point_coordinate", "blocked", "Point falls outside the final image bounds", {"index": i, "xy": xy, "dimensions": dimensions})
            else:
                key = (round(float(xy[0]), 4), round(float(xy[1]), 4))
                if key in seen_xy:
                    self.add("platform_point_coordinate", "blocked", "Duplicate platform point coordinates", {"index": i, "xy": xy})
                else:
                    seen_xy.add(key)
                    self.add("platform_point_coordinate", "pass" if dimensions else "needs_review", "Pixel coordinate is finite and within image bounds; target alignment still requires viewing", {"index": i, "xy": xy, "source": pt.get("source")})

        if pct_pts:
            for i, pm in enumerate(pct_pts):
                px, py = pm["pct_xy"]
                if not (math.isfinite(px) and math.isfinite(py) and 0.0 <= px <= 100.0 and 0.0 <= py <= 100.0):
                    self.add("platform_point_dom_marker", "blocked", "DOM marker percentage style falls outside 0%–100%", {"index": i, "pct_xy": [px, py]})

        self.metadata["platform_points"] = points

    def author_review(self, author, dimensions):
        if self.html_mode:
            self._html_point_review(dimensions)
        else:
            inline = author.get("platform_points")
            pin_file = self.directory / "platform_points.json"
            file_points = None
            if pin_file.is_file():
                try:
                    file_points = load(pin_file)
                except (OSError, ValueError):
                    self.add("platform_points_json", "blocked", "Cannot parse platform_points.json")
            points = inline if isinstance(inline, list) else file_points
            if inline is not None and file_points is not None and inline != file_points:
                self.add("platform_points_conflict", "needs_review", "Inline and standalone platform points differ; select the actual submitted set")
            if not isinstance(points, list) or not 1 <= len(points) <= 3:
                self.add("platform_point_count", "blocked", "Platform points must be a separate set of 1–3 key positions; full author points are not substituted", {"count": len(points) if isinstance(points, list) else None})
            else:
                self.add("platform_point_count", "pass", "Platform key-point count is 1–3", {"count": len(points)})
                for i, point in enumerate(points):
                    if not isinstance(point, dict):
                        self.add("platform_point_coordinate", "blocked", "Point is not an object", {"index": i})
                        continue
                    xy = point.get("xy", [point.get("x"), point.get("y")])
                    unit = point.get("coordinate_system", author.get("point_coordinate_system", "pixels"))
                    if not isinstance(xy, (list, tuple)) or len(xy) != 2 or not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in xy):
                        self.add("platform_point_coordinate", "blocked", "Coordinates must be two finite numeric values", {"index": i})
                    elif unit != "pixels":
                        self.add("platform_point_coordinate", "needs_review", "Non-pixel coordinates require an explicit mapping to the final image", {"index": i, "coordinate_system": unit})
                    elif dimensions and not (0 <= xy[0] < dimensions[0] and 0 <= xy[1] < dimensions[1]):
                        self.add("platform_point_coordinate", "blocked", "Point falls outside the final image bounds", {"index": i, "xy": xy, "dimensions": dimensions})
                    else:
                        self.add("platform_point_coordinate", "pass" if dimensions else "needs_review", "Pixel coordinate is finite and within known bounds; target alignment still requires viewing", {"index": i, "xy": xy})

        segments = [("image", author.get("cot_image_understanding", author.get("cot1"))), ("reasoning", author.get("cot_reasoning", author.get("cot2")))]
        for name, value in segments:
            self.add(f"author_solution_{name}", "pass" if isinstance(value, str) and value.strip() else "blocked", "Two author-written solution sections are required; mere presence does not establish full evidence coverage", {"section": name, "characters": len(value) if isinstance(value, str) else 0})
        qtype = author.get("question_type")
        qtype_ok = isinstance(qtype, str) and (qtype in MAIN_TYPES or any(mt in qtype for mt in MAIN_TYPES))
        self.add("question_type", "pass" if qtype_ok else "needs_review", "Check against the stored eight-category mapping; no live platform was accessed", {"question_type": qtype, "canonical_type": author.get("canonical_type")})
        answer = author.get("answer", author.get("response"))
        self.add("author_answer", "pass" if answer is not None and str(answer).strip() else "blocked", "Author answer exists; correctness and unique-match semantics require review")
        if self.html_mode:
            self.add("oracle_presence", "not_applicable", "HTML 双文件交付模式不要求存在 oracle.py", {"present": False, "mode": "html_delivery"})
        else:
            oracle_json = self.directory / "oracle.json"
            if oracle_json.is_file():
                stored = self.read(oracle_json)
                same = str(stored.get("answer")) == str(answer)
                self.add("stored_answer_consistency", "pass" if same else "needs_review", "Compared stored answer strings only; no oracle executed, no scientific correctness inferred", {"same_string": same})
            self.add("oracle_presence", "pass" if (self.directory / "oracle.py").is_file() else "needs_review", "Oracle presence recorded only; this checker never imports or runs it", {"present": (self.directory / "oracle.py").is_file()})

    def _find_eval_4x(self, qid: str | None) -> Path | None:
        candidates: list[Path] = [self.directory / "eval_4x.json"]
        if isinstance(qid, str) and qid:
            for base in [self.directory, *list(self.directory.parents)[:4]]:
                candidates.append(base / "_work" / qid / "eval_4x.json")
                candidates.append(base / "outputs" / "_work" / qid / "eval_4x.json")
        for cand in candidates:
            if cand.is_file():
                return cand
        return None

    def evaluation_review(self, author):
        qid, version = author.get("id"), author.get("version")
        roots = [p / "evaluation" for p in [self.directory, *list(self.directory.parents)[:4]] if (p / "evaluation").is_dir()]
        receipts = []
        summaries = []
        if roots and isinstance(qid, str):
            root = roots[0]
            for path in sorted(root.glob(f"**/attempts/r*-{qid}.json")):
                try:
                    rec = load(path)
                except (OSError, ValueError):
                    self.add("evaluation_receipt", "needs_review", "Unreadable receipt", {"path": str(path)})
                    continue
                if rec.get("question_version") != version:
                    continue
                req_model = self.expected_model or rec.get("requested_model")
                req_effort = self.expected_effort or rec.get("requested_effort")
                actual_models = rec.get("provider_models", [])
                actual_efforts = rec.get("provider_efforts", [])
                model_ok = bool(req_model and actual_models and all(x == req_model for x in actual_models))
                effort_ok = bool(req_effort and actual_efforts and all(x == req_effort for x in actual_efforts))
                tools = rec.get("tools_available")
                tools_ok = rec.get("no_tools") is False and isinstance(tools, list) and bool(tools)
                grade = rec.get("grade", {}).get("status")
                status, reason = rec.get("status"), rec.get("invalid_reason")
                if status != "completed":
                    classification = "no_valid_complete_answer"
                elif grade == "needs_review":
                    classification = "answer_needs_review"
                elif not (model_ok and effort_ok and tools_ok and rec.get("contract_accepted") is True):
                    classification = "protocol_unverified_or_mismatch"
                elif grade == "incorrect":
                    classification = "machine_incorrect_candidate_requires_content_review"
                elif grade == "correct":
                    classification = "machine_correct"
                else:
                    classification = "grade_unverified"
                trace = rec.get("trace")
                trace_path = path.parent.parent / trace if isinstance(trace, str) else None
                receipts.append({"path": str(path), "round": rec.get("round"), "classification": classification,
                                 "status": status, "invalid_reason": reason, "invalid_detail": rec.get("invalid_detail"),
                                 "machine_grade": grade, "requested_model": req_model, "provider_models": actual_models,
                                 "requested_effort": req_effort, "provider_efforts": actual_efforts,
                                 "model_echo_matches": model_ok, "effort_echo_matches": effort_ok,
                                 "tools_declared_available": tools_ok, "tools_available": tools,
                                 "observed_tool_counts": rec.get("observed_tool_counts", {}),
                                 "trace_exists": bool(trace_path and trace_path.is_file()), "seconds": rec.get("seconds"),
                                 "carried_seconds": rec.get("carried_seconds"), "timeout_seconds": rec.get("timeout_seconds")})
            for path in sorted(root.glob("**/evaluation_summary.json")):
                try:
                    summary = load(path)
                except (OSError, ValueError):
                    continue
                for row in summary.get("questions", []):
                    if row.get("id") != qid:
                        continue
                    records = row.get("rounds", []) + row.get("skipped_rounds", [])
                    versions = {r.get("question_version") for r in records if isinstance(r, dict)}
                    if version not in versions:
                        continue
                    recorded_rounds = {r["round"] for r in receipts if Path(r["path"]).parent.parent == path.parent and isinstance(r["round"], int)}
                    planned = row.get("planned", summary.get("config", {}).get("rounds_per_question"))
                    skipped = [{k: r.get(k) for k in ("round", "status", "triggered_by_round", "reason")} for r in row.get("skipped_rounds", [])]
                    summaries.append({"path": str(path), "planned": planned, "recorded_rounds": sorted(recorded_rounds),
                                      "rounds_without_receipt": sorted(set(range(1, planned + 1)) - recorded_rounds) if isinstance(planned, int) and 0 < planned <= 100 else None,
                                      "skipped_records": skipped, "reported_pending": row.get("pending"),
                                      "note": "Summary skip reasons are retained as declarations; they are not completed model answers."})

        eval_4x_path = self._find_eval_4x(qid)
        eval_4x_meta = None
        if eval_4x_path is not None:
            try:
                ev4 = load(eval_4x_path)
                counts = ev4.get("counts") or {}
                verdict = ev4.get("verdict")
                qualified = ev4.get("difficulty_qualified")
                model_match = (not self.expected_model) or (ev4.get("model") == self.expected_model)
                effort_match = (not self.expected_effort) or (ev4.get("reasoning_effort") == self.expected_effort)
                eval_4x_meta = {
                    "path": str(eval_4x_path),
                    "model": ev4.get("model"),
                    "reasoning_effort": ev4.get("reasoning_effort"),
                    "api_mode": ev4.get("api_mode"),
                    "requested_trials": ev4.get("requested_trials"),
                    "counts": counts,
                    "difficulty_qualified": qualified,
                    "verdict": verdict,
                    "model_matches_expected": model_match,
                    "effort_matches_expected": effort_match,
                }
            except (OSError, ValueError) as exc:
                self.add("eval_4x_receipt", "needs_review", "Unreadable eval_4x.json receipt", {"path": str(eval_4x_path), "error": str(exc)})

        self.metadata["evaluation"] = {
            "id": qid,
            "version": version,
            "records": receipts,
            "counts": dict(Counter(r["classification"] for r in receipts)),
            "summaries": summaries,
            "eval_4x": eval_4x_meta,
            "completed_rounds": sorted({r["round"] for r in receipts if r["status"] == "completed" and isinstance(r["round"], int)}),
            "policy": "Latest receipt files or direct eval_4x.json receipts only; missing/timeout/error trials are not counted as model errors.",
        }

        if eval_4x_meta is not None:
            if eval_4x_meta["difficulty_qualified"] is True and eval_4x_meta["model_matches_expected"] and eval_4x_meta["effort_matches_expected"]:
                self.add("evaluation_evidence", "pass", "Loaded 4-trial direct evaluation receipt (eval_4x.json) with difficulty_qualified=True; human content review still applies", eval_4x_meta)
            else:
                self.add("evaluation_evidence", "needs_review", "Loaded eval_4x.json receipt; difficulty qualification, protocol echo, or error count requires review", eval_4x_meta)
        elif not receipts:
            self.add("evaluation_evidence", "needs_review", "No matching versioned local receipts or eval_4x.json found; no test result or failure rate inferred")
        else:
            self.add("evaluation_evidence", "needs_review", "Receipts were classified; confirm requested trial count, content validity, final answer and tool/trace integrity before accepting failures", self.metadata["evaluation"]["counts"])
        if any(not row["trace_exists"] for row in receipts):
            self.add("evaluation_trace", "needs_review", "One or more matching receipts lack a locally resolvable trace")
        if any(row["rounds_without_receipt"] for row in summaries):
            self.add("evaluation_round_gaps", "needs_review", "Planned rounds lack receipt files; preserve early-stop, interruption or missing-evidence status instead of filling them as failures", summaries)

    def run(self):
        author, public = self.inputs()
        self.public_review(public)
        dimensions = self.image_review(author)
        self.author_review(author, dimensions)
        self.evaluation_review(author)
        manual = [
            "View native key ROIs and final image at 100%; establish readability, occlusion, similar-color identity, Chinese-text extent and point-to-evidence alignment.",
            "Trace each required image observation to parameter choice, constraints and requested output; lawful full transcription or pixel registration is not cheating.",
            "Review source licenses and panel provenance, actual measurements versus simulated assays, scientific labels and public physical assumptions.",
            "Independently review facts-to-pixels, every empty/tie/boundary branch, answer formatting and GT. This tool does not execute an oracle.",
            "Review measurement error propagation and feasible-set/optimal-winner stability; inspect actual counterfactual recomputation, not a claimed pass flag.",
            "If an error is claimed, distinguish corrected intermediate reads from the final adopted facts, and exclude content defects, protocol mismatches, interruptions and service failures.",
        ]
        self.add("human_evidence_review", "needs_review", "Machine checks cannot establish these necessary conditions", manual)
        counts = Counter(x["status"] for x in self.checks)
        return {"schema_version": "1.0", "checked_at": datetime.now(timezone.utc).isoformat(), "case": str(self.directory),
                "id": author.get("id"), "version": author.get("version"),
                "status": "blocked" if counts["blocked"] else "needs_review",
                "machine_blockers": counts["blocked"], "counts": dict(counts), "checks": self.checks,
                "metadata": self.metadata, "platform_accepted": False, "difficulty_proven": False,
                "side_effects": {"oracle_executed": False, "model_api_called": False, "network_used": False, "dependencies_installed": False, "case_files_modified": False},
                "meaning": "blocked means a concrete local schema/reference/profile conflict; needs_review means unknown or incomplete evidence. pass applies only to the named limited check, never whole-case approval."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path, help="Case directory, author_record.html, or author/question JSON file")
    parser.add_argument("--out", required=True, type=Path, help="New JSON report path outside original case files")
    parser.add_argument("--min-native-short", type=int, default=1080, help="Deprecated compatibility option (not enforced)")
    parser.add_argument("--min-native-long", type=int, default=1920, help="Deprecated compatibility option (not enforced)")
    parser.add_argument("--expected-model", help="Optional requested model to compare with every actual echo")
    parser.add_argument("--expected-effort", help="Optional requested effort to compare with every actual echo")
    args = parser.parse_args()
    if not args.case.exists():
        parser.error("--case does not exist")
    if args.out.exists():
        parser.error("--out already exists; choose a new report path")
    if args.min_native_short < 0 or args.min_native_long < args.min_native_short:
        parser.error("Invalid native-resolution screening profile")
    review = Reviewer(args.case, args.min_native_short, args.min_native_long, args.expected_model, args.expected_effort).run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.out.resolve()), "id": review["id"], "status": review["status"], "counts": review["counts"], "model_api_called": False}, ensure_ascii=False))
    return 1 if review["machine_blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
