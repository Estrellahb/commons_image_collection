"""Shared atomic file writing and SQLite img_claims registration for local datasets."""

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

import image_tags


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write bytes to a sibling temp file and atomically replace target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.stem}-", suffix=path.suffix, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def ensure_img_claims_schema(conn: sqlite3.Connection) -> None:
    """Ensure img_claims exists with all expected annotation columns."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS img_claims (
            file_path TEXT PRIMARY KEY,
            claimed_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(img_claims)")}
    for field in ("claimed_by", *image_tags.ANNOTATION_FIELDS):
        if field not in existing:
            conn.execute(f"ALTER TABLE img_claims ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")


def register_local_claims(
    db_path: Path, records: list[dict], *, force_tags: bool = False
) -> tuple[int, int]:
    """Upsert local img/ paths and tags into img_claims inside a BEGIN IMMEDIATE transaction."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    inserted = 0
    updated = 0
    with closing(sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None)) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            ensure_img_claims_schema(conn)
            for rec in records:
                rel_img = rec["img_relpath"]
                ann = rec["annotations"]
                existing = conn.execute(
                    "SELECT claimed_by, question_types, difficulty, difficulty_tags, "
                    "tag_notes, authored_status, authored_ref "
                    "FROM img_claims WHERE file_path = ?",
                    (rel_img,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO img_claims (
                            file_path, claimed_by, updated_at,
                            question_types, difficulty, difficulty_tags, tag_notes,
                            authored_status, authored_ref
                        ) VALUES (?, '', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rel_img,
                            now,
                            ann["question_types"],
                            ann["difficulty"],
                            ann["difficulty_tags"],
                            ann["tag_notes"],
                            ann["authored_status"],
                            ann["authored_ref"],
                        ),
                    )
                    inserted += 1
                else:
                    old_q, old_diff, old_dtags, old_notes, old_astatus, old_aref = existing[1:]
                    has_tags = any((old_q, old_diff, old_dtags, old_notes))
                    new_q = ann["question_types"] if (force_tags or not has_tags) else old_q
                    new_diff = ann["difficulty"] if (force_tags or not has_tags) else old_diff
                    new_dtags = ann["difficulty_tags"] if (force_tags or not has_tags) else old_dtags
                    new_notes = ann["tag_notes"] if (force_tags or not has_tags) else old_notes
                    new_astatus = old_astatus if old_astatus else ann["authored_status"]
                    conn.execute(
                        """
                        UPDATE img_claims
                        SET updated_at = ?, question_types = ?, difficulty = ?,
                            difficulty_tags = ?, tag_notes = ?, authored_status = ?, authored_ref = ?
                        WHERE file_path = ?
                        """,
                        (now, new_q, new_diff, new_dtags, new_notes, new_astatus, old_aref, rel_img),
                    )
                    updated += 1
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    return inserted, updated
