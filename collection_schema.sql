CREATE TABLE search_keywords (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL CHECK (trim(category) <> ''),
    keyword TEXT NOT NULL COLLATE NOCASE CHECK (trim(keyword) <> ''),
    search_url TEXT NOT NULL,
    selection_notes TEXT NOT NULL,
    is_exploratory INTEGER NOT NULL DEFAULT 0 CHECK (is_exploratory IN (0, 1)),
    UNIQUE (category, keyword)
);

CREATE TABLE collection_queue (
    id INTEGER PRIMARY KEY,
    file_url TEXT NOT NULL UNIQUE CHECK (trim(file_url) <> ''),
    category TEXT NOT NULL CHECK (trim(category) <> ''),
    claimed_by TEXT NOT NULL DEFAULT '',
    question_types TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    difficulty_tags TEXT NOT NULL DEFAULT '',
    tag_notes TEXT NOT NULL DEFAULT '',
    authored_status TEXT NOT NULL DEFAULT '', -- ''=未出题, draft=出题中, authored=已出题, discarded=已淘汰
    authored_ref TEXT NOT NULL DEFAULT '' -- 题号或作者材料路径
);

CREATE TABLE img_claims (
    file_path TEXT PRIMARY KEY,
    claimed_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    question_types TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    difficulty_tags TEXT NOT NULL DEFAULT '',
    tag_notes TEXT NOT NULL DEFAULT '',
    authored_status TEXT NOT NULL DEFAULT '',
    authored_ref TEXT NOT NULL DEFAULT ''
);
