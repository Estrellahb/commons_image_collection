#!/usr/bin/env python3
"""SQLite ledger bridge for ZeroBench authoring (collection_queue + img_claims + 来源与许可.jsonl).

Does NOT check or filter by image pixel dimensions or file sizes.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import image_tags
import local_registry

DEFAULT_DB = PROJECT_ROOT / "采集数据.sqlite"
DEFAULT_PROVENANCE = PROJECT_ROOT / "来源与许可.jsonl"
DEFAULT_IMG_DIR = PROJECT_ROOT / "img"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
PAGE_ID_FILE_RE = re.compile(r"^zb-[a-z]+-(\d+)\.[^.]+$", re.I)
COMMONS_URL_RE = re.compile(r"https?://commons\.wikimedia\.org/wiki/File:[^\s\"'<>|]+", re.I)
PAGE_ID_HTML_RE = re.compile(r"Page\s+ID\s+(\d+)", re.I)
QUEUE_COLUMNS = ("id", "file_url", "category", "claimed_by", *image_tags.ANNOTATION_FIELDS)
LOCAL_CLAIM_COLUMNS = ("file_path", "claimed_by", "updated_at", *image_tags.ANNOTATION_FIELDS)


class LedgerError(RuntimeError):
    """Base error for ledger operations with machine-readable code."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_commons_title(value: str) -> str:
    """Normalize a Wikimedia Commons File URL or title for reliable matching."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        raw = unquote(urlsplit(raw).path).removeprefix("/wiki/")
    else:
        raw = unquote(raw)
    normalized = raw.replace("_", " ").strip()
    if normalized.lower().startswith("file:"):
        return "File:" + normalized[5:].strip()
    return normalized


def normalize_img_relpath(raw_path: str) -> str:
    """Strip leading img/ or images/ prefix and normalize POSIX slashes."""
    rel = (raw_path or "").replace("\\", "/").lstrip("/")
    for prefix in ("img/", "images/"):
        if rel.startswith(prefix):
            return rel[len(prefix):]
    return rel


def extract_page_id_from_name(name: str) -> str | None:
    m = PAGE_ID_FILE_RE.match(Path(name).name)
    return m.group(1) if m else None


def resolve_context_paths(
    db_path: Path,
    provenance_path: Path,
    img_dir: Path | None,
    outputs_dir: Path | None,
) -> tuple[Path, Path, Path | None, Path | None]:
    db_resolved = db_path.resolve()
    prov_resolved = provenance_path.resolve()
    is_default_db = db_resolved == DEFAULT_DB.resolve()

    if img_dir is not None:
        resolved_img = img_dir.resolve()
    elif is_default_db:
        resolved_img = DEFAULT_IMG_DIR.resolve()
    else:
        cand = db_resolved.parent / "img"
        resolved_img = cand.resolve() if cand.is_dir() else None

    if outputs_dir is not None:
        resolved_outputs = outputs_dir.resolve()
    elif is_default_db:
        resolved_outputs = DEFAULT_OUTPUTS_DIR.resolve()
    else:
        cand = db_resolved.parent / "outputs"
        resolved_outputs = cand.resolve() if cand.is_dir() else None

    return db_resolved, prov_resolved, resolved_img, resolved_outputs


def load_provenance_index(provenance_path: Path) -> dict:
    """Read 来源与许可.jsonl keeping the LATEST record for each title, page_id, and relpath."""
    latest_by_title: dict[str, dict] = {}
    latest_by_page_id: dict[str, dict] = {}
    latest_by_rel: dict[str, dict] = {}
    title_to_rels: dict[str, list[str]] = {}

    if not provenance_path.is_file():
        return {
            "latest_by_title": latest_by_title,
            "latest_by_page_id": latest_by_page_id,
            "latest_by_rel": latest_by_rel,
            "title_to_rels": title_to_rels,
        }

    for raw_line in provenance_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        title = canonical_commons_title(rec.get("source_page") or rec.get("title") or "")
        page_id = str(rec["page_id"]) if rec.get("page_id") is not None else None
        raw_file = rec.get("file", "")
        rel = normalize_img_relpath(raw_file) if raw_file else ""

        if title:
            latest_by_title[title] = rec
        if page_id:
            latest_by_page_id[page_id] = rec
        if rel:
            latest_by_rel[rel] = rec
            if title:
                title_to_rels.setdefault(title, [])
                if rel not in title_to_rels[title]:
                    title_to_rels[title].append(rel)

    return {
        "latest_by_title": latest_by_title,
        "latest_by_page_id": latest_by_page_id,
        "latest_by_rel": latest_by_rel,
        "title_to_rels": title_to_rels,
    }


def _find_local_relpath(
    file_url: str,
    prov_rec: dict | None,
    prov_index: dict,
    img_dir: Path | None,
) -> str | None:
    if img_dir is None or not img_dir.is_dir():
        return None
    canon = canonical_commons_title(file_url)
    candidates: list[Path] = []
    seen: set[str] = set()

    def push(rel_str: str):
        if not rel_str:
            return
        norm = normalize_img_relpath(rel_str)
        rp = Path(norm)
        for cand in (rp, Path(rp.name)):
            key = cand.as_posix()
            if key not in seen:
                seen.add(key)
                candidates.append(cand)
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if rp.suffix.lower() != ext:
                for cand in (rp.with_suffix(ext), Path(rp.name).with_suffix(ext)):
                    key = cand.as_posix()
                    if key not in seen:
                        seen.add(key)
                        candidates.append(cand)

    if prov_rec and prov_rec.get("file"):
        push(prov_rec["file"])
    for rel in reversed(prov_index["title_to_rels"].get(canon, [])):
        push(rel)

    for cand in candidates:
        if (img_dir / cand).is_file():
            return cand.as_posix()
    return None


def scan_outputs_sources(outputs_dir: Path | None, prov_index: dict) -> dict:
    """Scan outputs/ authoring cases and _work dirs for source page_ids and titles."""
    by_page_id: dict[str, list[str]] = {}
    by_title: dict[str, list[str]] = {}

    def record(ref_id: str, *, page_id: str | None = None, url_or_title: str | None = None):
        if page_id:
            refs = by_page_id.setdefault(str(page_id), [])
            if ref_id not in refs:
                refs.append(ref_id)
            prov = prov_index["latest_by_page_id"].get(str(page_id))
            if prov and prov.get("source_page"):
                t = canonical_commons_title(prov["source_page"])
                if t:
                    trefs = by_title.setdefault(t, [])
                    if ref_id not in trefs:
                        trefs.append(ref_id)
        if url_or_title:
            t = canonical_commons_title(url_or_title)
            if t:
                trefs = by_title.setdefault(t, [])
                if ref_id not in trefs:
                    trefs.append(ref_id)
                prov = prov_index["latest_by_title"].get(t)
                if prov and prov.get("page_id") is not None:
                    pid = str(prov["page_id"])
                    prefs = by_page_id.setdefault(pid, [])
                    if ref_id not in prefs:
                        prefs.append(ref_id)

    if outputs_dir is None or not outputs_dir.is_dir():
        return {"by_page_id": by_page_id, "by_title": by_title}

    for entry in sorted(outputs_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or not entry.name.startswith("authoring_"):
            continue
        qid = entry.name.removeprefix("authoring_")
        for child in entry.iterdir():
            if child.is_file() and child.suffix.lower() in IMAGE_EXTS:
                pid = extract_page_id_from_name(child.name)
                if pid:
                    record(qid, page_id=pid)
        html_path = entry / "author_record.html"
        if html_path.is_file():
            # Scan non-base64 text slices for URLs / Page IDs efficiently
            txt = html_path.read_text(encoding="utf-8", errors="ignore")
            for m in COMMONS_URL_RE.finditer(txt):
                record(qid, url_or_title=m.group(0))
            for m in PAGE_ID_HTML_RE.finditer(txt):
                record(qid, page_id=m.group(1))

    work_root = outputs_dir / "_work"
    if work_root.is_dir():
        for wdir in sorted(work_root.iterdir(), key=lambda p: p.name):
            if not wdir.is_dir():
                continue
            qid = wdir.name
            src_file = wdir / "source.json"
            if src_file.is_file():
                try:
                    src = json.loads(src_file.read_text(encoding="utf-8"))
                    if src.get("page_id") is not None:
                        record(qid, page_id=str(src["page_id"]))
                    if src.get("source_page"):
                        record(qid, url_or_title=src["source_page"])
                    for item in src.get("entries", []) if isinstance(src.get("entries"), list) else []:
                        if isinstance(item, dict):
                            if item.get("page_id") is not None:
                                record(qid, page_id=str(item["page_id"]))
                            if item.get("source_page"):
                                record(qid, url_or_title=item["source_page"])
                except (OSError, ValueError):
                    pass
            res_file = wdir / "reservation.json"
            if res_file.is_file():
                try:
                    res = json.loads(res_file.read_text(encoding="utf-8"))
                    if res.get("file_url"):
                        record(qid, url_or_title=res["file_url"])
                    if res.get("file_path"):
                        pid = extract_page_id_from_name(res["file_path"])
                        if pid:
                            record(qid, page_id=pid)
                except (OSError, ValueError):
                    pass
            man_file = wdir / "manifest.json"
            if man_file.is_file():
                try:
                    man = json.loads(man_file.read_text(encoding="utf-8"))
                    items = man.get("items", []) if isinstance(man, dict) else []
                    for item in items:
                        src = item.get("source", {}) if isinstance(item, dict) else {}
                        if src.get("source_page_id") is not None:
                            record(qid, page_id=str(src["source_page_id"]))
                        for pid in src.get("same_scene_page_ids", []) or []:
                            record(qid, page_id=str(pid))
                        if src.get("url"):
                            record(qid, url_or_title=src["url"])
                except (OSError, ValueError):
                    pass

    return {"by_page_id": by_page_id, "by_title": by_title}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _ensure_ledger_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "collection_queue"):
        conn.execute(
            """
            CREATE TABLE collection_queue (
                id INTEGER PRIMARY KEY,
                file_url TEXT NOT NULL UNIQUE CHECK (trim(file_url) <> ''),
                category TEXT NOT NULL CHECK (trim(category) <> ''),
                claimed_by TEXT NOT NULL DEFAULT '',
                question_types TEXT NOT NULL DEFAULT '',
                difficulty TEXT NOT NULL DEFAULT '',
                difficulty_tags TEXT NOT NULL DEFAULT '',
                tag_notes TEXT NOT NULL DEFAULT '',
                authored_status TEXT NOT NULL DEFAULT '',
                authored_ref TEXT NOT NULL DEFAULT ''
            )
            """
        )
    local_registry.ensure_img_claims_schema(conn)
    for table in ("collection_queue", "img_claims"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for field in ("claimed_by", *image_tags.ANNOTATION_FIELDS):
            if field not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")


@contextmanager
def _db_tx(db_path: Path, *, write: bool):
    conn = sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_ledger_schema(conn)
        else:
            conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _iter_local_images(img_dir: Path | None) -> list[str]:
    if img_dir is None or not img_dir.is_dir():
        return []
    rels: list[str] = []
    for p in sorted(img_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = p.relative_to(img_dir).as_posix()
        parts = rel.split("/")
        if any(part.startswith(".") or part in {"掩膜", "元数据"} for part in parts):
            continue
        rels.append(rel)
    return rels


def _infer_category_from_relpath(relpath: str) -> str:
    parts = Path(relpath).parts
    if len(parts) >= 2:
        if parts[0] in ("科学图像", "小众专业实物") and len(parts) >= 3 and parts[2] in ("PNG", "JPG"):
            return f"{parts[0]}/{parts[1]}"
        return f"{parts[0]}/{parts[1]}" if len(parts) > 2 else parts[0]
    return ""


def _build_unified_items(
    conn: sqlite3.Connection,
    prov_index: dict,
    img_dir: Path | None,
    outputs_sources: dict,
) -> list[dict]:
    queue_rows = (
        conn.execute(f"SELECT {', '.join(QUEUE_COLUMNS)} FROM collection_queue ORDER BY id").fetchall()
        if _table_exists(conn, "collection_queue")
        else []
    )
    claim_rows = (
        conn.execute(f"SELECT {', '.join(LOCAL_CLAIM_COLUMNS)} FROM img_claims ORDER BY file_path").fetchall()
        if _table_exists(conn, "img_claims")
        else []
    )

    claims_by_norm: dict[str, sqlite3.Row] = {}
    for cr in claim_rows:
        norm = normalize_img_relpath(cr["file_path"])
        claims_by_norm[norm] = cr

    items: list[dict] = []
    matched_norms: set[str] = set()

    def conflict_info(page_id: str | None, title: str) -> tuple[bool, list[str]]:
        refs: list[str] = []
        if page_id:
            for r in outputs_sources["by_page_id"].get(str(page_id), []):
                if r not in refs:
                    refs.append(r)
        if title:
            for r in outputs_sources["by_title"].get(title, []):
                if r not in refs:
                    refs.append(r)
        return bool(refs), refs

    # 1. Queue rows
    for row in queue_rows:
        canon = canonical_commons_title(row["file_url"])
        prov = prov_index["latest_by_title"].get(canon)
        local_rel = _find_local_relpath(row["file_url"], prov, prov_index, img_dir)
        if local_rel is None and prov and prov.get("file"):
            cand_rel = normalize_img_relpath(prov["file"])
            if cand_rel in claims_by_norm:
                local_rel = cand_rel
        claim_row = claims_by_norm.get(local_rel) if local_rel else None
        if local_rel:
            matched_norms.add(local_rel)

        q_claimed = (row["claimed_by"] or "").strip()
        c_claimed = (claim_row["claimed_by"] or "").strip() if claim_row else ""
        claimed_by = q_claimed or c_claimed

        q_ann = image_tags.read_annotations(row)
        c_ann = image_tags.read_annotations(claim_row) if claim_row else {}
        authored_status = q_ann["authored_status"] or c_ann.get("authored_status", "")
        authored_ref = q_ann["authored_ref"] or c_ann.get("authored_ref", "")
        question_types = q_ann["question_types"] or c_ann.get("question_types", [])
        difficulty = q_ann["difficulty"] or c_ann.get("difficulty", "")
        difficulty_tags = sorted(set(q_ann["difficulty_tags"]) | set(c_ann.get("difficulty_tags", [])))
        tag_notes = q_ann["tag_notes"] or c_ann.get("tag_notes", "")

        page_id = str(prov["page_id"]) if prov and prov.get("page_id") is not None else (extract_page_id_from_name(local_rel) if local_rel else None)
        has_conflict, conflict_refs = conflict_info(page_id, canon)

        local_exists = bool(local_rel and img_dir is not None and (img_dir / local_rel).is_file())
        local_path = f"img/{local_rel}" if local_rel else None

        items.append({
            "registry_source": "collection_queue",
            "id": row["id"],
            "file_url": row["file_url"],
            "path": local_rel,
            "local_path": local_path,
            "local_exists": local_exists,
            "img_claims_key": claim_row["file_path"] if claim_row else local_rel,
            "category": row["category"],
            "claimed_by": claimed_by,
            "claimed": bool(claimed_by),
            "question_types": question_types,
            "difficulty": difficulty,
            "difficulty_tags": difficulty_tags,
            "tag_notes": tag_notes,
            "authored_status": authored_status,
            "authored_ref": authored_ref,
            "page_id": int(page_id) if (page_id and page_id.isdigit()) else page_id,
            "provenance": prov,
            "outputs_conflict": has_conflict,
            "outputs_conflict_refs": conflict_refs,
        })

    # 2. Local img_claims & local img/ files not matched to queue
    local_disk = _iter_local_images(img_dir)
    seen_norms = set(matched_norms)
    all_local_norms: list[str] = []
    for norm in sorted(claims_by_norm):
        if norm not in seen_norms:
            seen_norms.add(norm)
            all_local_norms.append(norm)
    for norm in local_disk:
        if norm not in seen_norms:
            seen_norms.add(norm)
            all_local_norms.append(norm)

    for norm in sorted(all_local_norms):
        claim_row = claims_by_norm.get(norm)
        prov = prov_index["latest_by_rel"].get(norm)
        if prov is None:
            pid = extract_page_id_from_name(norm)
            if pid:
                prov = prov_index["latest_by_page_id"].get(pid)
        canon = canonical_commons_title(prov.get("source_page") or prov.get("title") or "") if prov else ""
        page_id = str(prov["page_id"]) if prov and prov.get("page_id") is not None else extract_page_id_from_name(norm)
        has_conflict, conflict_refs = conflict_info(page_id, canon)

        ann = image_tags.read_annotations(claim_row)
        claimed_by = (claim_row["claimed_by"] or "").strip() if claim_row else ""
        category = (prov.get("category") if prov else "") or _infer_category_from_relpath(norm)
        local_exists = bool(img_dir is not None and (img_dir / norm).is_file())
        items.append({
            "registry_source": "img_claims" if claim_row is not None else "local_img",
            "id": None,
            "file_url": prov.get("source_page") if prov else None,
            "path": norm,
            "local_path": f"img/{norm}",
            "local_exists": local_exists,
            "img_claims_key": claim_row["file_path"] if claim_row else norm,
            "category": category,
            "claimed_by": claimed_by,
            "claimed": bool(claimed_by),
            "question_types": ann["question_types"],
            "difficulty": ann["difficulty"],
            "difficulty_tags": ann["difficulty_tags"],
            "tag_notes": ann["tag_notes"],
            "authored_status": ann["authored_status"],
            "authored_ref": ann["authored_ref"],
            "page_id": int(page_id) if (page_id and page_id.isdigit()) else page_id,
            "provenance": prov,
            "outputs_conflict": has_conflict,
            "outputs_conflict_refs": conflict_refs,
        })

    return items


def _build_filters(args) -> dict:
    qtypes = image_tags.normalize_codes(
        [p.strip() for v in (args.question_type or []) for p in v.split(",") if p.strip()],
        image_tags.QUESTION_TYPES,
        "question_type",
    ) if getattr(args, "question_type", None) else []
    diffs = image_tags.normalize_codes(
        [p.strip() for v in (args.difficulty or []) for p in v.split(",") if p.strip()],
        image_tags.DIFFICULTIES,
        "difficulty",
    ) if getattr(args, "difficulty", None) else []
    dtags = image_tags.normalize_codes(
        [p.strip() for v in (args.difficulty_tag or []) for p in v.split(",") if p.strip()],
        image_tags.DIFFICULTY_TAGS,
        "difficulty_tag",
    ) if getattr(args, "difficulty_tag", None) else []

    authored_status = getattr(args, "authored_status", "")
    if authored_status == "all":
        authored_filter = None
    else:
        if authored_status not in image_tags.AUTHORED_STATUSES:
            raise LedgerError("invalid_filter", f"Invalid authored_status: {authored_status}")
        authored_filter = authored_status

    return {
        "status": getattr(args, "status", "all"),
        "authored_status": authored_filter,
        "category": getattr(args, "category", "") or "",
        "question_types": qtypes,
        "difficulty": diffs,
        "difficulty_tags": dtags,
        "match": "all",
    }


def cmd_list(args) -> dict:
    db_path, prov_path, img_dir, outputs_dir = resolve_context_paths(
        args.db, args.provenance, args.img_dir, args.outputs_dir
    )
    if not db_path.is_file():
        raise LedgerError("db_not_found", f"SQLite database not found: {db_path}")
    prov_index = load_provenance_index(prov_path)
    outputs_sources = scan_outputs_sources(outputs_dir, prov_index)
    filters = _build_filters(args)

    with _db_tx(db_path, write=False) as conn:
        all_items = _build_unified_items(conn, prov_index, img_dir, outputs_sources)

    matched = [item for item in all_items if image_tags.matches(item, filters)]
    total_matched = len(matched)
    if args.limit > 0:
        matched = matched[: args.limit]

    return {
        "ok": True,
        "command": "list",
        "db": str(db_path),
        "provenance": str(prov_path),
        "total_scanned": len(all_items),
        "matched_count": total_matched,
        "returned_count": len(matched),
        "filters": {k: v for k, v in filters.items() if v not in ("", [], None) or k == "authored_status"},
        "items": matched,
    }


def _resolve_target_item(
    items: list[dict],
    *,
    queue_id: int | None = None,
    file_url: str | None = None,
    relpath: str | None = None,
) -> dict:
    if queue_id is not None:
        for it in items:
            if it["id"] == queue_id:
                return it
        raise LedgerError("not_found", f"Queue id={queue_id} not found")

    if file_url is not None:
        canon = canonical_commons_title(file_url)
        for it in items:
            if it.get("file_url") and (it["file_url"] == file_url or canonical_commons_title(it["file_url"]) == canon):
                return it
        raise LedgerError("not_found", f"file_url not found: {file_url}")

    if relpath is not None:
        norm = normalize_img_relpath(relpath)
        for it in items:
            if it.get("path") == norm or it.get("img_claims_key") in (relpath, norm):
                return it
        raise LedgerError("not_found", f"path not found in ledger or img_dir: {relpath}")

    raise LedgerError("invalid_selector", "Provide one of --id, --file-url, --path, or --next")


def _write_work_skeleton(work_dir: Path, updated_item: dict, img_dir: Path | None) -> list[str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    qid = updated_item.get("qid") or (
        updated_item["authored_ref"].split("|", 1)[0].strip() if updated_item.get("authored_ref") else ""
    ) or (f"ZB-QUEUE-{updated_item['id']}" if updated_item.get("id") is not None else Path(updated_item["path"]).stem)

    reservation = {
        "id": updated_item.get("id"),
        "file_path": updated_item.get("path"),
        "local_path": updated_item.get("local_path"),
        "file_url": updated_item.get("file_url"),
        "qid": qid,
        "claimed_by": updated_item.get("claimed_by"),
        "authored_status": updated_item.get("authored_status"),
        "authored_ref": updated_item.get("authored_ref"),
        "claimed_at": utc_now_iso(),
    }

    local_file = (img_dir / updated_item["path"]) if (img_dir and updated_item.get("path")) else None
    sha256 = None
    dimensions = None
    if local_file and local_file.is_file():
        sha256 = hashlib.sha256(local_file.read_bytes()).hexdigest()
        try:
            from PIL import Image
            with Image.open(local_file) as im:
                dimensions = list(im.size)
        except Exception:
            dimensions = None

    prov = updated_item.get("provenance") or {}
    source_doc = {
        "id": updated_item.get("id"),
        "page_id": updated_item.get("page_id"),
        "category": updated_item.get("category"),
        "file_url": updated_item.get("file_url"),
        "local_path": updated_item.get("local_path"),
        "sha256": sha256,
        "dimensions": dimensions,
        "provenance": prov,
    }

    if local_file and local_file.is_file():
        try:
            image_ref = str(local_file.resolve())
        except OSError:
            image_ref = updated_item.get("local_path") or ""
    else:
        image_ref = updated_item.get("local_path") or updated_item.get("file_url") or ""

    manifest_doc = {
        "items": [
            {
                "id": qid,
                "image": image_ref,
                "require_real": True,
                "source": {
                    "kind": "real_photo",
                    "url": updated_item.get("file_url") or (prov.get("source_page") if isinstance(prov, dict) else ""),
                    "license_url": ((prov.get("license") or {}).get("LicenseUrl") if isinstance(prov, dict) and isinstance(prov.get("license"), dict) else ""),
                    "authorization": "verified" if prov else "pending",
                },
                "objects": [],
                "critical_rois": [],
                "platform_points": [],
                "task": {},
            }
        ]
    }

    created = []
    for fname, payload in (
        ("reservation.json", reservation),
        ("source.json", source_doc),
        ("manifest.json", manifest_doc),
    ):
        target = work_dir / fname
        local_registry.atomic_write_bytes(
            target, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        created.append(str(target))
    return created


def _sync_write_fields(
    conn: sqlite3.Connection,
    item: dict,
    *,
    claimed_by: str | None = None,
    authored_status: str | None = None,
    authored_ref: str | None = None,
) -> None:
    now = utc_now_iso()
    fields: dict[str, str] = {}
    if claimed_by is not None:
        fields["claimed_by"] = claimed_by
    if authored_status is not None:
        fields["authored_status"] = authored_status
    if authored_ref is not None:
        fields["authored_ref"] = authored_ref

    if not fields:
        return

    if item["id"] is not None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE collection_queue SET {assignments} WHERE id = ?",
            (*fields.values(), item["id"]),
        )

    claim_key = item.get("img_claims_key") or item.get("path")
    should_sync_claims = (
        item["id"] is None
        or item.get("local_exists")
        or (
            claim_key
            and conn.execute("SELECT 1 FROM img_claims WHERE file_path = ?", (claim_key,)).fetchone() is not None
        )
    )
    if claim_key and should_sync_claims:
        existing = conn.execute(
            "SELECT claimed_by, question_types, difficulty, difficulty_tags, tag_notes, authored_status, authored_ref "
            "FROM img_claims WHERE file_path = ?",
            (claim_key,),
        ).fetchone()
        if existing is None:
            q_types = ",".join(item.get("question_types") or [])
            d_tags = ",".join(item.get("difficulty_tags") or [])
            conn.execute(
                """
                INSERT INTO img_claims (
                    file_path, claimed_by, updated_at,
                    question_types, difficulty, difficulty_tags, tag_notes,
                    authored_status, authored_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_key,
                    fields.get("claimed_by", item.get("claimed_by", "")),
                    now,
                    q_types,
                    item.get("difficulty", ""),
                    d_tags,
                    item.get("tag_notes", ""),
                    fields.get("authored_status", item.get("authored_status", "")),
                    fields.get("authored_ref", item.get("authored_ref", "")),
                ),
            )
        else:
            assignments = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
            conn.execute(
                f"UPDATE img_claims SET {assignments} WHERE file_path = ?",
                (*fields.values(), now, claim_key),
            )


def cmd_claim(args) -> dict:
    claimer = (args.claimer or "").strip()
    if not claimer:
        raise LedgerError("invalid_claimer", "--claimer cannot be empty")
    db_path, prov_path, img_dir, outputs_dir = resolve_context_paths(
        args.db, args.provenance, args.img_dir, args.outputs_dir
    )
    if not db_path.is_file():
        raise LedgerError("db_not_found", f"SQLite database not found: {db_path}")

    prov_index = load_provenance_index(prov_path)
    outputs_sources = scan_outputs_sources(outputs_dir, prov_index)
    qid = (args.qid or "").strip() or None
    authored_ref = f"{qid} | outputs/authoring_{qid}" if qid else None

    with _db_tx(db_path, write=True) as conn:
        all_items = _build_unified_items(conn, prov_index, img_dir, outputs_sources)
        if args.next:
            filters = _build_filters(args)
            filters["status"] = "unclaimed"
            filters["authored_status"] = ""
            target = next(
                (it for it in all_items if image_tags.matches(it, filters) and not it["outputs_conflict"]),
                None,
            )
            if target is None:
                raise LedgerError("no_available_item", "No unclaimed, unauthored, non-conflicting image matches filters")
        else:
            target = _resolve_target_item(
                all_items, queue_id=args.id, file_url=args.file_url, relpath=args.path
            )

        cur_claimer = target["claimed_by"]
        cur_status = target["authored_status"]
        if cur_claimer and cur_claimer != claimer:
            raise LedgerError("already_claimed", f"Already claimed by {cur_claimer}", details={"item": target})
        if cur_status and not (cur_status == "draft" and cur_claimer == claimer):
            raise LedgerError("already_authored", f"Item already has authored_status={cur_status!r}", details={"item": target})

        new_ref = authored_ref if authored_ref is not None else target.get("authored_ref", "")
        _sync_write_fields(
            conn,
            target,
            claimed_by=claimer,
            authored_status="draft",
            authored_ref=new_ref,
        )

        refreshed = _build_unified_items(conn, prov_index, img_dir, outputs_sources)
        updated = _resolve_target_item(
            refreshed,
            queue_id=target["id"],
            file_url=target["file_url"] if target["id"] is None else None,
            relpath=target["path"] if target["id"] is None else None,
        )
        if qid:
            updated["qid"] = qid

    work_files: list[str] = []
    if args.work_dir is not None:
        work_files = _write_work_skeleton(args.work_dir.resolve(), updated, img_dir)

    return {
        "ok": True,
        "command": "claim",
        "item": updated,
        "work_files": work_files,
    }


def cmd_mark(args) -> dict:
    if args.authored_status not in image_tags.AUTHORED_STATUSES:
        raise LedgerError(
            "invalid_authored_status",
            f"authored_status must be one of {image_tags.AUTHORED_STATUSES}",
        )
    db_path, prov_path, img_dir, outputs_dir = resolve_context_paths(
        args.db, args.provenance, args.img_dir, args.outputs_dir
    )
    if not db_path.is_file():
        raise LedgerError("db_not_found", f"SQLite database not found: {db_path}")

    prov_index = load_provenance_index(prov_path)
    outputs_sources = scan_outputs_sources(outputs_dir, prov_index)

    with _db_tx(db_path, write=True) as conn:
        all_items = _build_unified_items(conn, prov_index, img_dir, outputs_sources)
        target = _resolve_target_item(
            all_items, queue_id=args.id, file_url=args.file_url, relpath=args.path
        )
        _sync_write_fields(
            conn,
            target,
            authored_status=args.authored_status,
            authored_ref=args.authored_ref,
        )
        refreshed = _build_unified_items(conn, prov_index, img_dir, outputs_sources)
        updated = _resolve_target_item(
            refreshed,
            queue_id=target["id"],
            file_url=target["file_url"] if target["id"] is None else None,
            relpath=target["path"] if target["id"] is None else None,
        )

    return {
        "ok": True,
        "command": "mark",
        "item": updated,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common_paths(p: argparse.ArgumentParser):
        p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite ledger path")
        p.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE, help="JSONL provenance path")
        p.add_argument("--img-dir", type=Path, default=None, help="Optional local img/ root")
        p.add_argument("--outputs-dir", type=Path, default=None, help="Optional outputs/ root")

    def add_filter_args(p: argparse.ArgumentParser):
        p.add_argument("--category", default="", help="Exact category filter")
        p.add_argument("--question-type", action="append", default=[], help="Question type code(s)")
        p.add_argument("--difficulty", action="append", default=[], help="Difficulty code(s)")
        p.add_argument("--difficulty-tag", action="append", default=[], help="Difficulty tag code(s)")

    p_list = sub.add_parser("list", help="List and filter queue & local images")
    add_common_paths(p_list)
    p_list.add_argument("--status", choices=("unclaimed", "claimed", "all"), default="unclaimed")
    p_list.add_argument("--unclaimed", action="store_const", const="unclaimed", dest="status", help="Shorthand for --status unclaimed")
    p_list.add_argument("--authored-status", default="", help="'' (default unauthored), draft, authored, discarded, or all")
    p_list.add_argument("--unauthored", action="store_const", const="", dest="authored_status", help="Shorthand for --authored-status ''")
    add_filter_args(p_list)
    p_list.add_argument("--limit", type=int, default=20)

    p_claim = sub.add_parser("claim", help="Atomically claim an image in SQLite")
    add_common_paths(p_claim)
    sel_claim = p_claim.add_mutually_exclusive_group(required=True)
    sel_claim.add_argument("--id", type=int, help="collection_queue.id")
    sel_claim.add_argument("--file-url", help="Wikimedia Commons file_url")
    sel_claim.add_argument("--path", help="Relative image path under img/")
    sel_claim.add_argument("--next", action="store_true", help="Claim next matching unclaimed & unauthored item")
    add_filter_args(p_claim)
    p_claim.add_argument("--claimer", required=True, help="Claimer identifier")
    p_claim.add_argument("--qid", "--authored-ref", "--ref", dest="qid", default="", help="Optional question ID (e.g. ZB-XXXX-v1)")
    p_claim.add_argument("--work-dir", type=Path, default=None, help="Optional work directory for skeleton files")

    p_mark = sub.add_parser("mark", help="Update authored_status and optional authored_ref")
    add_common_paths(p_mark)
    sel_mark = p_mark.add_mutually_exclusive_group(required=True)
    sel_mark.add_argument("--id", type=int, help="collection_queue.id")
    sel_mark.add_argument("--file-url", help="Wikimedia Commons file_url")
    sel_mark.add_argument("--path", help="Relative image path under img/")
    p_mark.add_argument("--authored-status", "--status", dest="authored_status", required=True, choices=image_tags.AUTHORED_STATUSES)
    p_mark.add_argument("--authored-ref", "--ref", dest="authored_ref", default=None)

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            payload = cmd_list(args)
        elif args.command == "claim":
            payload = cmd_claim(args)
        elif args.command == "mark":
            payload = cmd_mark(args)
        else:
            raise LedgerError("unknown_command", f"Unsupported command: {args.command}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, ValueError) as exc:
        err = {
            "ok": False,
            "error": getattr(exc, "code", "validation_error"),
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
        print(json.dumps(err, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
