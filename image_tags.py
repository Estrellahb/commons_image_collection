"""Shared tag definitions, validation and matching for image annotations."""

QUESTION_TYPES = {
    "counting": ("计数聚合链", "辨认实体及属性，按明确口径筛选、计数或求完整方案数。"),
    "complex_instruction": ("复杂指令遵循", "用可核验的图像事实执行多条相互作用的规则。"),
    "game_puzzle": ("游戏·谜题规则求解", "恢复可核验的盘面或状态，按明确规则求解。"),
    "robust_ocr": ("抗干扰文本读取", "在视觉干扰下读取可辨文字或数字，用于对象对应或计算。"),
    "localization_measurement": ("定位度量", "以可核验的坐标、刻度或参照确定位置、距离或读数。"),
    "topology_tracking": ("拓扑·图结构追踪", "依据可核验的连接关系追踪路径、连通性或状态。"),
    "spatial_transform": ("空间变换", "执行可验证的镜像、旋转、拼合或多视角对应。"),
    "domain_decoding": ("小众知识解码", "依据明确专业规则解码图中可辨的符号或器物信息。"),
}

DIFFICULTIES = {
    "easy": ("简单", "候选方向主要依靠一次读取、筛选或简单对应。"),
    "medium": ("中等", "候选方向需核对多组对象，或据图建立明确关系并计算。"),
    "hard": ("困难", "候选方向需将多个可核验图像事实联合用于约束或全局求解。"),
}

DIFFICULTY_TAGS = {
    "high_density": ("密集目标", "关键对象密集，须逐一核对身份或属性。"),
    "occlusion_overlap": ("遮挡／重叠", "关键对象部分遮挡，仍可依据图证确定归属。"),
    "small_target": ("小目标／小字", "关键目标或读数较小，在原图中可辨。"),
    "high_similarity": ("相似干扰项", "相似对象的可辨差异会影响筛选或对应。"),
    "cluttered_bg": ("背景／光影干扰", "杂物、反光或阴影干扰关键证据读取。"),
    "view_transform": ("旋转／镜像／视角变化", "需处理方向、镜像或视角才能读取或对应。"),
    "cross_region_alignment": ("跨区对应", "须将不同区域或面板中的对象和属性可靠对应。"),
    "branching_paths": ("分叉／线路交叉", "须区分接点和跨越并追踪实际连接。"),
    "multi_hop_visual": ("多步视觉推理", "先前图像判断决定后续读取、参数或关系。"),
}

TAG_FIELDS = ("question_types", "difficulty", "difficulty_tags", "tag_notes")
AUTHORED_STATUS_META = {
    "": ("未出题", "尚未用于出题的图片。"),
    "draft": ("出题中", "已选定拟出题或正在构造复算中。"),
    "authored": ("已出题", "已定稿完成出题并通过质检。"),
    "discarded": ("已淘汰", "经核查不适合出题的图片。"),
}
AUTHORED_STATUSES = tuple(AUTHORED_STATUS_META)
AUTHORED_FIELDS = ("authored_status", "authored_ref")
ANNOTATION_FIELDS = (*TAG_FIELDS, *AUTHORED_FIELDS)
REGISTRY_SOURCES = ("collection_queue", "img_claims", "none")


def schema():
    return {
        name: [{"code": code, "label": label, "description": description}
               for code, (label, description) in definitions.items()]
        for name, definitions in (
            ("question_types", QUESTION_TYPES),
            ("difficulty", DIFFICULTIES),
            ("difficulty_tags", DIFFICULTY_TAGS),
            ("authored_status", AUTHORED_STATUS_META),
        )
    }


def normalize_codes(values, definitions, field):
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"{field} 必须是字符串数组。")
    cleaned = {value.strip() for value in values}
    if "" in cleaned or cleaned - definitions.keys():
        raise ValueError(f"{field} 包含无效标签。")
    return sorted(cleaned)


def normalize_updates(payload):
    updates = {}
    for field in ANNOTATION_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field in ("question_types", "difficulty_tags"):
            definitions = QUESTION_TYPES if field == "question_types" else DIFFICULTY_TAGS
            updates[field] = ",".join(normalize_codes(value, definitions, field))
        elif not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串。")
        elif field == "difficulty":
            value = value.strip()
            if value and value not in DIFFICULTIES:
                raise ValueError("difficulty 无效。")
            updates[field] = value
        elif field == "authored_status":
            if value not in AUTHORED_STATUSES:
                raise ValueError("authored_status 必须为空字符串、draft、authored 或 discarded。")
            updates[field] = value
        else:
            value.encode("utf-8")
            updates[field] = value
    if not updates:
        raise ValueError("请至少提供一个标签或出题状态字段。")
    return updates


def read_tags(row=None):
    def value(field):
        return (row[field] or "") if row is not None else ""

    def codes(field, definitions):
        return sorted({part.strip() for part in value(field).split(",") if part.strip() in definitions})

    difficulty = value("difficulty").strip()
    return {
        "question_types": codes("question_types", QUESTION_TYPES),
        "difficulty": difficulty if difficulty in DIFFICULTIES else "",
        "difficulty_tags": codes("difficulty_tags", DIFFICULTY_TAGS),
        "tag_notes": value("tag_notes"),
    }


def read_annotations(row=None):
    return {**read_tags(row), **{field: row[field] if row is not None else "" for field in AUTHORED_FIELDS}}


def matches(item, filters):
    authored_status = filters.get("authored_status")
    if authored_status is not None and item.get("authored_status", "") != authored_status:
        return False
    for field in ("question_types", "difficulty_tags"):
        requested = set(filters.get(field, []))
        if not requested:
            continue
        actual = set(item.get(field, []))
        matched = bool(requested & actual) if filters.get("match") == "any" else requested <= actual
        if not matched:
            return False
    difficulties = filters.get("difficulty", [])
    if difficulties and item.get("difficulty", "") not in difficulties:
        return False
    tagged = bool(item.get("question_types") or item.get("difficulty") or item.get("difficulty_tags"))
    if filters.get("tagged") is not None and tagged != filters["tagged"]:
        return False
    claimed_by = item.get("claimed_by", "")
    if filters.get("status") == "unclaimed" and claimed_by:
        return False
    if filters.get("status") == "claimed" and not claimed_by:
        return False
    if filters.get("claimed_by") and claimed_by != filters["claimed_by"]:
        return False
    if filters.get("category") and item.get("category") != filters["category"]:
        return False
    registered = filters.get("registered")
    if registered is not None and bool(item.get("registered")) != registered:
        return False
    registry_source = filters.get("registry_source")
    if registry_source is not None:
        actual_source = item.get("registry_source", "")
        expected_source = "" if registry_source == "none" else registry_source
        if actual_source != expected_source:
            return False
    return True
