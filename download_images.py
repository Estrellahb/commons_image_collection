"""Download selected Commons photos as PNG or JPG, reducing dimensions only to fit."""

import argparse
from contextlib import closing, contextmanager
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values
from PIL import Image, ImageChops, ImageOps, PngImagePlugin
import requests


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "采集数据.sqlite"
API = "https://commons.wikimedia.org/w/api.php"
LEDGER = "来源与许可.jsonl"
REPORT = "未入库.csv"
MAX_PNG_BYTES = 5_000_000
PREFERRED_PNG_BYTES = MAX_PNG_BYTES
PHOTO_SUFFIXES = {".png", ".jpg", ".jpeg"}
MIN_RESIZED_EDGE = 2048
MAX_TRANSFER = 100 * 1024 * 1024
RATE_BYTES = 2_000_000  # 16 Mbps, with one image transfer at a time.
GROUPS = {
    "居家场景": {
        "厨房台面": "kitchen", "浴室洗漱": "bathroom", "书房桌面": "desk",
        "衣物收纳": "clothes", "玩具积木": "toys", "药品保健": "health",
        "文具办公": "stationery", "工具五金": "hardware",
    },
    "公共场景": {
        "超市货架": "shelf", "健身房": "gym", "图书馆": "library",
        "街道停车": "parking", "餐饮后厨": "restaurant", "游乐场": "playground",
        "会场展台": "exhibit", "交通枢纽": "transit", "市场摊位": "market",
    },
    "小众专业实物": {
        "钱币·邮票·卡券": "collectibles", "科研仪器·实验器材": "lab",
        "工业异形部件": "industrial", "传统工具·手工艺器物": "craft",
        "体育装备·护具": "sports", "珠宝·矿物·标本": "specimens",
        "钟表·仪表盘": "dials",
    },
}
CATEGORIES = {f"{group}/{name}": code for group, names in GROUPS.items() for name, code in names.items()}


class Rejected(ValueError):
    pass


class StopBatch(RuntimeError):
    pass


class PlainText(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.parts = []
        self.feed(markup)

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return " ".join(" ".join(self.parts).split())


def queue_item(url, category, location):
    if not isinstance(url, str) or not isinstance(category, str):
        raise ValueError(f"{location}：文件页和图片种类必须是文本。")
    url, category = url.strip(), category.strip()
    parsed = urlsplit(url)
    title = unquote(parsed.path).removeprefix("/wiki/")
    if (parsed.scheme != "https" or parsed.netloc != "commons.wikimedia.org"
            or not parsed.path.startswith("/wiki/") or not title.startswith("File:")
            or not title.removeprefix("File:").strip() or "|" in title):
        raise ValueError(f"{location}：填入 Commons 单张图片的 File: 文件页链接。")
    if category not in CATEGORIES:
        raise ValueError(f"{location}：未知图片种类「{category}」；用 --list-categories 查看。")
    return url, title, category


def read_csv_queue(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["文件页", "图片种类"]:
            raise ValueError("采集清单表头必须是：文件页,图片种类")
        for row in reader:
            url = (row["文件页"] or "").strip()
            category = (row["图片种类"] or "").strip()
            if not url and not category and None not in row:
                continue
            if None in row:
                raise ValueError(f"第 {reader.line_num} 行：列数不正确，含逗号的链接需加双引号。")
            yield queue_item(url, category, f"第 {reader.line_num} 行")


def read_queue(path):
    if path.suffix.lower() == ".csv":
        return list(read_csv_queue(path))
    if not path.is_file():
        raise ValueError(f"找不到采集数据库：{path}")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT id, file_url, category FROM collection_queue ORDER BY id")
            return [queue_item(url, category, f"collection_queue.id={row_id}") for row_id, url, category in rows]
    except sqlite3.Error as exc:
        raise ValueError(f"无法读取采集数据库 {path.name} 的 collection_queue 表：{exc}") from exc


def retry_delay(value):
    if not value:
        return 10
    try:
        return max(1, int(value))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(1, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 10


class Commons:
    def __init__(self, session, contact, token, proxy=""):
        self.session = session
        self.headers = {"User-Agent": f"ZeroBenchCommonsCollector/1.0 ({contact})"}
        self.token = token
        self.proxies = {"https": proxy} if proxy else None

    def get(self, url, *, params=None, media=False):
        headers = dict(self.headers)
        if self.token and not media:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(2):
            if not media:
                time.sleep(0.5)
            response = self.session.get(
                url, params=params, headers=headers, stream=media, allow_redirects=False,
                proxies=self.proxies, timeout=(15, 60)
            )
            if response.status_code in (429, 503):
                code = response.status_code
                delay = retry_delay(response.headers.get("Retry-After"))
                response.close()
                if attempt or delay > 60:
                    raise StopBatch(f"Wikimedia 返回 HTTP {code}；已停止本批，请在限流或服务恢复后重跑。")
                time.sleep(delay)
                continue
            if response.status_code in (401, 403):
                code = response.status_code
                response.close()
                raise StopBatch(f"Wikimedia 返回 HTTP {code}；检查访问权限、User-Agent 和已填写的令牌。")
            if response.status_code != 200:
                code = response.status_code
                response.close()
                raise Rejected(f"Wikimedia 返回 HTTP {code}")
            return response

    def file_info(self, title):
        params = {
            "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
            "titles": title, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": "Artist|Credit|LicenseShortName|LicenseUrl|UsageTerms|AttributionRequired|Restrictions",
            "iiextmetadatalanguage": "en", "maxlag": 5,
        }
        if self.token:
            params["assert"] = "user"
        with self.get(API, params=params) as response:
            payload = response.json()
        if "error" in payload:
            code = payload["error"].get("code", "unknown")
            if code == "maxlag" or self.token:
                raise StopBatch(f"Wikimedia API 返回 {code}；检查服务器状态或配置的令牌。")
            raise Rejected(f"Wikimedia API 返回 {code}")
        page, = payload["query"]["pages"]
        if not page.get("imageinfo"):
            raise Rejected("Commons 文件页没有可下载的图片")
        return page["pageid"], page["title"], page["imageinfo"][0]

    def fetch(self, url, expected_size):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "upload.wikimedia.org"
                or not parsed.path.startswith("/wikipedia/commons/")
                or parsed.path.startswith("/wikipedia/commons/thumb/")):
            raise Rejected("API 没有返回 Commons 原始媒体文件地址")
        if expected_size > MAX_TRANSFER:
            raise Rejected("媒体超过 100 MiB 内存下载上限")
        data = BytesIO()
        with self.get(url, media=True) as response:
            for chunk in response.iter_content(64 * 1024):
                data.write(chunk)
                if data.tell() > MAX_TRANSFER:
                    raise Rejected("媒体超过 100 MiB 内存下载上限")
                time.sleep(len(chunk) / RATE_BYTES)
        if data.tell() != expected_size:
            raise Rejected("实际传输字节数与 Commons 文件信息不符")
        data.seek(0)
        return data


def licensing(info):
    fields = info.get("extmetadata", {})
    meta = {k: PlainText(v["value"]).text() for k, v in fields.items() if isinstance(v.get("value"), str)}
    license_name = meta.get("LicenseShortName", "")
    if not re.fullmatch(r"CC0(?: 1\.0)?|PD|Public domain|CC BY(?:-SA)? \d+\.\d+(?: [^ ]+)?", license_name, re.I):
        raise Rejected(f"许可需要人工确认：{license_name or '未提供'}")
    if meta.get("Restrictions"):
        raise Rejected(f"条目列有额外限制：{meta['Restrictions']}")
    if re.match(r"CC BY", license_name, re.I) and not (meta.get("Artist") and meta.get("LicenseUrl")):
        raise Rejected("CC BY / CC BY-SA 条目缺少作者或许可链接")
    return meta


def pack_png(pixels, color_chunks, icc):
    options = {"icc_profile": icc} if icc else {}
    png_info = PngImagePlugin.PngInfo()
    if "gamma" in color_chunks:
        png_info.add(b"gAMA", struct.pack(">I", round(color_chunks["gamma"] * 100000)))
    if "chromaticity" in color_chunks:
        png_info.add(b"cHRM", struct.pack(">8I", *(round(v * 100000) for v in color_chunks["chromaticity"])))
    if "srgb" in color_chunks:
        png_info.add(b"sRGB", struct.pack(">B", color_chunks["srgb"]))
    if "transparency" in color_chunks:
        options["transparency"] = color_chunks["transparency"]
    output = BytesIO()
    pixels.save(output, format="PNG", optimize=True, pnginfo=png_info, **options)
    return output


def fit_png(pixels, target, limit, color_chunks, icc, full_size):
    """Fit by reducing spatial resolution, never by reducing the color palette."""
    if "transparency" in color_chunks:
        # Resample a real alpha channel, not a transparent color key.
        pixels.info["transparency"] = color_chunks["transparency"]
        remaining = {k: v for k, v in color_chunks.items() if k != "transparency"}
        with pixels.convert("RGBA") as rgba:
            if pixels.mode != "L":
                return fit_png(rgba, target, limit, remaining, icc, full_size)
            with rgba.getchannel("A") as alpha, Image.merge("LA", (pixels, alpha)) as gray_alpha:
                return fit_png(gray_alpha, target, limit, remaining, icc, full_size)
    return fit_by_resizing(pixels, target, limit, full_size, lambda image: pack_png(image, color_chunks, icc))


def fit_by_resizing(pixels, target, limit, full_size, pack):
    source_edge = max(pixels.size)
    edge = source_edge
    size = full_size
    while True:
        minimum = MIN_RESIZED_EDGE if edge > MIN_RESIZED_EDGE else 1
        edge = max(minimum, int(edge * min(0.93, 0.98 * math.sqrt(target / size))))
        dimensions = tuple(max(1, round(length * edge / source_edge)) for length in pixels.size)
        with pixels.resize(dimensions, Image.Resampling.LANCZOS, reducing_gap=3) as resized:
            output = pack(resized)
        size = output.tell()
        if size <= target or (edge <= MIN_RESIZED_EDGE and size <= limit) or edge == 1:
            return dimensions, output.getvalue()


@contextmanager
def photo_pixels(data):
    with Image.open(data) as original:
        if original.format not in ("JPEG", "PNG") or getattr(original, "n_frames", 1) != 1:
            raise Rejected("仅接受单帧 JPEG / PNG 照片")
        with ImageOps.exif_transpose(original) as pixels:
            if pixels.mode not in ("RGB", "RGBA", "L"):
                raise Rejected(f"当前不处理 {pixels.mode} 色彩模式")
            yield pixels


def encode_png(data, limit, allow_resize=True, preferred=PREFERRED_PNG_BYTES):
    with photo_pixels(data) as pixels:
        icc = pixels.info.get("icc_profile")
        color_chunks = {
            name: pixels.info[name] for name in ("gamma", "chromaticity", "srgb", "transparency")
            if name in pixels.info
        }
        pixels.info.clear()
        output = pack_png(pixels, color_chunks, icc)
        full_size = output.tell()
        target = min(preferred, limit)
        edge = max(pixels.size)
        if allow_resize and edge > 1 and (full_size > limit or (full_size > target and edge > MIN_RESIZED_EDGE)):
            dimensions, payload = fit_png(pixels, target, limit, color_chunks, icc, full_size)
            if len(payload) < full_size:
                return dimensions, payload, True
        output.seek(0)
        with Image.open(output) as decoded:
            if (decoded.size != pixels.size or decoded.mode != pixels.mode
                    or decoded.info.get("icc_profile") != icc
                    or any(decoded.info.get(k) != v for k, v in color_chunks.items())
                    or ImageChops.difference(pixels, decoded).getbbox(alpha_only=False)):
                raise Rejected("输出与原图像素、尺寸或颜色配置不一致")
        return pixels.size, output.getvalue(), False


def encode_jpg(data, limit, allow_resize=True, preferred=PREFERRED_PNG_BYTES):
    """Encode a high-quality JPG, or return None when PNG must preserve transparency."""
    with photo_pixels(data) as pixels:
        if "A" in pixels.getbands() or "transparency" in pixels.info:
            return None
        icc = pixels.info.get("icc_profile")
        pixels.info.clear()

        def pack(image):
            output = BytesIO()
            # Keep full chroma resolution for fine colored details and text.
            settings = {"format": "JPEG", "quality": 93, "subsampling": 0, "icc_profile": icc}
            try:
                image.save(output, optimize=True, **settings)
            except OSError:
                # The optimized encoder's internal buffer can overflow on very detailed images.
                output.seek(0)
                output.truncate()
                image.save(output, **settings)
            return output

        output = pack(pixels)
        full_size = output.tell()
        target = min(preferred, limit)
        edge = max(pixels.size)
        if allow_resize and edge > 1 and (full_size > limit or (full_size > target and edge > MIN_RESIZED_EDGE)):
            dimensions, payload = fit_by_resizing(pixels, target, limit, full_size, pack)
            if len(payload) < full_size:
                return dimensions, payload, True
        return pixels.size, output.getvalue(), False


def atomic_save(path, write):
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.stem}-", suffix=path.suffix, delete=False) as temp:
        staging = Path(temp.name)
    try:
        write(staging)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def load_records(root):
    path = root / LEDGER
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return {r["page_id"]: r for r in records if (root / r["file"]).is_file()}


def collect_one(root, commons, item, records, limit, allow_resize=True, recompress=False, *, output_format="png"):
    source, title, category = item
    page_id, canonical_title, info = commons.file_info(title)
    saved = records.get(page_id)
    replacing = False
    limit = min(limit, MAX_PNG_BYTES)
    preferred = min(limit, PREFERRED_PNG_BYTES)
    suffix = ".jpg" if output_format == "jpg" else ".png"
    if saved:
        if saved["category"] != category:
            raise Rejected(f"已归类为「{saved['category']}」，未在第二个目录重复下载")
        saved_suffix = Path(saved["file"]).suffix.lower()
        if saved_suffix in PHOTO_SUFFIXES:
            if not allow_resize and saved.get("resized"):
                raise Rejected("已保存的是缩小版本，不符合本次保留原尺寸的要求")
            size = (root / saved["file"]).stat().st_size
            if recompress and allow_resize and size > limit:
                replacing = True
                suffix = saved_suffix
            elif size > limit:
                raise Rejected(f"已保存的图片为 {size / 1_000_000:.2f} MB，超过当前上限")
            else:
                return saved, "已存在"
    meta = licensing(info)
    if info["mime"] not in ("image/jpeg", "image/png"):
        raise Rejected(f"不支持此媒体类型：{info['mime']}")
    data = commons.fetch(info["url"], info["size"])
    encoded = encode_jpg(data, limit, allow_resize) if suffix != ".png" else None
    if encoded is None:
        suffix = ".png"
        encoded = encode_png(data, limit, allow_resize)
    (width, height), payload, resized = encoded
    if len(payload) > limit:
        raise Rejected(f"{suffix[1:].upper()} 为 {len(payload) / 1_000_000:.2f} MB，超过 {limit / 1_000_000:g} MB；未保存")
    categorized_file = Path(*category.split("/"), f"zb-{CATEGORIES[category]}-{page_id}{suffix}")
    relative = Path("img", categorized_file)
    if replacing:
        existing = Path(saved["file"])
        if existing not in (relative, Path("images", categorized_file)):
            raise Rejected("已保存文件的路径与当前分类不一致，未替换")
        relative = existing
    output = root / relative
    if not replacing and output.exists():
        raise Rejected(f"目标文件已存在但无来路记录，请检查 {relative.name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "page_id": page_id, "category": category, "file": relative.as_posix(),
        "title": canonical_title, "source_page": info.get("descriptionurl", source),
        "source_url": info["url"], "source_bytes": info["size"],
        "source_width": info["width"], "source_height": info["height"],
        "width": width, "height": height, "bytes": len(payload),
        "limit_bytes": limit, "preferred_bytes": preferred, "license": meta,
        "modifications": (
            ("Resized with Lanczos to fit the size limit. " if resized else "")
            + ("Lossy JPEG re-encoding." if suffix != ".png" else
               "Lossless PNG re-encoding of resized pixels." if resized else "Lossless re-encoding of decoded pixels.")
            + " EXIF orientation applied; only color-related metadata kept."
        ),
        "resized": resized,
    }
    previous = output.read_bytes() if replacing else None
    atomic_save(output, lambda p: p.write_bytes(payload))
    try:
        with (root / LEDGER).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        if previous is None:
            output.unlink()
        else:
            atomic_save(output, lambda p: p.write_bytes(previous))
        raise
    records[page_id] = record
    return record, "已重新压缩" if replacing else ("缩小后已保存" if resized else "已保存")


def write_index(root, records):
    from make_index import write_workbook

    output = root / "图片分类.xlsx"
    compatible = [
        r for r in records.values()
        if Path(r["file"]).suffix.lower() in PHOTO_SUFFIXES and (root / r["file"]).stat().st_size <= MAX_PNG_BYTES
    ]
    atomic_save(output, lambda p: write_workbook(root, compatible, p))
    return len(compatible)


def write_rejections(root, rejections):
    def save(path):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["文件页", "图片种类", "未入库原因"])
            writer.writerows(rejections)

    atomic_save(root / REPORT, save)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="采集 Commons 实拍照片到 img/，支持 PNG 和 JPG，单张硬上限 5 MB。")
    parser.add_argument("--input", type=Path, default=DEFAULT_DB, help="采集数据库（默认采集数据.sqlite；兼容显式传入的 CSV）")
    parser.add_argument("--format", choices=("png", "jpg"), default="png", help="新图输出格式，默认 png；选 jpg 时有透明通道的图仍保存为 PNG")
    parser.add_argument("--target-mb", type=float, default=MAX_PNG_BYTES / 1_000_000, help="体积硬上限，默认 5 MB，可设更小")
    parser.add_argument("--no-resize", "--strict-size", action="store_true", help="必须保留原尺寸，超过上限时跳过")
    parser.add_argument("--recompress-existing", action="store_true", help="对清单内超过上限的旧图，按已保存格式从来源文件重新压缩")
    parser.add_argument("--list-categories", action="store_true", help="列出合法分类")
    parser.add_argument("--dry-run", action="store_true", help="只检查输入清单，不联网")
    parser.add_argument("--index-only", action="store_true", help="只从已保存图片重建 Excel，不联网")
    args = parser.parse_args()
    if args.no_resize and args.recompress_existing:
        parser.error("--no-resize 和 --recompress-existing 不能同时使用")
    if args.list_categories:
        print("\n".join(CATEGORIES))
        return 0
    if not (0.001 <= args.target_mb <= MAX_PNG_BYTES / 1_000_000):
        parser.error("--target-mb 必须在 0.001 到 5 之间")
    if args.index_only:
        records = load_records(ROOT)
        count = write_index(ROOT, records)
        print(f"已重建图片分类.xlsx：{count} 张")
        return 0
    queue = read_queue(args.input)
    if args.dry_run:
        print(f"清单格式正确：{len(queue)} 张候选图")
        for _, title, category in queue:
            print(f"{category}：{title}")
        return 0
    if not queue:
        raise ValueError("采集清单为空，请先加入候选图片的文件页和分类。")
    config = dotenv_values(ROOT / ".env")
    contact = (os.getenv("WIKIMEDIA_CONTACT", config.get("WIKIMEDIA_CONTACT")) or "").strip()
    token = (os.getenv("WIKIMEDIA_ACCESS_TOKEN", config.get("WIKIMEDIA_ACCESS_TOKEN")) or "").strip()
    proxy = (os.getenv("WIKIMEDIA_PROXY_URL", config.get("WIKIMEDIA_PROXY_URL")) or "").strip()
    if not contact or not contact.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in contact):
        raise ValueError("请在 .env 中填入联系邮箱或 URL 编码的 Wikimedia 用户页链接。")
    if token and not re.fullmatch(r"[!-~]+", token):
        raise ValueError("令牌格式不正确，请复制完整的 Access token，不要带换行或空格。")
    if proxy:
        parsed = urlsplit(proxy)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
            raise ValueError("WIKIMEDIA_PROXY_URL 应为匿名 HTTP 代理地址，例如 http://127.0.0.1:1277。")
    records = load_records(ROOT)
    rejections = []
    collected = 0
    stop = None
    limit = round(args.target_mb * 1_000_000)
    with requests.Session() as session:
        commons = Commons(session, contact, token, proxy)
        for i, item in enumerate(queue):
            try:
                record, state = collect_one(
                    ROOT, commons, item, records, limit, not args.no_resize, args.recompress_existing,
                    output_format=args.format,
                )
                print(f"{state}：{record['file']} ({record['bytes'] / 1_000_000:.2f} MB)")
                collected += 1
            except StopBatch as exc:
                stop = str(exc)
                rejections.append((item[0], item[2], stop))
                rejections.extend((url, category, "本批已停止，尚未处理") for url, _, category in queue[i + 1:])
                break
            except (Rejected, OSError, requests.RequestException, Image.DecompressionBombError) as exc:
                reason = str(exc)
                print(f"未入库：{item[1]}：{reason}", file=sys.stderr)
                rejections.append((item[0], item[2], reason))
                if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                    stop = "网络连接或响应超时，已停止本批；检查代理或直连后可重跑。"
                    rejections.extend((url, category, "本批已停止，尚未处理") for url, _, category in queue[i + 1:])
                    break
    if collected or not stop:
        write_rejections(ROOT, rejections)
        count = write_index(ROOT, records)
        print(f"图片分类.xlsx：共 {count} 张；本次未入库 {len(rejections)} 张。")
    if stop:
        print(stop, file=sys.stderr)
    return 1 if rejections else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PermissionError as exc:
        print(f"无法写入文件：{exc}。如 Excel 正在打开清单，关闭后运行 --index-only 重建。", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
