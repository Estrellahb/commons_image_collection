"""Build the Excel index with the Codex runtime or XlsxWriter."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess

from PIL import Image


def spreadsheet_runtime():
    deps = Path(os.environ.get("CODEX_WORKSPACE_DEPS") or
                Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies")
    node = deps / "node/bin" / ("node.exe" if os.name == "nt" else "node")
    modules = deps / "node/node_modules"
    if not (node.is_file() and (modules / "@oai/artifact-tool").is_dir()):
        raise ValueError("未找到 Codex 电子表格运行时；请设置 CODEX_WORKSPACE_DEPS 为运行时 dependencies 目录。")
    return node, modules


def row_for(root, record):
    path = root / record["file"]
    with Image.open(path) as image:
        # Preview is small and embedded in XLSX; the saved photo is unaffected.
        image.draft("RGB", (168, 84))
        image.thumbnail((168, 84), Image.Resampling.LANCZOS)
        preview = BytesIO()
        image.convert("RGB").save(preview, format="JPEG", quality=83, optimize=True)
        return [path.name, record["category"], image.width, image.height,
                "data:image/jpeg;base64," + base64.b64encode(preview.getvalue()).decode("ascii")]


def write_with_xlsxwriter(rows, output):
    from xlsxwriter import Workbook

    with Workbook(str(output)) as workbook:
        sheet = workbook.add_worksheet("图片分类")
        sheet.hide_gridlines(2)
        sheet.freeze_panes(1, 0)
        sheet.set_tab_color("#194353")
        sheet.set_column_pixels(0, 0, 252)
        sheet.set_column_pixels(1, 1, 242)
        header = workbook.add_format({
            "bg_color": "#194353", "font_color": "#FFFFFF", "bold": True,
            "font_name": "Microsoft YaHei", "font_size": 11, "align": "center", "valign": "vcenter",
        })
        sheet.set_row_pixels(0, 34)
        sheet.write_row(0, 0, ["图片", "图片种类"], header)
        body = {"font_name": "Microsoft YaHei", "font_size": 10, "font_color": "#163744", "align": "center"}
        formats = [
            (workbook.add_format({**body, **fill, "valign": "bottom"}),
             workbook.add_format({**body, **fill, "valign": "vcenter"}))
            for fill in ({}, {"bg_color": "#F3F8F9"})
        ]
        for row, (name, category, width, height, data_url) in enumerate(rows, start=1):
            photo_format, category_format = formats[(row - 1) % 2]
            sheet.set_row_pixels(row, 112)
            sheet.write_string(row, 0, name, photo_format)
            sheet.write_string(row, 1, category, category_format)
            sheet.insert_image(row, 0, name, {
                "image_data": BytesIO(base64.b64decode(data_url.partition(",")[2])),
                "x_offset": (252 - width) // 2, "y_offset": 6 + (84 - height) // 2,
                "description": name, "object_position": 2,
            })


def write_workbook(root, records, output, preview=None):
    rows = [row_for(root, record) for record in sorted(records, key=lambda r: r["file"])]
    try:
        node, modules = spreadsheet_runtime()
    except ValueError:
        if preview or os.environ.get("CODEX_WORKSPACE_DEPS"):
            raise
        write_with_xlsxwriter(rows, output)
        return
    args = [str(node), str(Path(__file__).with_suffix(".mjs")), str(output), str(modules)]
    if preview:
        args.append(str(preview))
    try:
        result = subprocess.run(args, input=json.dumps(rows, ensure_ascii=False).encode("utf-8"), capture_output=True)
    finally:
        output.with_name(output.name + ".inspect.ndjson").unlink(missing_ok=True)
    if result.returncode:
        raise ValueError("生成 Excel 失败：" + result.stderr.decode("utf-8", errors="replace").strip())
