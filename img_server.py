"""External HTTP server for token-authenticated image download and transfer from ./img."""

import argparse
from base64 import b64decode
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_default_policy
from email.utils import formatdate, parsedate_to_datetime
import hashlib
import hmac
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import sys
from tempfile import NamedTemporaryFile, SpooledTemporaryFile
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit
import zipfile

import image_tags
from img_openapi import openapi_document


ROOT = Path(__file__).resolve().parent
SWAGGER_DIR = ROOT / "swagger_ui"
SWAGGER_ASSETS = {
    "/docs": ("index.html", "text/html; charset=utf-8"),
    "/docs/": ("index.html", "text/html; charset=utf-8"),
    "/docs/swagger-ui.css": ("swagger-ui.css", "text/css; charset=utf-8"),
    "/docs/swagger-ui-bundle.js": ("swagger-ui-bundle.js", "text/javascript; charset=utf-8"),
    "/docs/init.js": ("init.js", "text/javascript; charset=utf-8"),
}
SWAGGER_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
DEFAULT_IMG_DIR = ROOT / "img"
DEFAULT_DB_NAME = "采集数据.sqlite"
LEDGER_NAME = "来源与许可.jsonl"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 18080
DEFAULT_MAX_UPLOAD_MB = 50.0
MAX_JSON_BODY_BYTES = 1024 * 1024
CHUNK_SIZE = 64 * 1024
SPOOL_LIMIT_BYTES = 16 * 1024 * 1024
PAGE_ID_FILE_RE = re.compile(r"^zb-[a-z]+-(\d+)\.[^.]+$", re.I)
QUEUE_COLUMNS = ", ".join(("id", "file_url", "category", "claimed_by", *image_tags.ANNOTATION_FIELDS))
LOCAL_CLAIM_COLUMNS = ", ".join(("file_path", "claimed_by", *image_tags.ANNOTATION_FIELDS))
THUMB_SIZE = (360, 360)
MAX_THUMB_PIXELS = 32_000_000
THUMB_FORMATS = ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "AVIF", "ICO")
# Fixed JPEG used when the source cannot be previewed, including without Pillow.
THUMB_PLACEHOLDER = b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL"
    "/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCABaAKADASIAAhEBAxEB"
    "/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAL/xAAUEQEAAAAAAAAAAAAAAAAAAAAA"
    "/9oADAMBAAIRAxEAPwC5AKQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//Z"
)

IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}


class PathValidationError(ValueError):
    """Raised when a requested or uploaded relative path is invalid or unsafe."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = int(status)


class RangeError(ValueError):
    """Raised when an HTTP Range header cannot be satisfied."""


class ClaimError(RuntimeError):
    """Base error for database claim tracking operations."""

    def __init__(self, message: str, status: int, *, claimed_by: str = "", details: dict | None = None):
        super().__init__(message)
        self.status = int(status)
        self.claimed_by = claimed_by
        self.details = details or {}


class ClaimConflictError(ClaimError):
    """Raised when a resource is already claimed by another user."""

    def __init__(self, claimed_by: str, message: str, *, details: dict | None = None):
        super().__init__(message, HTTPStatus.CONFLICT, claimed_by=claimed_by, details=details)


class ClaimNotFoundError(ClaimError):
    """Raised when no matching queue row or local image can be found."""

    def __init__(self, message: str):
        super().__init__(message, HTTPStatus.NOT_FOUND)


@dataclass(frozen=True)
class ServerConfig:
    """Resolved runtime configuration for the image HTTP server."""

    img_dir: Path
    token: str
    token_source: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    allow_query_token: bool = True
    allow_upload: bool = False
    allow_all_files: bool = False
    max_upload_bytes: int = int(DEFAULT_MAX_UPLOAD_MB * 1024 * 1024)
    cors_origin: str = ""
    db_path: Path | None = None
    ledger_path: Path | None = None


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file without external dependencies."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            quote_char = val[0]
            val = val[1:-1]
            if quote_char == '"':
                val = val.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        values[key] = val
    return values


def validate_token_value(token: str) -> str:
    """Validate that a configured token is non-empty and free of control characters."""
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("HTTP Token 不能为空。")
    if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in cleaned):
        raise ValueError("HTTP Token 不能包含空格、换行或控制字符。")
    return cleaned


def resolve_config(
    *,
    host: str | None = None,
    port: int | None = None,
    img_dir: Path | None = None,
    token: str | None = None,
    token_file: Path | None = None,
    allow_query_token: bool = True,
    allow_upload: bool = False,
    allow_all_files: bool = False,
    max_upload_mb: float = DEFAULT_MAX_UPLOAD_MB,
    cors_origin: str = "",
    create_dir: bool = False,
    db_path: Path | None = None,
    no_db: bool = False,
    root: Path = ROOT,
    env: dict[str, str] | None = None,
) -> ServerConfig:
    """Build a ServerConfig from CLI arguments, environment variables, and .env."""
    env_map = os.environ if env is None else env
    dotenv = load_dotenv_file(root / ".env")

    def pick(cli_val, env_key: str, default: str = "") -> str:
        if cli_val is not None:
            return str(cli_val)
        return (env_map.get(env_key) or dotenv.get(env_key) or default).strip()

    resolved_host = pick(host, "IMG_SERVER_HOST", DEFAULT_HOST) or DEFAULT_HOST
    port_raw = pick(port, "IMG_SERVER_PORT", str(DEFAULT_PORT))
    try:
        resolved_port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"端口必须是整数：{port_raw}") from exc
    if not (0 <= resolved_port <= 65535):
        raise ValueError(f"端口必须在 0 到 65535 之间：{resolved_port}")

    dir_raw = pick(str(img_dir) if img_dir is not None else None, "IMG_SERVER_DIR", "")
    target_dir = Path(dir_raw) if dir_raw else (root / "img")
    if not target_dir.is_absolute():
        target_dir = root / target_dir
    if target_dir == (root / "img") or create_dir:
        target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise ValueError(f"图片目录不存在或不是文件夹：{target_dir}")
    resolved_dir = target_dir.resolve()

    if token is not None:
        resolved_token = validate_token_value(token)
        token_source = "cli"
    elif token_file is not None:
        if not token_file.is_file():
            raise ValueError(f"找不到 Token 文件：{token_file}")
        resolved_token = validate_token_value(token_file.read_text(encoding="utf-8"))
        token_source = "token-file"
    elif (env_map.get("IMG_SERVER_TOKEN") or "").strip():
        resolved_token = validate_token_value(env_map["IMG_SERVER_TOKEN"])
        token_source = "env"
    elif (dotenv.get("IMG_SERVER_TOKEN") or "").strip():
        resolved_token = validate_token_value(dotenv["IMG_SERVER_TOKEN"])
        token_source = ".env"
    else:
        resolved_token = secrets.token_urlsafe(32)
        token_source = "generated"

    if max_upload_mb <= 0:
        raise ValueError("--max-upload-mb 必须大于 0。")

    resolved_db: Path | None = None
    if not no_db:
        db_raw = pick(str(db_path) if db_path is not None else None, "IMG_SERVER_DB", "")
        if db_raw:
            candidate_db = Path(db_raw)
            if not candidate_db.is_absolute():
                candidate_db = root / candidate_db
            if not candidate_db.is_file():
                raise ValueError(f"找不到数据库文件：{candidate_db}")
            resolved_db = candidate_db.resolve()
        elif (root / DEFAULT_DB_NAME).is_file():
            resolved_db = (root / DEFAULT_DB_NAME).resolve()

    ledger_path = (root / LEDGER_NAME).resolve() if (root / LEDGER_NAME).exists() else (root / LEDGER_NAME)

    env_allow_upload = (env_map.get("IMG_SERVER_ALLOW_UPLOAD") or dotenv.get("IMG_SERVER_ALLOW_UPLOAD") or "").strip().lower()
    env_all_files = (env_map.get("IMG_SERVER_ALL_FILES") or dotenv.get("IMG_SERVER_ALL_FILES") or "").strip().lower()
    env_cors = (env_map.get("IMG_SERVER_CORS_ORIGIN") or dotenv.get("IMG_SERVER_CORS_ORIGIN") or "").strip()

    return ServerConfig(
        img_dir=resolved_dir,
        token=resolved_token,
        token_source=token_source,
        host=resolved_host,
        port=resolved_port,
        allow_query_token=allow_query_token,
        allow_upload=allow_upload or env_allow_upload in {"1", "true", "yes", "on"},
        allow_all_files=allow_all_files or env_all_files in {"1", "true", "yes", "on"},
        max_upload_bytes=int(max_upload_mb * 1024 * 1024),
        cors_origin=cors_origin or env_cors,
        db_path=resolved_db,
        ledger_path=ledger_path,
    )


def guess_mime_type(path: Path, allow_all_files: bool = False) -> str | None:
    """Return MIME type for supported images, or any file when allow_all_files is True."""
    ext = path.suffix.lower()
    if ext in IMAGE_MIME_TYPES:
        return IMAGE_MIME_TYPES[ext]
    if allow_all_files:
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"
    return None


def parse_relpath(raw_path: str, *, allow_empty: bool = False) -> list[str]:
    """Validate and split a URL-decoded relative POSIX path into safe path segments."""
    decoded = unquote(raw_path)
    if "\x00" in decoded or "\\" in decoded:
        raise PathValidationError("路径包含非法字符。", HTTPStatus.BAD_REQUEST)
    parts = [part for part in decoded.split("/") if part != ""]
    for part in parts:
        if part in (".", "..") or part.startswith("."):
            raise PathValidationError("禁止访问相对跳转或隐藏路径。", HTTPStatus.FORBIDDEN)
    if not parts and not allow_empty:
        raise PathValidationError("缺少图片路径。", HTTPStatus.BAD_REQUEST)
    return parts


def query_values(query: dict[str, list[str]], field: str, *, multiple: bool = False) -> list[str]:
    parts = (part for value in query.get(field, []) for part in (value.split(",") if multiple else [value]))
    return [part.strip() for part in parts if part.strip()]


def query_choice(query, field, choices, default=""):
    values = query_values(query, field)
    if field == "status":
        values = [value.lower() for value in values]
    if any(value not in choices for value in values) or len(set(values)) > 1:
        raise ValueError(f"{field} 的筛选值无效。")
    return values[0] if values else default


def parse_authored_filter(query, payload=None):
    # An explicit empty value selects unstarted images. Omission leaves the filter off.
    statuses = list(query.get("authored_status", ()))
    if payload is not None and "authored_status" in payload:
        statuses.append(payload["authored_status"])
    if any(status not in image_tags.AUTHORED_STATUSES for status in statuses):
        raise ValueError("authored_status 的筛选值无效。")
    authored = query_choice(query, "authored", ("0", "1"))
    if authored:
        statuses.append("authored" if authored == "1" else "")
    if len(set(statuses)) > 1:
        raise ValueError("出题状态筛选条件互相冲突。")
    return statuses[0] if statuses else None


def parse_image_filters(query, *, claimer_alias=False):
    def first(field):
        return next(iter(query_values(query, field)), "")

    tagged = query_choice(query, "tagged", ("0", "1"))
    registered = query_choice(query, "registered", ("0", "1"))
    registry_source = query_choice(query, "registry_source", image_tags.REGISTRY_SOURCES)
    filters = {
        "question_types": image_tags.normalize_codes(
            query_values(query, "question_type", multiple=True), image_tags.QUESTION_TYPES, "question_type"
        ),
        "difficulty": image_tags.normalize_codes(
            query_values(query, "difficulty", multiple=True), image_tags.DIFFICULTIES, "difficulty"
        ),
        "difficulty_tags": image_tags.normalize_codes(
            query_values(query, "difficulty_tag", multiple=True), image_tags.DIFFICULTY_TAGS, "difficulty_tag"
        ),
        "match": query_choice(query, "match", ("all", "any"), "all"),
        "tagged": tagged == "1" if tagged else None,
        "registered": registered == "1" if registered else None,
        "registry_source": registry_source or None,
        "status": query_choice(query, "status", ("all", "claimed", "unclaimed"), "all"),
        "authored_status": parse_authored_filter(query),
        "claimed_by": first("claimed_by") or (first("claimer") if claimer_alias else ""),
        "category": first("category"),
    }
    # Query strings are already URL-decoded by parse_qs.
    prefix = "/".join(parse_relpath(quote(first("prefix"), safe="/"), allow_empty=True))
    return filters, prefix


def path_matches_prefix(relpath: str | None, prefix: str) -> bool:
    return not prefix or bool(relpath and (relpath == prefix or relpath.startswith(prefix + "/")))


def resolve_existing_file(img_root: Path, raw_path: str, allow_all_files: bool = False) -> tuple[Path, str]:
    """Safely resolve an existing readable file inside img_root."""
    parts = parse_relpath(raw_path)
    candidate = img_root.joinpath(*parts)
    if not candidate.exists():
        raise PathValidationError("找不到指定的图片文件。", HTTPStatus.NOT_FOUND)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(img_root):
        raise PathValidationError("禁止访问图片目录之外的文件。", HTTPStatus.FORBIDDEN)
    if not resolved.is_file():
        raise PathValidationError("目标不是可下载文件。", HTTPStatus.NOT_FOUND)
    if guess_mime_type(resolved, allow_all_files) is None:
        raise PathValidationError("该文件类型不允许通过图片服务传输。", HTTPStatus.FORBIDDEN)
    return resolved, "/".join(parts)


def resolve_upload_target(img_root: Path, raw_path: str, allow_all_files: bool = False) -> tuple[Path, str]:
    """Safely resolve a target path inside img_root for uploading an image."""
    parts = parse_relpath(raw_path)
    if guess_mime_type(Path(parts[-1]), allow_all_files) is None:
        raise PathValidationError("仅允许上传支持的图像格式。", HTTPStatus.BAD_REQUEST)
    cursor = img_root
    for segment in parts[:-1]:
        cursor = cursor / segment
        if cursor.exists():
            if not cursor.resolve().is_relative_to(img_root) or not cursor.is_dir():
                raise PathValidationError("目标目录路径不合法。", HTTPStatus.FORBIDDEN)
    target = img_root.joinpath(*parts)
    if target.exists():
        if not target.resolve().is_relative_to(img_root):
            raise PathValidationError("禁止写入图片目录之外的位置。", HTTPStatus.FORBIDDEN)
        if target.is_dir():
            raise PathValidationError("目标路径已存在同名目录。", HTTPStatus.CONFLICT)
    return target, "/".join(parts)


def iter_images(img_root: Path, prefix: str = "", allow_all_files: bool = False) -> list[tuple[Path, str, os.stat_result, str]]:
    """List matching image files inside img_root sorted by relative POSIX path."""
    parts = parse_relpath(prefix, allow_empty=True) if prefix else []
    search_root = img_root.joinpath(*parts) if parts else img_root
    if not search_root.exists():
        return []
    resolved_search = search_root.resolve()
    if not resolved_search.is_relative_to(img_root) or not resolved_search.is_dir():
        return []

    results: list[tuple[Path, str, os.stat_result, str]] = []
    for dirpath, dirnames, filenames in os.walk(search_root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        current_dir = Path(dirpath)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = current_dir / name
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(img_root) or not resolved.is_file():
                continue
            mime = guess_mime_type(resolved, allow_all_files)
            if mime is None:
                continue
            rel = path.relative_to(img_root).as_posix()
            results.append((resolved, rel, resolved.stat(), mime))
    results.sort(key=lambda item: item[1])
    return results


def file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file in streaming chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def format_etag(st: os.stat_result) -> str:
    """Build a strong ETag from file byte size and nanosecond mtime."""
    return f'"{st.st_size:x}-{st.st_mtime_ns:x}"'


def build_file_metadata(
    path: Path,
    rel: str,
    st: os.stat_result,
    mime: str,
    *,
    include_sha256: bool = False,
) -> dict:
    """Create JSON-serializable metadata for a file in the image directory."""
    encoded_rel = "/".join(quote(part, safe="") for part in rel.split("/"))
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "path": rel,
        "name": Path(rel).name,
        "size": st.st_size,
        "mtime": mtime,
        "etag": format_etag(st),
        "mime_type": mime,
        "view_url": f"/img/{encoded_rel}",
        "download_url": f"/download/{encoded_rel}",
        "thumb_url": f"/api/thumb/{encoded_rel}",
    }
    if include_sha256:
        payload["sha256"] = file_sha256(path)
    return payload


def make_thumbnail(path: Path) -> bytes:
    if path.suffix.lower() in {".svg", ".heic", ".heif"}:
        return THUMB_PLACEHOLDER
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return THUMB_PLACEHOLDER

    try:
        Image.init()
        formats = tuple(name for name in THUMB_FORMATS if name in Image.OPEN)
        with Image.open(path, formats=formats) as image:
            if image.width * image.height > MAX_THUMB_PIXELS:
                return THUMB_PLACEHOLDER
            if image.format == "JPEG":
                image.draft("RGB", THUMB_SIZE)
            image.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            with ImageOps.exif_transpose(image) as oriented, Image.new("RGB", oriented.size, "#eef3f5") as canvas:
                if oriented.has_transparency_data:
                    with oriented.convert("RGBA") as rgba, rgba.getchannel("A") as alpha:
                        canvas.paste(rgba, mask=alpha)
                else:
                    canvas.paste(oriented)
                with BytesIO() as output:
                    canvas.save(output, format="JPEG", quality=80)
                    return output.getvalue()
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return THUMB_PLACEHOLDER


def parse_range_header(header_val: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single HTTP byte Range header; return None to serve full body, or raise RangeError for 416."""
    value = header_val.strip()
    if not value.lower().startswith("bytes="):
        return None
    spec = value[6:].strip()
    if "," in spec:
        return None
    if file_size == 0:
        raise RangeError("空文件无法满足字节范围请求。")
    match = re.fullmatch(r"(\d*)-(\d*)", spec)
    if not match or (not match.group(1) and not match.group(2)):
        raise RangeError("无效的 Range 请求格式。")
    start_str, end_str = match.groups()
    if not start_str:
        suffix = int(end_str)
        if suffix == 0:
            raise RangeError("无效的后缀范围。")
        start = max(0, file_size - suffix)
        return start, file_size - 1
    start = int(start_str)
    if start >= file_size:
        raise RangeError("请求起始字节超出文件长度。")
    end = min(int(end_str), file_size - 1) if end_str else file_size - 1
    if end < start:
        raise RangeError("请求结束字节小于起始字节。")
    return start, end


def etag_matches(if_none_match: str, etag: str) -> bool:
    """Check whether an If-None-Match header value matches the current ETag."""
    for candidate in if_none_match.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:].strip()
        if tag == etag:
            return True
    return False


def content_disposition_header(disposition: str, filename: str) -> str:
    """Build RFC 5987 Content-Disposition header with ASCII fallback and UTF-8 filename*."""
    ascii_name = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";"} else "_"
        for ch in filename
    ) or "image"
    utf8_name = quote(filename, safe="")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'


def redact_path_for_log(raw_path: str) -> str:
    """Redact token query parameters before printing request paths to logs."""
    parsed = urlsplit(raw_path)
    if not parsed.query:
        return raw_path
    redacted_query = re.sub(r"(?i)(^|&)token=[^&]*", r"\1token=***", parsed.query)
    return f"{parsed.path}?{redacted_query}"


def decode_header_text(raw: str) -> str:
    """Decode raw UTF-8 bytes that HTTP header parsing read as latin-1."""
    try:
        return raw.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return raw


def canonical_commons_title(value: str) -> str:
    """Normalize a Wikimedia Commons File URL or title for reliable matching."""
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        raw = unquote(urlsplit(raw).path).removeprefix("/wiki/")
    else:
        raw = unquote(raw)
    normalized = raw.replace("_", " ").strip()
    if normalized.lower().startswith("file:"):
        return "File:" + normalized[5:].strip()
    return normalized


def normalize_ledger_relpath(raw_file: str) -> str:
    """Strip leading img/ or images/ directory prefixes from ledger file paths."""
    rel = raw_file.replace("\\", "/").lstrip("/")
    for prefix in ("img/", "images/"):
        if rel.startswith(prefix):
            return rel[len(prefix):]
    return rel


def validate_claimer_name(value: str | None, *, required: bool = False) -> str:
    """Sanitize and validate a claimer identifier."""
    cleaned = (value or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ClaimError("领取人名称不能包含控制字符。", HTTPStatus.BAD_REQUEST)
    if len(cleaned) > 120:
        raise ClaimError("领取人名称过长（最多 120 个字符）。", HTTPStatus.BAD_REQUEST)
    if required and not cleaned:
        raise ClaimError("缺少领取人名称（claimer）。", HTTPStatus.BAD_REQUEST)
    return cleaned


class ClaimStore:
    """Thread-safe SQLite store syncing collection_queue.claimed_by with ./img downloads."""

    def __init__(self, db_path: Path, img_dir: Path, ledger_path: Path | None = None):
        self.db_path = db_path
        self.img_dir = img_dir
        self.ledger_path = ledger_path
        self._lock = threading.Lock()
        self._ledger_stamp: tuple[int, int] | None = None
        self._by_rel: dict[str, str] = {}
        self._by_page_id: dict[str, str] = {}
        self._title_to_rels: dict[str, list[str]] = {}
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _transaction(self, *, write: bool = True):
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def _ensure_schema(self) -> None:
        with self._transaction() as conn:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            has_queue = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='collection_queue'"
            ).fetchone()
            if not has_queue:
                conn.execute(
                    """
                    CREATE TABLE collection_queue (
                        id INTEGER PRIMARY KEY,
                        file_url TEXT NOT NULL UNIQUE CHECK (trim(file_url) <> ''),
                        category TEXT NOT NULL CHECK (trim(category) <> ''),
                        claimed_by TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS img_claims (
                    file_path TEXT PRIMARY KEY,
                    claimed_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            for table in ("collection_queue", "img_claims"):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                for field in ("claimed_by", *image_tags.ANNOTATION_FIELDS):
                    if field not in columns:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")

    def _load_ledger_maps(self) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
        if not self.ledger_path or not self.ledger_path.is_file():
            return {}, {}, {}
        st = self.ledger_path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        if self._ledger_stamp == stamp:
            return self._by_rel, self._by_page_id, self._title_to_rels

        by_rel: dict[str, str] = {}
        by_page_id: dict[str, str] = {}
        title_to_rels: dict[str, list[str]] = {}
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_ref = record.get("source_page") or record.get("title") or ""
            canon_title = canonical_commons_title(source_ref)
            if not canon_title:
                continue
            raw_file = record.get("file", "")
            if raw_file:
                rel = normalize_ledger_relpath(raw_file)
                by_rel[rel] = canon_title
                title_to_rels.setdefault(canon_title, [])
                if rel not in title_to_rels[canon_title]:
                    title_to_rels[canon_title].append(rel)
            if record.get("page_id") is not None:
                by_page_id[str(record["page_id"])] = canon_title
        self._by_rel = by_rel
        self._by_page_id = by_page_id
        self._title_to_rels = title_to_rels
        self._ledger_stamp = stamp
        return by_rel, by_page_id, title_to_rels

    def _queue_title_index(self, conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
        rows = conn.execute(f"SELECT {QUEUE_COLUMNS} FROM collection_queue ORDER BY id")
        return {canonical_commons_title(row["file_url"]): row for row in rows}

    def _match_queue_row(
        self,
        relpath: str,
        title_index: dict[str, sqlite3.Row],
        by_rel: dict[str, str],
        by_page_id: dict[str, str],
    ) -> sqlite3.Row | None:
        canon = by_rel.get(relpath)
        if canon and canon in title_index:
            return title_index[canon]
        name = Path(relpath).name
        if match := PAGE_ID_FILE_RE.match(name):
            canon = by_page_id.get(match.group(1))
            if canon and canon in title_index:
                return title_index[canon]
        direct_title = canonical_commons_title(f"File:{name}")
        return title_index.get(direct_title)

    def _find_local_file(self, file_url: str, title_to_rels: dict[str, list[str]]) -> str | None:
        canon = canonical_commons_title(file_url)
        for rel in title_to_rels.get(canon, []):
            rel_path = Path(rel)
            candidates = [rel_path, Path(rel_path.name)]
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                if rel_path.suffix.lower() != ext:
                    candidates.append(rel_path.with_suffix(ext))
                    candidates.append(Path(rel_path.name).with_suffix(ext))
            for cand in candidates:
                if (self.img_dir / cand).is_file():
                    return cand.as_posix()
        return None

    def _format_queue_item(self, row: sqlite3.Row, title_to_rels: dict[str, list[str]]) -> dict:
        claimed_by = (row["claimed_by"] or "").strip()
        local_file = self._find_local_file(row["file_url"], title_to_rels)
        item = {
            "source": "collection_queue",
            "id": row["id"],
            "file_url": row["file_url"],
            "category": row["category"],
            "claimed_by": claimed_by,
            "claimed": bool(claimed_by),
            "registered": True,
            "registry_source": "collection_queue",
            "local_file": local_file,
            **image_tags.read_annotations(row),
        }
        if local_file:
            encoded = "/".join(quote(part, safe="") for part in local_file.split("/"))
            item["download_url"] = f"/download/{encoded}"
            item["view_url"] = f"/img/{encoded}"
        return item

    def _resolve_target_in_tx(
        self,
        conn: sqlite3.Connection,
        *,
        queue_id: int | None = None,
        file_url: str | None = None,
        relpath: str | None = None,
        title_index: dict[str, sqlite3.Row] | None = None,
    ) -> tuple[str, dict]:
        by_rel, by_page_id, title_to_rels = self._load_ledger_maps()
        if queue_id is not None:
            row = conn.execute(
                f"SELECT {QUEUE_COLUMNS} FROM collection_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"找不到 id={queue_id} 的记录。")
            return "queue", self._format_queue_item(row, title_to_rels)

        if title_index is None:
            title_index = self._queue_title_index(conn)
        if file_url is not None:
            row = title_index.get(canonical_commons_title(file_url))
            if row is None:
                raise ClaimNotFoundError("在 collection_queue 中找不到对应的 file_url。")
            return "queue", self._format_queue_item(row, title_to_rels)

        if relpath is not None:
            row = self._match_queue_row(relpath, title_index, by_rel, by_page_id)
            if row is not None:
                return "queue", self._format_queue_item(row, title_to_rels)
            if not (self.img_dir / relpath).is_file():
                raise ClaimNotFoundError(f"找不到文件或队列记录：{relpath}")
            local_row = conn.execute(
                f"SELECT {LOCAL_CLAIM_COLUMNS} FROM img_claims WHERE file_path = ?",
                (relpath,),
            ).fetchone()
            claimed_by = (local_row["claimed_by"] or "").strip() if local_row else ""
            encoded = "/".join(quote(part, safe="") for part in relpath.split("/"))
            return "local", {
                "source": "img_claims",
                "path": relpath,
                "claimed_by": claimed_by,
                "claimed": bool(claimed_by),
                "registered": local_row is not None,
                "registry_source": "img_claims" if local_row is not None else "",
                "download_url": f"/download/{encoded}",
                "view_url": f"/img/{encoded}",
                **image_tags.read_annotations(local_row),
            }

        raise ClaimError("请提供 id、file_url 或 path 参数来定位图片记录。", HTTPStatus.BAD_REQUEST)

    def _write_claim_in_tx(self, conn: sqlite3.Connection, kind: str, target: dict, new_claimer: str) -> dict:
        if kind == "queue":
            conn.execute("UPDATE collection_queue SET claimed_by = ? WHERE id = ?", (new_claimer, target["id"]))
            updated = dict(target)
        else:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if not new_claimer:
                conn.execute(
                    "UPDATE img_claims SET claimed_by = '', updated_at = ? WHERE file_path = ?",
                    (now, target["path"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO img_claims (file_path, claimed_by, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        claimed_by = excluded.claimed_by,
                        updated_at = excluded.updated_at
                    """,
                    (target["path"], new_claimer, now),
                )
            updated = dict(target)
            if new_claimer:
                updated["registered"] = True
                updated["registry_source"] = "img_claims"
        updated["claimed_by"] = new_claimer
        updated["claimed"] = bool(new_claimer)
        return updated

    def get_claims_by_relpaths(self, relpaths: list[str]) -> dict[str, dict]:
        if not relpaths:
            return {}
        with self._transaction(write=False) as conn:
            by_rel, by_page_id, _ = self._load_ledger_maps()
            title_index = self._queue_title_index(conn)
            local_rows = {
                row["file_path"]: row
                for row in conn.execute(f"SELECT {LOCAL_CLAIM_COLUMNS} FROM img_claims")
            }
        mapping: dict[str, dict] = {}
        for rel in relpaths:
            row = self._match_queue_row(rel, title_index, by_rel, by_page_id)
            if row is not None:
                claimed_by = (row["claimed_by"] or "").strip()
                mapping[rel] = {
                    "claimed": bool(claimed_by),
                    "claimed_by": claimed_by,
                    "registered": True,
                    "registry_source": "collection_queue",
                    "queue_id": row["id"],
                    "file_url": row["file_url"],
                    "category": row["category"],
                    **image_tags.read_annotations(row),
                }
            else:
                local_row = local_rows.get(rel)
                claimed_by = (local_row["claimed_by"] or "").strip() if local_row else ""
                mapping[rel] = {
                    "claimed": bool(claimed_by),
                    "claimed_by": claimed_by,
                    "registered": local_row is not None,
                    "registry_source": "img_claims" if local_row is not None else "",
                    "queue_id": None,
                    "file_url": None,
                    "category": None,
                    **image_tags.read_annotations(local_row),
                }
        return mapping

    def update_tags(self, entries: list[tuple[dict, dict]]) -> list[dict]:
        seen = set()
        updated = []
        with self._transaction() as conn:
            title_index = self._queue_title_index(conn)
            for index, (selector, fields) in enumerate(entries):
                try:
                    kind, target = self._resolve_target_in_tx(conn, title_index=title_index, **selector)
                except ClaimError as exc:
                    raise ClaimError(str(exc), exc.status, details={"index": index}) from exc
                except ValueError as exc:
                    raise ClaimError(str(exc), HTTPStatus.BAD_REQUEST, details={"index": index}) from exc
                key = (kind, target["id"] if kind == "queue" else target["path"])
                if key in seen:
                    raise ClaimError("同一图片在批次中重复出现。", HTTPStatus.BAD_REQUEST, details={"index": index})
                seen.add(key)

                assignments = ", ".join(f"{field} = ?" for field in fields)
                if kind == "queue":
                    conn.execute(f"UPDATE collection_queue SET {assignments} WHERE id = ?", (*fields.values(), key[1]))
                else:
                    conn.execute(
                        "INSERT INTO img_claims (file_path, claimed_by, updated_at) VALUES (?, '', '') "
                        "ON CONFLICT(file_path) DO NOTHING",
                        (key[1],),
                    )
                    conn.execute(f"UPDATE img_claims SET {assignments} WHERE file_path = ?", (*fields.values(), key[1]))
                normalized = image_tags.read_annotations(dict.fromkeys(image_tags.ANNOTATION_FIELDS, "") | fields)
                target.update({field: normalized[field] for field in fields})
                target["registered"] = True
                target["registry_source"] = "collection_queue" if kind == "queue" else "img_claims"
                updated.append(target)
        return updated

    def acquire_for_download(self, relpath: str, requested_claimer: str = "") -> dict:
        claimer = validate_claimer_name(requested_claimer, required=False)
        with self._transaction() as conn:
            kind, target = self._resolve_target_in_tx(conn, relpath=relpath)
            current = target["claimed_by"]
            if current:
                if claimer and claimer == current:
                    result = dict(target)
                    result["newly_claimed"] = False
                    return result
                raise ClaimConflictError(
                    current,
                    f"该图片已被「{current}」领取，禁止重复领取或下载。",
                    details=target,
                )
            assigned = claimer or "downloaded"
            updated = self._write_claim_in_tx(conn, kind, target, assigned)
            updated["newly_claimed"] = True
            return updated

    def acquire_batch_for_download(
        self,
        relpaths: list[str],
        requested_claimer: str = "",
        *,
        only_unclaimed: bool = False,
        filters: dict | None = None,
        claim: bool = True,
    ) -> tuple[list[str], list[dict]]:
        claimer = validate_claimer_name(requested_claimer, required=False)
        with self._transaction(write=claim) as conn:
            title_index = self._queue_title_index(conn)
            selected: list[tuple[str, str, dict]] = []
            conflicts: list[dict] = []
            for rel in relpaths:
                kind, target = self._resolve_target_in_tx(conn, relpath=rel, title_index=title_index)
                if filters and not image_tags.matches(target, filters):
                    continue
                current = target["claimed_by"]
                if current and not (claimer and claimer == current):
                    if only_unclaimed:
                        continue
                    if claim:
                        conflicts.append({"path": rel, "claimed_by": current, "queue_id": target.get("id")})
                        continue
                selected.append((rel, kind, target))
            if conflicts:
                first = conflicts[0]
                raise ClaimConflictError(
                    first["claimed_by"],
                    f"存在 {len(conflicts)} 张已被他人领取的图片（如 {first['path']} 已被「{first['claimed_by']}」领取），可加 ?status=unclaimed 仅打包未领取图片。",
                    details={"conflicts": conflicts},
                )

            results = []
            written = set()
            for _, kind, target in selected:
                if claim and not target["claimed_by"]:
                    key = (kind, target["id"] if kind == "queue" else target["path"])
                    assigned = claimer or "downloaded"
                    if key not in written:
                        target = self._write_claim_in_tx(conn, kind, target, assigned)
                        target["newly_claimed"] = True
                        written.add(key)
                    else:
                        target = {**target, "claimed_by": assigned, "claimed": True, "newly_claimed": False}
                else:
                    target["newly_claimed"] = False
                results.append(target)
            return [rel for rel, _, _ in selected], results

    def claim_item(
        self,
        *,
        claimer: str,
        queue_id: int | None = None,
        file_url: str | None = None,
        relpath: str | None = None,
        claim_next: bool = False,
        category: str = "",
        filters: dict | None = None,
    ) -> dict:
        clean_claimer = validate_claimer_name(claimer, required=True)
        with self._transaction() as conn:
            if claim_next:
                _, _, title_to_rels = self._load_ledger_maps()
                rows = conn.execute(
                    f"SELECT {QUEUE_COLUMNS} FROM collection_queue "
                    "WHERE trim(claimed_by) = '' AND (? = '' OR category = ?) ORDER BY id",
                    (category, category),
                )
                row = next((row for row in rows if not filters or image_tags.matches(image_tags.read_annotations(row), filters)), None)
                if row is None:
                    raise ClaimNotFoundError("当前没有未领取的队列记录。")
                kind, target = "queue", self._format_queue_item(row, title_to_rels)
            else:
                kind, target = self._resolve_target_in_tx(conn, queue_id=queue_id, file_url=file_url, relpath=relpath)

            current = target["claimed_by"]
            if current and current != clean_claimer:
                raise ClaimConflictError(
                    current,
                    f"该记录已被「{current}」领取，不能重复领取。",
                    details=target,
                )
            if current == clean_claimer:
                result = dict(target)
                result["newly_claimed"] = False
                return result
            updated = self._write_claim_in_tx(conn, kind, target, clean_claimer)
            updated["newly_claimed"] = True
            return updated

    def update_claim(
        self,
        *,
        expected_claimer: str,
        new_claimed_by: str,
        queue_id: int | None = None,
        file_url: str | None = None,
        relpath: str | None = None,
        force: bool = False,
    ) -> dict:
        clean_expected = validate_claimer_name(expected_claimer, required=False)
        clean_new = validate_claimer_name(new_claimed_by, required=False)
        with self._transaction() as conn:
            kind, target = self._resolve_target_in_tx(conn, queue_id=queue_id, file_url=file_url, relpath=relpath)
            current = target["claimed_by"]
            if current and not force and clean_expected != current:
                raise ClaimConflictError(
                    current,
                    f"该记录当前归属于「{current}」，只有原领取人可修改或释放。",
                    details=target,
                )
            return self._write_claim_in_tx(conn, kind, target, clean_new)

    def batch_update_claims(
        self,
        entries: list[dict],
        *,
        skip_claimed: bool = False,
        force: bool = False,
    ) -> dict:
        updated_items: list[dict] = []
        skipped_items: list[dict] = []
        with self._transaction() as conn:
            for entry in entries:
                new_claimer = validate_claimer_name(entry.get("claimed_by"), required=False)
                expected = validate_claimer_name(entry.get("expected_claimer"), required=False)
                kind, target = self._resolve_target_in_tx(
                    conn,
                    queue_id=entry.get("id"),
                    file_url=entry.get("file_url"),
                    relpath=entry.get("path"),
                )
                current = target["claimed_by"]
                if current and not force and current != new_claimer and current != expected:
                    if skip_claimed:
                        skipped_items.append({"target": target, "claimed_by": current})
                        continue
                    raise ClaimConflictError(
                        current,
                        f"存在已被「{current}」领取的记录，批量更新已回滚。",
                        details=target,
                    )
                updated_items.append(self._write_claim_in_tx(conn, kind, target, new_claimer))
        return {"updated_count": len(updated_items), "skipped_count": len(skipped_items), "updated": updated_items, "skipped": skipped_items}

    def list_queue(
        self,
        *,
        status: str = "all",
        claimer: str = "",
        category: str = "",
        limit: int = 0,
        offset: int = 0,
        filters: dict | None = None,
        prefix: str = "",
    ) -> dict:
        filters = {"status": status, "claimed_by": claimer, "category": category, **(filters or {})}
        with self._lock, closing(self._connect()) as conn:
            _, _, title_to_rels = self._load_ledger_maps()
            all_rows = conn.execute(
                f"SELECT {QUEUE_COLUMNS} FROM collection_queue ORDER BY id"
            ).fetchall()

        total = len(all_rows)
        claimed_total = sum(1 for r in all_rows if (r["claimed_by"] or "").strip())
        unclaimed_total = total - claimed_total

        items: list[dict] = []
        for row in all_rows:
            item = self._format_queue_item(row, title_to_rels)
            if not image_tags.matches(item, filters):
                continue
            rel = item["local_file"]
            if path_matches_prefix(rel, prefix):
                items.append(item)

        matched_count = len(items)
        if offset > 0:
            items = items[offset:]
        if limit > 0:
            items = items[:limit]
        return {
            "total": total,
            "unclaimed_count": unclaimed_total,
            "claimed_count": claimed_total,
            "matched_count": matched_count,
            "items": items,
        }


def extract_request_token(headers, query: dict[str, list[str]], allow_query_token: bool) -> str | None:
    """Extract token from Authorization Bearer, X-Token, X-API-Key, or query param."""
    auth_header = headers.get("Authorization")
    if auth_header is not None:
        parts = auth_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return ""
        return parts[1].strip()
    x_token = headers.get("X-Token")
    if x_token is not None:
        return x_token.strip()
    x_api_key = headers.get("X-API-Key")
    if x_api_key is not None:
        return x_api_key.strip()
    if allow_query_token and "token" in query and query["token"]:
        return query["token"][0].strip()
    return None


def verify_token(provided: str | None, expected: str) -> bool:
    """Constant-time token comparison."""
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def save_stream_atomically(target: Path, stream_reader, expected_length: int, max_bytes: int) -> tuple[bool, int, str]:
    """Stream uploaded bytes into a temp file and atomically replace target."""
    if expected_length < 0:
        raise PathValidationError("无效的 Content-Length。", HTTPStatus.BAD_REQUEST)
    if expected_length > max_bytes:
        raise PathValidationError(f"上传文件超过上限 ({max_bytes // (1024 * 1024)} MB)。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    digest = hashlib.sha256()
    remaining = expected_length
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".upload-", suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while remaining > 0:
                chunk = stream_reader.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise PathValidationError("上传连接提前中断，数据不完整。", HTTPStatus.BAD_REQUEST)
                tmp.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return existed, expected_length, digest.hexdigest()


def save_bytes_atomically(target: Path, data: bytes) -> tuple[bool, str]:
    """Write an in-memory payload atomically to target and return (existed, sha256)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    digest = hashlib.sha256(data).hexdigest()
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".upload-", suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return existed, digest


def render_gallery_html(items: list[dict], directory_name: str, *, claim_enabled: bool = False, filters=None) -> str:
    """Render a lightweight, dependency-free HTML browser for authenticated visitors."""
    items_json = json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")
    filters_json = json.dumps(filters or {}, ensure_ascii=False).replace("<", "\\u003c")
    title_escaped = html.escape(directory_name)
    claim_flag = "true" if claim_enabled else "false"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_escaped} - 图片下载服务</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; margin: 24px auto; max-width: 1120px; padding: 0 16px; color: #1a242b; background: #f7f9fa; }}
    header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; }}
    h1 {{ font-size: 20px; margin: 0; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 16px; padding: 12px; background: #fff; border: 1px solid #dbe4e8; border-radius: 8px; }}
    .toolbar input {{ padding: 7px 10px; border: 1px solid #b9cad2; border-radius: 6px; font-size: 14px; }}
    .toolbar select, dialog select, dialog input, dialog textarea {{ padding: 6px 8px; border: 1px solid #b9cad2; border-radius: 6px; font: inherit; }}
    .toolbar label, dialog label {{ font-size: 14px; }}
    .tag-picker {{ display: flex; flex-wrap: wrap; gap: 8px 16px; }}
    .tag-picker label {{ display: flex; align-items: center; gap: 4px; }}
    .filter-tags {{ flex-basis: 100%; display: flex; flex-wrap: wrap; gap: 12px; }}
    fieldset {{ border: 1px solid #dbe4e8; border-radius: 6px; min-width: 0; }}
    dialog {{ width: min(580px, calc(100% - 48px)); padding: 18px; border: 1px solid #b9cad2; border-radius: 8px; }}
    dialog::backdrop {{ background: #1a242b66; }}
    dialog form {{ display: grid; gap: 10px; }}
    dialog h2 {{ margin: 0; font-size: 18px; }}
    dialog input, dialog textarea {{ display: block; box-sizing: border-box; width: 100%; }}
    .error {{ color: #9c3018; }}
    .notes {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .btn {{ display: inline-block; padding: 7px 12px; border-radius: 6px; background: #194353; color: #fff; text-decoration: none; font-size: 13px; border: 0; cursor: pointer; }}
    .btn.secondary {{ background: #e1eaee; color: #194353; }}
    .btn.warn {{ background: #b84a27; color: #fff; }}
    .meta {{ color: #526570; font-size: 13px; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .badge.free {{ background: #ddf3e4; color: #18643a; }}
    .badge.busy {{ background: #fde8e1; color: #9c3018; }}
    .badge.authored-unstarted {{ background: #eef3f5; color: #526570; }}
    .badge.authored-draft {{ background: #fff3d6; color: #8a5a00; }}
    .badge.authored-done {{ background: #dcebfa; color: #144d82; }}
    .badge.authored-discarded {{ background: #f1e6f4; color: #6c327c; }}
    .badge.reg-ok {{ background: #e1f5ee; color: #126149; }}
    .badge.reg-none {{ background: #f2e6e4; color: #8c2d19; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }}
    .card {{ background: #fff; border: 1px solid #dbe4e8; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }}
    .thumb {{ height: 150px; background: #eef3f5; display: flex; align-items: center; justify-content: center; overflow: hidden; color: #526570; font-size: 13px; }}
    .thumb img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
    .info {{ padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }}
    .path {{ font-weight: 600; word-break: break-all; }}
    .row-actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }}
    .empty {{ background: #fff; border: 1px dashed #b9cad2; border-radius: 8px; padding: 36px; text-align: center; color: #526570; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>目录：{title_escaped}/</h1>
      <div class="meta" id="summary"></div>
    </div>
    <div class="actions">
      <a class="btn" id="archiveLink">打包下载 (.zip)</a>
      <a class="btn secondary" id="queueLink" href="/api/queue">队列状态 JSON</a>
      <a class="btn secondary" id="jsonLink" href="/api/images">图片清单 JSON</a>
      <a class="btn secondary" href="/docs" referrerpolicy="no-referrer">Swagger UI</a>
    </div>
  </header>
  <form class="toolbar" id="filters">
    <label>当前领取人 <input id="claimerInput" placeholder="输入姓名"></label>
    <label>已有领取人 <input name="claimed_by"></label>
    <label>领取状态 <select name="status"><option value="all">全部</option><option value="unclaimed">未领取</option><option value="claimed">已领取</option></select></label>
    <label>出题状态 <select name="authored_status"><option value="__all__">全部</option><option value="">未出题</option><option value="draft">出题中</option><option value="authored">已出题</option><option value="discarded">已淘汰</option></select></label>
    <label>图片类别 <input name="category"></label>
    <label>目录前缀 <input name="prefix"></label>
    <label>登记状态 <select name="registered"><option value="">全部</option><option value="1">已入库</option><option value="0">未登记</option></select></label>
    <label>登记表 <select name="registry_source"><option value="">全部</option><option value="collection_queue">队列 collection_queue</option><option value="img_claims">本地 img_claims</option><option value="none">未登记</option></select></label>
    <label>标注状态 <select name="tagged"><option value="">全部</option><option value="1">已打标</option><option value="0">待标注</option></select></label>
    <label>组内匹配 <select name="match"><option value="all">全部所选标签</option><option value="any">任一所选标签</option></select></label>
    <button class="btn" type="submit">筛选</button>
    <a class="btn secondary" id="clearFilters">重置</a>
    <div class="filter-tags" id="filterTags"></div>
  </form>
  <p id="galleryError" class="error" role="alert" hidden></p>
  <main id="content"></main>
  <dialog id="tagEditor" aria-labelledby="editTitle">
    <form id="editTags">
      <h2 id="editTitle">编辑标签与出题状态</h2>
      <div class="path" id="editPath"></div>
      <fieldset><legend>候选题型</legend><div class="tag-picker" id="editQuestionTypes"></div></fieldset>
      <label>综合难度 <select name="difficulty"></select></label>
      <fieldset><legend>视觉难点</legend><div class="tag-picker" id="editDifficultyTags"></div></fieldset>
      <label>出题状态 <select name="authored_status"></select></label>
      <label>题号/材料路径 <input name="authored_ref" placeholder="如 ZB-001 | outputs/题目材料"></label>
      <label>出题备注 <textarea name="tag_notes" rows="3"></textarea></label>
      <div class="error" id="editError" role="alert" hidden></div>
      <div class="actions"><button class="btn" type="submit">保存</button><button class="btn secondary" id="closeEditor" type="button">取消</button></div>
    </form>
  </dialog>
  <script>
    let items = {items_json};
    const currentFilters = {filters_json};
    const claimEnabled = {claim_flag};
    const token = new URLSearchParams(window.location.search).get("token") || "";
    const withToken = (url, extra = {{}}) => {{
      const params = new URLSearchParams();
      if (token) params.set("token", token);
      for (const [k, v] of Object.entries(extra)) {{
        if (v !== undefined && v !== null && (String(v) !== "" || k === "authored_status")) params.set(k, String(v));
      }}
      const qs = params.toString();
      return qs ? url + (url.includes("?") ? "&" : "?") + qs : url;
    }};
    const fmtSize = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(2) + " MB";

    const filterForm = document.getElementById("filters");
    const filterFields = ["claimed_by", "status", "category", "prefix", "registered", "registry_source", "tagged", "match"];
    const filterTags = [
      ["question_types", "question_type", "候选题型"],
      ["difficulty", "difficulty", "综合难度"],
      ["difficulty_tags", "difficulty_tag", "视觉难点"],
    ];
    const claimerInput = document.getElementById("claimerInput");
    const galleryError = document.getElementById("galleryError");
    const editor = document.getElementById("tagEditor");
    const editForm = document.getElementById("editTags");
    const editError = document.getElementById("editError");
    const saveButton = editForm.querySelector("button[type=submit]");
    let tagSchema;
    let editingItem;

    for (const name of filterFields) {{
      if (name in currentFilters) filterForm.elements[name].value = currentFilters[name];
    }}
    filterForm.elements.authored_status.value =
      currentFilters.authored_status === null || currentFilters.authored_status === undefined
        ? "__all__"
        : currentFilters.authored_status;
    document.getElementById("clearFilters").href = withToken("/");
    filterForm.addEventListener("submit", (event) => {{
      event.preventDefault();
      const values = new FormData(filterForm);
      const params = Object.fromEntries(filterFields.map((name) => [name, values.get(name)]));
      const rawAuthored = values.get("authored_status");
      params.authored_status = rawAuthored === "__all__" ? null : rawAuthored;
      for (const [, name] of filterTags) {{
        params[name] = tagSchema ? values.getAll(name) : currentFilters[name];
      }}
      window.location.assign(withToken("/", params));
    }});

    claimerInput.value = localStorage.getItem("img_server_claimer") || "";
    claimerInput.addEventListener("input", () => {{
      localStorage.setItem("img_server_claimer", claimerInput.value.trim());
      updateGlobalLinks();
    }});

    function updateGlobalLinks() {{
      const claimer = claimerInput.value.trim();
      const archiveFilters = {{ ...currentFilters, claimer }};
      if (claimEnabled && !archiveFilters.claimed_by && (!archiveFilters.status || archiveFilters.status === "all")) {{
        archiveFilters.status = "unclaimed";
      }}
      const archive = document.getElementById("archiveLink");
      archive.href = withToken("/api/archive", archiveFilters);
      archive.textContent = archiveFilters.status === "unclaimed" ? "打包下载未领取 (.zip)" : "打包下载 (.zip)";
      document.getElementById("queueLink").href = withToken("/api/queue", currentFilters);
      document.getElementById("jsonLink").href = withToken("/api/images", currentFilters);
    }}

    async function callApi(method, url, body) {{
      const resp = await fetch(url, {{
        method,
        headers: body ? {{ "Content-Type": "application/json" }} : undefined,
        body: body ? JSON.stringify(body) : undefined,
      }});
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.message || resp.statusText);
      return data;
    }}

    function showError(node, message) {{
      node.textContent = message;
      node.hidden = !message;
    }}

    async function refreshItems() {{
      try {{
        const data = await callApi("GET", withToken("/api/images", currentFilters));
        items = data.images;
        showError(galleryError, "");
        render();
      }} catch (err) {{
        showError(galleryError, err.message);
        render();
      }}
    }}

    function fillPicker(container, options, name, selected) {{
      container.replaceChildren();
      for (const {{ code, label, description }} of options) {{
        const item = document.createElement("label");
        item.title = description;
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = name;
        input.value = code;
        input.checked = selected.includes(code);
        item.append(input, label);
        container.appendChild(item);
      }}
    }}

    function initTagFilters() {{
      const container = document.getElementById("filterTags");
      for (const [field, name, title] of filterTags) {{
        const fieldset = document.createElement("fieldset");
        const legend = document.createElement("legend");
        legend.textContent = title;
        const options = document.createElement("div");
        options.className = "tag-picker";
        fillPicker(options, tagSchema[field], name, currentFilters[name] || []);
        fieldset.append(legend, options);
        container.appendChild(fieldset);
      }}
      const select = editForm.elements.difficulty;
      select.add(new Option("未评级", ""));
      for (const {{ code, label, description }} of tagSchema.difficulty) {{
        const option = new Option(label, code);
        option.title = description;
        select.add(option);
      }}
      const authoredSelect = editForm.elements.authored_status;
      authoredSelect.replaceChildren();
      const filterAuthored = filterForm.elements.authored_status;
      for (const {{ code, label, description }} of tagSchema.authored_status || []) {{
        const option = new Option(label, code);
        option.title = description;
        authoredSelect.add(option);
        const filterOpt = Array.from(filterAuthored.options).find((opt) => opt.value === code);
        if (filterOpt) {{
          filterOpt.textContent = label;
          filterOpt.title = description;
        }}
      }}
    }}

    function editTags(item) {{
      editingItem = item;
      document.getElementById("editPath").textContent = item.path;
      fillPicker(document.getElementById("editQuestionTypes"), tagSchema.question_types, "question_types", item.question_types);
      fillPicker(document.getElementById("editDifficultyTags"), tagSchema.difficulty_tags, "difficulty_tags", item.difficulty_tags);
      editForm.elements.difficulty.value = item.difficulty;
      editForm.elements.authored_status.value = item.authored_status || "";
      editForm.elements.authored_ref.value = item.authored_ref || "";
      editForm.elements.tag_notes.value = item.tag_notes;
      showError(editError, "");
      editor.showModal();
    }}
    document.getElementById("closeEditor").onclick = () => editor.close();
    editor.addEventListener("cancel", (event) => {{
      if (saveButton.disabled) event.preventDefault();
    }});
    editForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      saveButton.disabled = true;
      const cancelButton = document.getElementById("closeEditor");
      cancelButton.disabled = true;
      const item = editingItem;
      const values = new FormData(editForm);
      const annotation = {{
        question_types: values.getAll("question_types").sort(),
        difficulty: values.get("difficulty"),
        difficulty_tags: values.getAll("difficulty_tags").sort(),
        authored_status: values.get("authored_status"),
        authored_ref: values.get("authored_ref"),
        tag_notes: values.get("tag_notes"),
      }};
      const changes = Object.fromEntries(Object.entries(annotation).filter(
        ([field, value]) => JSON.stringify(value) !== JSON.stringify(item[field])
      ));
      try {{
        if (Object.keys(changes).length) {{
          const selector = item.queue_id == null ? {{ path: item.path }} : {{ id: item.queue_id }};
          const updated = await callApi("PATCH", withToken("/api/tags"), {{ ...selector, ...changes }});
          for (const field of Object.keys(annotation)) item[field] = updated[field];
          await refreshItems();
        }}
        editor.close();
      }} catch (err) {{
        showError(editError, err.message);
      }} finally {{
        saveButton.disabled = false;
        cancelButton.disabled = false;
      }}
    }});

    function render() {{
      updateGlobalLinks();
      const totalBytes = items.reduce((acc, item) => acc + item.size, 0);
      const claimedCount = items.filter((item) => item.claimed).length;
      document.getElementById("summary").textContent = claimEnabled
        ? `共 ${{items.length}} 张图片（未领取 ${{items.length - claimedCount}} / 已领取 ${{claimedCount}}），总大小 ${{fmtSize(totalBytes)}}`
        : `共 ${{items.length}} 张图片，总大小 ${{fmtSize(totalBytes)}}`;

      const content = document.getElementById("content");
      content.replaceChildren();
      if (!items.length) {{
        content.innerHTML = '<div class="empty">当前筛选条件下暂无图片。</div>';
        return;
      }}
      const grid = document.createElement("div");
      grid.className = "grid";
      for (const item of items) {{
        const card = document.createElement("div");
        card.className = "card";
        const thumb = document.createElement("div");
        thumb.className = "thumb";
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = item.name;
        img.src = withToken(item.thumb_url);
        thumb.appendChild(img);

        const info = document.createElement("div");
        info.className = "info";
        const pathEl = document.createElement("div");
        pathEl.className = "path";
        pathEl.textContent = item.path;
        const sizeEl = document.createElement("div");
        sizeEl.className = "meta";
        sizeEl.textContent = `${{fmtSize(item.size)}} · ${{item.mime_type}}`;
        info.append(pathEl, sizeEl);

        for (const [field, , title] of filterTags) {{
          const values = [].concat(item[field] || []);
          if (!values.length) continue;
          const tags = document.createElement("div");
          const options = tagSchema?.[field] || [];
          const labels = values.map((code) => options.find((option) => option.code === code)?.label || code);
          tags.textContent = `${{title}} · ${{labels.join("、")}}`;
          info.appendChild(tags);
        }}
        if (item.tag_notes) {{
          const notes = document.createElement("div");
          notes.className = "meta notes";
          notes.textContent = item.tag_notes;
          info.appendChild(notes);
        }}

        if (claimEnabled) {{
          const badges = document.createElement("div");
          badges.className = "badges";
          const claimBadge = document.createElement("span");
          claimBadge.className = "badge " + (item.claimed ? "busy" : "free");
          claimBadge.textContent = item.claimed ? `已领取：${{item.claimed_by}}` : "未领取";
          badges.appendChild(claimBadge);

          const authoredCode = item.authored_status || "";
          const authoredMap = {{ "": ["未出题", "authored-unstarted"], draft: ["出题中", "authored-draft"], authored: ["已出题", "authored-done"], discarded: ["已淘汰", "authored-discarded"] }};
          const [fallbackLabel, authoredCls] = authoredMap[authoredCode] || [authoredCode, "authored-unstarted"];
          const authoredLabel = tagSchema?.authored_status?.find((opt) => opt.code === authoredCode)?.label || fallbackLabel;
          const authoredBadge = document.createElement("span");
          authoredBadge.className = `badge ${{authoredCls}}`;
          authoredBadge.textContent = authoredLabel;
          badges.appendChild(authoredBadge);

          const regBadge = document.createElement("span");
          regBadge.className = "badge " + (item.registered ? "reg-ok" : "reg-none");
          regBadge.textContent = item.registered ? `已入库 · ${{item.registry_source}}` : "未登记";
          badges.appendChild(regBadge);
          info.appendChild(badges);

          if (item.authored_ref) {{
            const refEl = document.createElement("div");
            refEl.className = "meta notes";
            refEl.textContent = `出题引用：${{item.authored_ref}}`;
            info.appendChild(refEl);
          }}
        }}

        const rowActions = document.createElement("div");
        rowActions.className = "row-actions";
        const dl = document.createElement("button");
        dl.className = "btn";
        dl.textContent = claimEnabled && !item.claimed ? "领取并下载原图" : "下载原图";
        dl.onclick = async () => {{
          const claimer = claimerInput.value.trim();
          window.location.href = withToken(item.download_url, {{ claimer }});
          if (claimEnabled) setTimeout(refreshItems, 800);
        }};
        rowActions.appendChild(dl);

        if (claimEnabled && tagSchema) {{
          const edit = document.createElement("button");
          edit.className = "btn secondary";
          edit.textContent = "编辑标签";
          edit.onclick = () => editTags(item);
          rowActions.appendChild(edit);
        }}

        if (claimEnabled && item.claimed) {{
          const mod = document.createElement("button");
          mod.className = "btn secondary";
          mod.textContent = "修改/转交";
          mod.onclick = async () => {{
            const nextName = prompt(`当前领取人：${{item.claimed_by}}\n请输入新的领取人（留空则释放）：`, item.claimed_by);
            if (nextName === null) return;
            try {{
              const selector = item.queue_id == null ? {{ path: item.path }} : {{ id: item.queue_id }};
              await callApi("PATCH", withToken("/api/claims"), {{
                ...selector,
                claimer: claimerInput.value.trim() || item.claimed_by,
                new_claimed_by: nextName.trim(),
              }});
              await refreshItems();
            }} catch (err) {{
              alert(err.message);
            }}
          }};
          rowActions.appendChild(mod);
        }}
        info.appendChild(rowActions);
        card.append(thumb, info);
        grid.appendChild(card);
      }}
      content.appendChild(grid);
    }}
    updateGlobalLinks();
    callApi("GET", withToken("/api/tags/schema")).then((schema) => {{
      tagSchema = schema;
      initTagFilters();
    }}).catch((err) => showError(galleryError, err.message)).finally(render);
  </script>
</body>
</html>
"""


class ImageHTTPServer(ThreadingHTTPServer):
    """Multi-threaded HTTP server holding immutable ServerConfig and optional SQLite ClaimStore."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], RequestHandlerClass, config: ServerConfig):
        self.config = config
        self.openapi = openapi_document(allow_query_token=config.allow_query_token)
        self.thumbnail_slots = threading.BoundedSemaphore(2)
        self.claim_store = (
            ClaimStore(config.db_path, config.img_dir, config.ledger_path)
            if config.db_path is not None
            else None
        )
        super().__init__(server_address, RequestHandlerClass)


class ImageHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler providing token-gated image listing, streaming download, archive, and optional upload."""

    protocol_version = "HTTP/1.1"
    server_version = "CommonsImgServer/1.0"

    @property
    def cfg(self) -> ServerConfig:
        return self.server.config

    def log_message(self, format: str, *args) -> None:
        safe_args = tuple(redact_path_for_log(a) if isinstance(a, str) else a for a in args)
        super().log_message(format, *safe_args)

    def _add_common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.cfg.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cfg.cors_origin)
            self.send_header(
                "Access-Control-Expose-Headers",
                "Content-Disposition, Content-Range, Accept-Ranges, ETag, X-File-SHA256, X-Claimed-By",
            )
            self.send_header("Vary", "Origin")

    def _send_json(self, status: int, payload: dict, *, send_body: bool = True, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._add_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if send_body and self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(self, status: int, content: str, *, send_body: bool = True) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self._add_common_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body and self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, status: int, error_code: str, message: str, *, extra_headers: dict[str, str] | None = None) -> None:
        headers = dict(extra_headers or {})
        if self.headers and (
            self.headers.get("Content-Length") is not None
            or self.headers.get("Transfer-Encoding") is not None
        ):
            headers["Connection"] = "close"
        self._send_json(status, {"error": error_code, "message": message}, extra_headers=headers)

    def handle_expect_100(self) -> bool:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._require_auth(query):
            return False
        is_upload = (self.command == "PUT" and parsed.path.startswith("/img/")) or (
            self.command == "POST" and parsed.path == "/api/upload"
        )
        if is_upload:
            if not self.cfg.allow_upload:
                self._send_error_json(HTTPStatus.FORBIDDEN, "upload_disabled", "服务端未开启上传功能，请使用 --allow-upload 启动。")
                return False
            if self._parse_content_length() is None:
                return False
        return super().handle_expect_100()

    def _require_auth(self, query: dict[str, list[str]]) -> bool:
        token = extract_request_token(self.headers, query, self.cfg.allow_query_token)
        if verify_token(token, self.cfg.token):
            return True
        self._send_error_json(
            HTTPStatus.UNAUTHORIZED,
            "unauthorized",
            "需要携带有效的 HTTP Token（Authorization: Bearer <token>、X-Token 请求头或 ?token=<token> 参数）。",
            extra_headers={"WWW-Authenticate": 'Bearer realm="img-server"', "Cache-Control": "no-store"},
        )
        return False

    def _stream_file_handle(self, handle, length: int) -> None:
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            self.wfile.write(chunk)
            remaining -= len(chunk)

    def _extract_claimer(self, query: dict[str, list[str]], payload: dict | None = None) -> str:
        if payload is not None and payload.get("claimer") is not None:
            return str(payload["claimer"]).strip()
        header_val = self.headers.get("X-Claimer")
        if header_val is not None:
            return decode_header_text(header_val).strip()
        if "claimer" in query and query["claimer"]:
            return query["claimer"][0].strip()
        return ""

    def _require_claim_store(self) -> ClaimStore | None:
        store = self.server.claim_store
        if store is None:
            self._send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "db_disabled",
                "未启用 SQLite 领取数据库，无法操作领取状态。",
            )
            return None
        return store

    def _read_json_body(self) -> dict | None:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return {}
        try:
            length = int(raw_len)
            if length < 0:
                raise ValueError
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length", "无效的 Content-Length。")
            return None
        if length > MAX_JSON_BODY_BYTES:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", "JSON 请求体过大。")
            return None
        if length == 0:
            return {}
        raw_bytes = self.rfile.read(length)
        if len(raw_bytes) != length:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "incomplete_body", "请求体不完整。")
            return None
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json", "请求体必须是合法的 JSON 对象。")
            return None
        if not isinstance(parsed, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json", "JSON 顶层必须是对象。")
            return None
        return parsed

    def _parse_claim_selector(self, query: dict[str, list[str]], payload: dict) -> tuple[int | None, str | None, str | None]:
        raw_id = payload.get("id") if "id" in payload else (query.get("id", [None])[0])
        queue_id: int | None = None
        if raw_id is not None and str(raw_id).strip() != "":
            try:
                queue_id = int(raw_id)
            except ValueError as exc:
                raise ClaimError("id 必须是整数。", HTTPStatus.BAD_REQUEST) from exc

        raw_url = payload.get("file_url") if "file_url" in payload else (query.get("file_url", [None])[0])
        file_url = str(raw_url).strip() if raw_url is not None and str(raw_url).strip() else None

        raw_path = payload.get("path") if "path" in payload else (query.get("path", [None])[0])
        relpath: str | None = None
        if raw_path is not None and str(raw_path).strip():
            parts = parse_relpath(str(raw_path).strip())
            relpath = "/".join(parts)

        return queue_id, file_url, relpath

    def _handle_claim_error(self, exc: ClaimError) -> None:
        payload = {"error": "already_claimed" if exc.status == HTTPStatus.CONFLICT else "claim_error", "message": str(exc)}
        if exc.claimed_by:
            payload["claimed_by"] = exc.claimed_by
        if exc.details:
            payload.update(exc.details)
        self._send_json(exc.status, payload)

    def _parse_tag_update(self, entry: dict) -> tuple[dict, dict]:
        selector_names = {"id", "file_url", "path"}
        if not isinstance(entry, dict) or entry.keys() - selector_names - set(image_tags.ANNOTATION_FIELDS):
            raise ValueError("标注记录必须是对象，且只能包含选择器、标签和出题状态字段。")
        selectors = entry.keys() & selector_names
        if len(selectors) != 1:
            raise ValueError("id、file_url、path 必须三选一。")
        field, = selectors
        value = entry[field]
        if field == "id":
            if type(value) is not int or not -(2**63) <= value < 2**63:
                raise ValueError("id 必须是整数。")
            selector = {"queue_id": value}
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} 必须是非空字符串。")
            if field == "path":
                # JSON callers submit the relative path returned by the listing.
                # Also accept URL-encoded spellings when there is no literal match.
                try:
                    _, relpath = resolve_existing_file(self.cfg.img_dir, quote(value, safe="/"), self.cfg.allow_all_files)
                except PathValidationError as exc:
                    if exc.status != HTTPStatus.NOT_FOUND or "%" not in value:
                        raise
                    _, relpath = resolve_existing_file(self.cfg.img_dir, value, self.cfg.allow_all_files)
                selector = {"relpath": relpath}
            else:
                selector = {"file_url": value.strip()}
        return selector, image_tags.normalize_updates(entry)

    def _handle_tags_write(self, query, *, batch=False) -> None:
        store = self._require_claim_store()
        if store is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return
        if query.keys() & {"id", "file_url", "path"}:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_tags", "请在 JSON 请求体中提供选择器。")
            return
        entries = payload.get("items") if batch else [payload]
        if not isinstance(entries, list) or not entries:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_tags", "items 必须是非空数组。")
            return

        validated = []
        for index, entry in enumerate(entries):
            try:
                validated.append(self._parse_tag_update(entry))
            except ValueError as exc:
                error = {"error": "invalid_tags", "message": str(exc)}
                if batch:
                    error["index"] = index
                status = exc.status if isinstance(exc, PathValidationError) else HTTPStatus.BAD_REQUEST
                self._send_json(status, error)
                return
        try:
            items = store.update_tags(validated)
        except ClaimError as exc:
            error = {"error": "invalid_tags", "message": str(exc)}
            if batch:
                error.update(exc.details)
            self._send_json(exc.status, error)
            return
        self._send_json(HTTPStatus.OK, {"updated_count": len(items), "items": items} if batch else items[0])

    def _collect_filtered_images(
        self,
        filters: dict,
        prefix: str,
        *,
        include_sha256: bool = False,
    ) -> list[dict]:
        entries = iter_images(
            self.cfg.img_dir, prefix=quote(prefix, safe="/"), allow_all_files=self.cfg.allow_all_files
        )
        store = self.server.claim_store
        claims = store.get_claims_by_relpaths([rel for _, rel, _, _ in entries]) if store is not None else {}
        empty_claim = {**image_tags.read_annotations(), "registered": False, "registry_source": ""}
        items = []
        for path, rel, st, mime in entries:
            claim_info = claims.get(rel) or empty_claim
            if not image_tags.matches(claim_info, filters):
                continue
            meta = build_file_metadata(path, rel, st, mime, include_sha256=include_sha256)
            meta.update(claim_info)
            items.append(meta)
        return items

    def _handle_list(self, parsed_path: str, query: dict[str, list[str]], *, send_body: bool) -> None:
        include_sha256 = query.get("checksum", [""])[0].lower() in {"1", "true", "yes"}
        try:
            filters, prefix = parse_image_filters(query, claimer_alias=True)
            items = self._collect_filtered_images(filters, prefix, include_sha256=include_sha256)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_filter", str(exc))
            return

        store = self.server.claim_store
        accept = self.headers.get("Accept", "")
        fmt = query.get("format", [""])[0].lower()
        if parsed_path == "/" and fmt != "json" and ("text/html" in accept or fmt == "html"):
            gallery_filters = {
                "question_type": filters["question_types"], "difficulty": filters["difficulty"],
                "difficulty_tag": filters["difficulty_tags"], "match": filters["match"],
                "status": filters["status"], "claimed_by": filters["claimed_by"],
                "authored_status": filters["authored_status"],
                "category": filters["category"], "prefix": prefix,
                "registered": "" if filters["registered"] is None else str(int(filters["registered"])),
                "registry_source": filters["registry_source"] or "",
                "tagged": "" if filters["tagged"] is None else str(int(filters["tagged"])),
            }
            self._send_html(
                HTTPStatus.OK,
                render_gallery_html(items, self.cfg.img_dir.name, claim_enabled=(store is not None), filters=gallery_filters),
                send_body=send_body,
            )
            return
        registered_count = sum(1 for item in items if item.get("registered"))
        self._send_json(
            HTTPStatus.OK,
            {
                "directory": self.cfg.img_dir.name,
                "count": len(items),
                "total_bytes": sum(item["size"] for item in items),
                "claim_tracking": store is not None,
                "registered_count": registered_count,
                "unregistered_count": len(items) - registered_count,
                "images": items,
            },
            send_body=send_body,
        )

    def _handle_file_download(self, raw_relpath: str, query: dict[str, list[str]], *, force_attachment: bool, send_body: bool) -> None:
        try:
            resolved, rel = resolve_existing_file(self.cfg.img_dir, raw_relpath, self.cfg.allow_all_files)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "file_error", str(exc))
            return

        st = resolved.stat()
        mime = guess_mime_type(resolved, self.cfg.allow_all_files) or "application/octet-stream"
        etag = format_etag(st)
        last_modified = formatdate(st.st_mtime, usegmt=True)

        byte_range: tuple[int, int] | None = None
        if range_header := self.headers.get("Range"):
            try:
                byte_range = parse_range_header(range_header, st.st_size)
            except RangeError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self._add_common_headers()
                self.send_header("Content-Range", f"bytes */{st.st_size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        claim_info: dict | None = None
        store = self.server.claim_store
        if store is not None:
            try:
                requested_claimer = self._extract_claimer(query)
                if send_body:
                    claim_info = store.acquire_for_download(rel, requested_claimer)
                else:
                    claim_info = store.get_claims_by_relpaths([rel]).get(rel)
            except ClaimError as exc:
                self._handle_claim_error(exc)
                return

        if_none_match = self.headers.get("If-None-Match")
        if if_none_match and etag_matches(if_none_match, etag):
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self._add_common_headers()
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            if claim_info and claim_info.get("claimed_by"):
                self.send_header("X-Claimed-By", quote(claim_info["claimed_by"], safe=""))
            self.end_headers()
            return

        if not if_none_match and (if_mod_since := self.headers.get("If-Modified-Since")):
            try:
                since_dt = parsedate_to_datetime(if_mod_since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
                if int(st.st_mtime) <= int(since_dt.timestamp()):
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self._add_common_headers()
                    self.send_header("ETag", etag)
                    self.send_header("Last-Modified", last_modified)
                    if claim_info and claim_info.get("claimed_by"):
                        self.send_header("X-Claimed-By", quote(claim_info["claimed_by"], safe=""))
                    self.end_headers()
                    return
            except (TypeError, ValueError):
                pass

        dl_param = (query.get("download", [""])[0] or query.get("attachment", [""])[0]).lower()
        as_attachment = force_attachment or dl_param in {"1", "true", "yes"} or resolved.suffix.lower() == ".svg"
        disposition = "attachment" if as_attachment else "inline"

        if byte_range is not None:
            start, end = byte_range
            content_length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{st.st_size}")
        else:
            start = 0
            content_length = st.st_size
            self.send_response(HTTPStatus.OK)

        self._add_common_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified)
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
        self.send_header("Content-Disposition", content_disposition_header(disposition, Path(rel).name))
        if claim_info and claim_info.get("claimed_by"):
            self.send_header("X-Claimed-By", quote(claim_info["claimed_by"], safe=""))
        if resolved.suffix.lower() == ".svg":
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        if query.get("sha256", [""])[0].lower() in {"1", "true", "yes"}:
            self.send_header("X-File-SHA256", file_sha256(resolved))
        self.end_headers()

        if send_body and content_length > 0:
            with resolved.open("rb") as handle:
                if start:
                    handle.seek(start)
                self._stream_file_handle(handle, content_length)

    def _handle_meta(self, raw_relpath: str, *, send_body: bool) -> None:
        try:
            resolved, rel = resolve_existing_file(self.cfg.img_dir, raw_relpath, self.cfg.allow_all_files)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "file_error", str(exc))
            return
        mime = guess_mime_type(resolved, self.cfg.allow_all_files) or "application/octet-stream"
        meta = build_file_metadata(resolved, rel, resolved.stat(), mime, include_sha256=True)
        store = self.server.claim_store
        empty_claim = {**image_tags.read_annotations(), "registered": False, "registry_source": ""}
        meta.update(store.get_claims_by_relpaths([rel])[rel] if store is not None else empty_claim)
        self._send_json(HTTPStatus.OK, meta, send_body=send_body)

    def _handle_thumbnail(self, raw_relpath: str, query: dict[str, list[str]], *, send_body: bool) -> None:
        if query.keys() - {"token"}:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_thumbnail_query", "缩略图仅支持固定尺寸的整图预览。")
            return
        try:
            path, _ = resolve_existing_file(self.cfg.img_dir, raw_relpath, self.cfg.allow_all_files)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "file_error", str(exc))
            return
        with self.server.thumbnail_slots:
            body = make_thumbnail(path)
        self.send_response(HTTPStatus.OK)
        self._add_common_headers()
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _handle_archive(self, query: dict[str, list[str]], *, send_body: bool) -> None:
        requested_paths: list[str] = []
        for raw_p in query.get("path", []):
            if raw_p.strip():
                requested_paths.append(raw_p.strip())
        if "paths" in query:
            for item in query["paths"]:
                requested_paths.extend(p.strip() for p in item.split(",") if p.strip())

        try:
            # Explicit paths take precedence over the directory selector.
            filter_query = {key: values for key, values in query.items() if key != "prefix"} if requested_paths else query
            filters, prefix = parse_image_filters(filter_query)
            if requested_paths:
                entries = []
                seen = set()
                for raw_p in requested_paths:
                    resolved, rel = resolve_existing_file(self.cfg.img_dir, raw_p, self.cfg.allow_all_files)
                    if rel not in seen:
                        seen.add(rel)
                        entries.append((resolved, rel, resolved.stat(), ""))
            else:
                entries = iter_images(self.cfg.img_dir, prefix=quote(prefix, safe="/"), allow_all_files=self.cfg.allow_all_files)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "archive_error", str(exc))
            return
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_filter", str(exc))
            return

        if not entries:
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "没有找到可打包下载的图片。")
            return

        store = self.server.claim_store
        if store is not None:
            only_unclaimed = query.get("only_unclaimed", [""])[0].lower() in {"1", "true", "yes"}
            requested_claimer = self._extract_claimer(query)
            try:
                allowed_rels, _ = store.acquire_batch_for_download(
                    [rel for _, rel, _, _ in entries],
                    requested_claimer,
                    only_unclaimed=only_unclaimed,
                    filters=filters,
                    claim=send_body,
                )
            except ClaimError as exc:
                self._handle_claim_error(exc)
                return
            allowed_set = set(allowed_rels)
            entries = [entry for entry in entries if entry[1] in allowed_set]
        elif not image_tags.matches({}, filters):
            entries = []
        if not entries:
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "没有符合条件的可打包图片。")
            return

        archive_name = f"{self.cfg.img_dir.name}.zip"
        with SpooledTemporaryFile(max_size=SPOOL_LIMIT_BYTES, mode="w+b") as spool:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_STORED) as zf:
                for resolved, rel, _, _ in entries:
                    zf.write(resolved, arcname=rel)
            spool.seek(0, os.SEEK_END)
            total_size = spool.tell()
            spool.seek(0)

            self.send_response(HTTPStatus.OK)
            self._add_common_headers()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(total_size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", content_disposition_header("attachment", archive_name))
            self.end_headers()
            if send_body:
                self._stream_file_handle(spool, total_size)

    def _handle_queue_list(self, query: dict[str, list[str]], *, send_body: bool) -> None:
        store = self._require_claim_store()
        if store is None:
            return
        try:
            filters, prefix = parse_image_filters(query, claimer_alias=True)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_filter", str(exc))
            return
        try:
            limit = int(query.get("limit", ["0"])[0] or "0")
            offset = int(query.get("offset", ["0"])[0] or "0")
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_pagination", "limit 和 offset 必须是整数。")
            return
        payload = store.list_queue(
            limit=max(0, limit),
            offset=max(0, offset),
            filters=filters,
            prefix=prefix,
        )
        self._send_json(HTTPStatus.OK, payload, send_body=send_body)

    def _handle_registry(self, query: dict[str, list[str]], *, send_body: bool) -> None:
        include_sha256 = query.get("checksum", [""])[0].lower() in {"1", "true", "yes"}
        include_pending = query.get("include_pending", [""])[0].lower() in {"1", "true", "yes"}
        try:
            filters, prefix = parse_image_filters(query, claimer_alias=True)
            limit = int(query.get("limit", ["0"])[0] or "0")
            offset = int(query.get("offset", ["0"])[0] or "0")
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_filter", str(exc))
            return

        store = self.server.claim_store
        if include_pending and store is None:
            self._require_claim_store()
            return

        try:
            items = self._collect_filtered_images(filters, prefix, include_sha256=include_sha256)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return

        by_source = {"collection_queue": 0, "img_claims": 0, "unregistered": 0}
        for item in items:
            src = item.get("registry_source") or "unregistered"
            by_source[src] = by_source.get(src, 0) + 1
        registered_count = by_source["collection_queue"] + by_source["img_claims"]
        unregistered_count = by_source["unregistered"]
        matched_count = len(items)
        sliced = items[offset:] if offset > 0 else items
        if limit > 0:
            sliced = sliced[:limit]

        queue_summary = None
        pending_queue: list[dict] = []
        if store is not None:
            all_queue = store.list_queue()["items"]
            downloaded_count = sum(1 for q in all_queue if q.get("local_file"))
            queue_summary = {
                "total": len(all_queue),
                "downloaded_count": downloaded_count,
                "pending_download_count": len(all_queue) - downloaded_count,
            }
            if include_pending:
                pending_queue = [
                    q for q in all_queue
                    if not q.get("local_file")
                    and image_tags.matches(q, filters)
                    and path_matches_prefix(q.get("local_file"), prefix)
                ]

        payload = {
            "directory": self.cfg.img_dir.name,
            "claim_tracking": store is not None,
            "total_files": matched_count,
            "registered_count": registered_count,
            "unregistered_count": unregistered_count,
            "by_source": by_source,
            "queue_summary": queue_summary,
            "matched_count": matched_count,
            "images": sliced,
        }
        if include_pending:
            payload["pending_queue"] = pending_queue
        self._send_json(HTTPStatus.OK, payload, send_body=send_body)

    def _handle_claim_create(self, query: dict[str, list[str]]) -> None:
        store = self._require_claim_store()
        if store is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return
        claimer = self._extract_claimer(query, payload)
        claim_next = bool(payload.get("next")) or query.get("next", [""])[0].lower() in {"1", "true", "yes"}
        category = str(payload.get("category") or query.get("category", [""])[0] or "").strip()
        try:
            queue_id, file_url, relpath = self._parse_claim_selector(query, payload)
            filters = {}
            if claim_next:
                fields = {key: payload[key] for key in ("question_types", "difficulty", "difficulty_tags") if key in payload}
                normalized = image_tags.normalize_updates(fields) if fields else {}
                filters = image_tags.read_tags(dict.fromkeys(image_tags.TAG_FIELDS, "") | normalized)
                filters["difficulty"] = [filters["difficulty"]] if filters["difficulty"] else []
                match = payload.get("match", "all")
                if match not in ("all", "any"):
                    raise ValueError("match 必须是 all 或 any。")
                filters["match"] = match
                filters["authored_status"] = parse_authored_filter(query, payload)
            result = store.claim_item(
                claimer=claimer,
                queue_id=queue_id,
                file_url=file_url,
                relpath=relpath,
                claim_next=claim_next,
                category=category,
                filters=filters,
            )
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_filter", str(exc))
            return
        except ClaimError as exc:
            self._handle_claim_error(exc)
            return
        self._send_json(HTTPStatus.OK, result)

    def _handle_claim_modify(self, query: dict[str, list[str]], *, force_release: bool = False) -> None:
        store = self._require_claim_store()
        if store is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return
        expected_claimer = self._extract_claimer(query, payload)
        release = force_release or bool(payload.get("release")) or query.get("release", [""])[0].lower() in {"1", "true", "yes"}
        if release:
            new_claimed_by = ""
        elif "new_claimed_by" in payload:
            new_claimed_by = str(payload["new_claimed_by"] or "")
        elif "claimed_by" in payload:
            new_claimed_by = str(payload["claimed_by"] or "")
        elif "new_claimed_by" in query:
            new_claimed_by = query["new_claimed_by"][0]
        else:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "missing_field", "请提供 new_claimed_by（新领取人）或 release=true（释放）。")
            return
        force = bool(payload.get("force")) or query.get("force", [""])[0].lower() in {"1", "true", "yes"}
        try:
            queue_id, file_url, relpath = self._parse_claim_selector(query, payload)
            result = store.update_claim(
                expected_claimer=expected_claimer,
                new_claimed_by=new_claimed_by,
                queue_id=queue_id,
                file_url=file_url,
                relpath=relpath,
                force=force,
            )
        except PathValidationError as exc:
            self._send_error_json(exc.status, "invalid_path", str(exc))
            return
        except ClaimError as exc:
            self._handle_claim_error(exc)
            return
        self._send_json(HTTPStatus.OK, result)

    def _handle_claim_batch(self, query: dict[str, list[str]]) -> None:
        store = self._require_claim_store()
        if store is None:
            return
        payload = self._read_json_body()
        if payload is None:
            return
        skip_claimed = bool(payload.get("skip_claimed"))
        force = bool(payload.get("force"))
        entries: list[dict] = []
        if isinstance(payload.get("items"), list):
            for item in payload["items"]:
                if not isinstance(item, dict):
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_items", "items 中的每一项都必须是对象。")
                    return
                entry = dict(item)
                if "path" in entry and entry["path"] is not None:
                    try:
                        entry["path"] = "/".join(parse_relpath(str(entry["path"])))
                    except PathValidationError as exc:
                        self._send_error_json(exc.status, "invalid_path", str(exc))
                        return
                entries.append(entry)
        else:
            claimer = self._extract_claimer(query, payload)
            for qid in payload.get("ids", []):
                entries.append({"id": int(qid), "claimed_by": claimer})
            for furl in payload.get("file_urls", []):
                entries.append({"file_url": str(furl), "claimed_by": claimer})
            for raw_p in payload.get("paths", []):
                try:
                    entries.append({"path": "/".join(parse_relpath(str(raw_p))), "claimed_by": claimer})
                except PathValidationError as exc:
                    self._send_error_json(exc.status, "invalid_path", str(exc))
                    return

        if not entries:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "empty_batch", "请提供要批量标记的 items、ids、file_urls 或 paths。")
            return
        try:
            result = store.batch_update_claims(entries, skip_claimed=skip_claimed, force=force)
        except ClaimError as exc:
            self._handle_claim_error(exc)
            return
        self._send_json(HTTPStatus.OK, result)

    def _handle_swagger_asset(self, route: str, *, send_body: bool) -> None:
        name, content_type = SWAGGER_ASSETS[route]
        try:
            handle = (SWAGGER_DIR / name).open("rb")
        except FileNotFoundError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "找不到 Swagger UI 资源。")
            return
        with handle:
            size = os.fstat(handle.fileno()).st_size
            self.send_response(HTTPStatus.OK)
            self._add_common_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            if name == "index.html":
                self.send_header("Content-Security-Policy", SWAGGER_CSP)
                self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if send_body:
                self._stream_file_handle(handle, size)

    def _dispatch_read(self, *, send_body: bool) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)

        if parsed.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"}, send_body=send_body)
            return
        if parsed.path == "/openapi.json":
            self._send_json(HTTPStatus.OK, self.server.openapi, send_body=send_body)
            return
        if parsed.path in SWAGGER_ASSETS:
            self._handle_swagger_asset(parsed.path, send_body=send_body)
            return
        if not self._require_auth(query):
            return

        path = parsed.path
        if path in ("/", "/img", "/img/", "/api/images", "/api/files"):
            self._handle_list(path, query, send_body=send_body)
            return
        if path == "/api/queue":
            self._handle_queue_list(query, send_body=send_body)
            return
        if path == "/api/registry":
            self._handle_registry(query, send_body=send_body)
            return
        if path == "/api/tags/schema":
            self._send_json(HTTPStatus.OK, image_tags.schema(), send_body=send_body)
            return
        if path.startswith("/api/thumb/"):
            self._handle_thumbnail(path[len("/api/thumb/"):], query, send_body=send_body)
            return
        if path.startswith("/img/"):
            self._handle_file_download(path[len("/img/"):], query, force_attachment=False, send_body=send_body)
            return
        if path.startswith("/download/"):
            self._handle_file_download(path[len("/download/"):], query, force_attachment=True, send_body=send_body)
            return
        if path.startswith("/api/meta/"):
            self._handle_meta(path[len("/api/meta/"):], send_body=send_body)
            return
        if path in ("/api/archive", "/download-all"):
            self._handle_archive(query, send_body=send_body)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"未知路径：{path}")

    def _parse_content_length(self) -> int | None:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            self._send_error_json(HTTPStatus.LENGTH_REQUIRED, "length_required", "上传请求必须包含 Content-Length 请求头。")
            return None
        try:
            length = int(raw_len)
            if length < 0:
                raise ValueError
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length", "无效的 Content-Length。")
            return None
        if length > self.cfg.max_upload_bytes:
            self._send_error_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "payload_too_large",
                f"上传大小超过限制 ({self.cfg.max_upload_bytes // (1024 * 1024)} MB)。",
            )
            return None
        return length

    def _handle_put_upload(self, raw_relpath: str) -> None:
        content_length = self._parse_content_length()
        if content_length is None:
            return
        try:
            target, rel = resolve_upload_target(self.cfg.img_dir, raw_relpath, self.cfg.allow_all_files)
            existed, written, sha256 = save_stream_atomically(target, self.rfile, content_length, self.cfg.max_upload_bytes)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "upload_error", str(exc))
            return
        mime = guess_mime_type(target, self.cfg.allow_all_files) or "application/octet-stream"
        meta = build_file_metadata(target, rel, target.stat(), mime)
        meta["sha256"] = sha256
        meta["bytes_written"] = written
        self._send_json(HTTPStatus.OK if existed else HTTPStatus.CREATED, {"uploaded": [meta]})

    def _handle_post_upload(self, query: dict[str, list[str]]) -> None:
        content_length = self._parse_content_length()
        if content_length is None:
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raw_path = query.get("path", [""])[0] or self.headers.get("X-Filename", "")
            try:
                target, rel = resolve_upload_target(self.cfg.img_dir, raw_path, self.cfg.allow_all_files)
                existed, _, sha256 = save_stream_atomically(target, self.rfile, content_length, self.cfg.max_upload_bytes)
            except PathValidationError as exc:
                self._send_error_json(exc.status, "upload_error", str(exc))
                return
            mime = guess_mime_type(target, self.cfg.allow_all_files) or "application/octet-stream"
            meta = build_file_metadata(target, rel, target.stat(), mime)
            meta["sha256"] = sha256
            self._send_json(HTTPStatus.OK if existed else HTTPStatus.CREATED, {"uploaded": [meta]})
            return

        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "incomplete_body", "上传请求体不完整。")
            return
        raw_mime = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", errors="replace") + body
        message = BytesParser(policy=email_default_policy).parsebytes(raw_mime)
        if not message.is_multipart():
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_multipart", "无法解析 multipart/form-data 请求。")
            return

        subdir = query.get("dir", [""])[0]
        explicit_path = query.get("path", [""])[0]
        file_parts: list[tuple[str, bytes]] = []
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if field_name == "dir" and filename is None:
                subdir = payload.decode("utf-8", errors="replace").strip()
            elif field_name == "path" and filename is None:
                explicit_path = payload.decode("utf-8", errors="replace").strip()
            elif filename:
                file_parts.append((filename, payload))

        if not file_parts:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "missing_file", "multipart 请求中未包含上传文件字段。")
            return

        uploaded_meta = []
        any_created = False
        try:
            for filename, payload in file_parts:
                clean_name = Path(filename.replace("\\", "/")).name
                raw_target = explicit_path if (explicit_path and len(file_parts) == 1) else (
                    f"{subdir.strip('/')}/{clean_name}" if subdir.strip("/") else clean_name
                )
                target, rel = resolve_upload_target(self.cfg.img_dir, raw_target, self.cfg.allow_all_files)
                existed, sha256 = save_bytes_atomically(target, payload)
                any_created = any_created or (not existed)
                mime = guess_mime_type(target, self.cfg.allow_all_files) or "application/octet-stream"
                meta = build_file_metadata(target, rel, target.stat(), mime)
                meta["sha256"] = sha256
                uploaded_meta.append(meta)
        except PathValidationError as exc:
            self._send_error_json(exc.status, "upload_error", str(exc))
            return

        self._send_json(HTTPStatus.CREATED if any_created else HTTPStatus.OK, {"uploaded": uploaded_meta})

    def do_GET(self) -> None:
        try:
            self._dispatch_read(send_body=True)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self) -> None:
        try:
            self._dispatch_read(send_body=False)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._add_common_headers()
        if self.cfg.cors_origin:
            methods = "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
            self.send_header("Access-Control-Allow-Methods", methods)
            self.send_header("Access-Control-Allow-Headers", "Authorization, X-Token, X-API-Key, Content-Type, Range, X-Filename, X-Claimer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._require_auth(query):
            return
        if parsed.path == "/api/claims":
            self._handle_claim_modify(query)
            return
        if not self.cfg.allow_upload:
            self._send_error_json(HTTPStatus.FORBIDDEN, "upload_disabled", "服务端未开启上传功能，请使用 --allow-upload 启动。")
            return
        if not parsed.path.startswith("/img/"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "PUT 上传请使用 /img/<相对路径>。")
            return
        self._handle_put_upload(parsed.path[len("/img/"):])

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._require_auth(query):
            return
        if parsed.path == "/api/tags/batch":
            self._handle_tags_write(query, batch=True)
            return
        if parsed.path == "/api/claims":
            self._handle_claim_create(query)
            return
        if parsed.path == "/api/claims/batch":
            self._handle_claim_batch(query)
            return
        if parsed.path == "/api/claims/update":
            self._handle_claim_modify(query)
            return
        if not self.cfg.allow_upload:
            self._send_error_json(HTTPStatus.FORBIDDEN, "upload_disabled", "服务端未开启上传功能，请使用 --allow-upload 启动。")
            return
        if parsed.path != "/api/upload":
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "POST 上传请使用 /api/upload。")
            return
        self._handle_post_upload(query)

    def do_PATCH(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._require_auth(query):
            return
        if parsed.path == "/api/tags":
            self._handle_tags_write(query)
            return
        if parsed.path == "/api/claims":
            self._handle_claim_modify(query)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"未知路径：{parsed.path}")

    def do_DELETE(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._require_auth(query):
            return
        if parsed.path == "/api/claims":
            self._handle_claim_modify(query, force_release=True)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"未知路径：{parsed.path}")


def detect_lan_ips() -> list[str]:
    """Best-effort detection of non-loopback IPv4 addresses for printing helpful access URLs."""
    ips = set()
    try:
        hostname_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        for addr in hostname_ips:
            if not addr.startswith("127."):
                ips.add(addr)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            addr = sock.getsockname()[0]
            if addr and not addr.startswith("127."):
                ips.add(addr)
    except OSError:
        pass
    return sorted(ips)


def mask_token(token: str) -> str:
    """Mask a configured token for safe console display."""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def create_server(config: ServerConfig, ssl_cert: Path | None = None, ssl_key: Path | None = None) -> ImageHTTPServer:
    """Instantiate ImageHTTPServer and optionally wrap its socket with TLS."""
    if bool(ssl_cert) != bool(ssl_key):
        raise ValueError("--ssl-cert 和 --ssl-key 必须同时提供。")
    httpd = ImageHTTPServer((config.host, config.port), ImageHTTPHandler, config)
    if ssl_cert and ssl_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(ssl_cert), keyfile=str(ssl_key))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对外提供携带 HTTP Token 验证的 ./img 图片下载与传输服务。"
    )
    parser.add_argument("--host", default=None, help=f"监听地址，默认 {DEFAULT_HOST}（允许外部访问）")
    parser.add_argument("--port", type=int, default=None, help=f"监听端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--dir", dest="img_dir", type=Path, default=None, help=f"图片目录，默认 {DEFAULT_IMG_DIR}")
    parser.add_argument("--create-dir", action="store_true", help="自定义目录不存在时自动创建")
    parser.add_argument("--token", default=None, help="访问 Token（也可通过环境变量或 .env 中的 IMG_SERVER_TOKEN 设置）")
    parser.add_argument("--token-file", type=Path, default=None, help="从指定文件读取访问 Token")
    parser.add_argument("--generate-token", action="store_true", help="生成一个随机强 Token 并退出")
    parser.add_argument("--disable-query-token", action="store_true", help="禁止通过 URL 参数 ?token=... 传参，只允许请求头传 Token")
    parser.add_argument("--allow-upload", action="store_true", help="开启图片上传传输接口（PUT /img/<路径> 与 POST /api/upload）")
    parser.add_argument("--max-upload-mb", type=float, default=DEFAULT_MAX_UPLOAD_MB, help=f"单次上传上限（MB），默认 {DEFAULT_MAX_UPLOAD_MB:g}")
    parser.add_argument("--all-files", action="store_true", help="允许下载目录中的非图片文件")
    parser.add_argument("--db", dest="db_path", type=Path, default=None, help=f"领取状态数据库路径，默认自动使用 {DEFAULT_DB_NAME}")
    parser.add_argument("--no-db", action="store_true", help="禁用数据库领取状态跟踪与防重复下载拦截")
    parser.add_argument("--cors-origin", default="", help="设置 Access-Control-Allow-Origin 响应头")
    parser.add_argument("--ssl-cert", type=Path, default=None, help="HTTPS 证书路径（PEM）")
    parser.add_argument("--ssl-key", type=Path, default=None, help="HTTPS 私钥路径（PEM）")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")

    args = build_parser().parse_args(argv)
    if args.generate_token:
        print(f"IMG_SERVER_TOKEN={secrets.token_urlsafe(32)}")
        return 0

    config = resolve_config(
        host=args.host,
        port=args.port,
        img_dir=args.img_dir,
        token=args.token,
        token_file=args.token_file,
        allow_query_token=not args.disable_query_token,
        allow_upload=args.allow_upload,
        allow_all_files=args.all_files,
        max_upload_mb=args.max_upload_mb,
        cors_origin=args.cors_origin,
        create_dir=args.create_dir,
        db_path=args.db_path,
        no_db=args.no_db,
    )
    httpd = create_server(config, ssl_cert=args.ssl_cert, ssl_key=args.ssl_key)
    scheme = "https" if args.ssl_cert else "http"
    actual_port = httpd.server_address[1]
    example_host = "127.0.0.1" if config.host in ("0.0.0.0", "::", "") else config.host
    lan_ips = detect_lan_ips() if config.host in ("0.0.0.0", "::", "") else []

    print(f"图片目录: {config.img_dir}")
    print(f"领取数据库: {config.db_path if config.db_path else '已禁用'}")
    print(f"监听地址: {scheme}://{config.host}:{actual_port}")
    print(f"Swagger UI: {scheme}://{example_host}:{actual_port}/docs")
    for ip in lan_ips:
        print(f"局域网地址: {scheme}://{ip}:{actual_port}")
    if config.token_source == "generated":
        print(f"临时 Token（本次随机生成）: {config.token}")
        print("提示: 如需固定 Token，请在 .env 中配置 IMG_SERVER_TOKEN=<你的Token>，或通过 --token 传入。")
        example_token = config.token
    else:
        print(f"Token 来源: {config.token_source} ({mask_token(config.token)})")
        example_token = "<你的IMG_SERVER_TOKEN>"

    print(f"上传开关: {'已开启' if config.allow_upload else '关闭（仅下载与列表）'}")
    print("\n调用示例:")
    print(f'  curl -H "Authorization: Bearer {example_token}" {scheme}://{example_host}:{actual_port}/api/images')
    print(f'  curl -H "Authorization: Bearer {example_token}" -OJ {scheme}://{example_host}:{actual_port}/download/<图片路径>')
    if config.allow_query_token:
        print(f'  curl -OJ "{scheme}://{example_host}:{actual_port}/download/<图片路径>?token={example_token}"')
    print(f'  curl -H "Authorization: Bearer {example_token}" -o img.zip {scheme}://{example_host}:{actual_port}/api/archive')
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        sys.exit(1)
