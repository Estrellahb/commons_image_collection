"""OpenAPI schema for the image server and its legacy routes."""

import image_tags


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def array(items):
    return {"type": "array", "items": items}


def obj(properties, required=()):
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


STRING = {"type": "string"}
INTEGER = {"type": "integer", "format": "int64"}
BOOLEAN = {"type": "boolean"}
BINARY = {"type": "string", "format": "binary"}

TAG_VALUES = {
    "question_types": array({**STRING, "enum": list(image_tags.QUESTION_TYPES)}),
    "difficulty": {**STRING, "enum": ["", *image_tags.DIFFICULTIES]},
    "difficulty_tags": array({**STRING, "enum": list(image_tags.DIFFICULTY_TAGS)}),
    "tag_notes": STRING,
}
AUTHORED_VALUES = {
    "authored_status": {**STRING, "enum": list(image_tags.AUTHORED_STATUSES)},
    "authored_ref": STRING,
}
SELECTOR = {"id": INTEGER, "file_url": STRING, "path": STRING}
CLAIM_FIELDS = {"claimed": BOOLEAN, "claimed_by": STRING}
CLAIM_TARGET = {
    **SELECTOR,
    **CLAIM_FIELDS,
    **TAG_VALUES,
    **AUTHORED_VALUES,
    "source": STRING,
    "category": STRING,
    "local_file": {**STRING, "nullable": True},
    "download_url": STRING,
    "view_url": STRING,
    "newly_claimed": BOOLEAN,
}
FILE_FIELDS = {
    "path": STRING,
    "name": STRING,
    "size": INTEGER,
    "mtime": STRING,
    "etag": STRING,
    "mime_type": STRING,
    "view_url": STRING,
    "download_url": STRING,
    "thumb_url": STRING,
    "sha256": STRING,
    "bytes_written": INTEGER,
    **CLAIM_FIELDS,
    **TAG_VALUES,
    **AUTHORED_VALUES,
    "queue_id": {**INTEGER, "nullable": True},
    "file_url": {**STRING, "nullable": True},
    "category": {**STRING, "nullable": True},
}
SCHEMAS = {
    "Error": obj(
        {
            "error": STRING,
            "message": STRING,
            "claimed_by": STRING,
            "index": INTEGER,
            "conflicts": array(obj({"path": STRING, "claimed_by": STRING, "queue_id": {**INTEGER, "nullable": True}})),
        },
        ("error", "message"),
    ),
    "Image": obj(FILE_FIELDS, ("path", "name", "size", "mime_type")),
    "ImageList": obj(
        {
            "directory": STRING,
            "count": INTEGER,
            "total_bytes": INTEGER,
            "claim_tracking": BOOLEAN,
            "images": array(ref("Image")),
        }
    ),
    "Queue": obj(
        {
            "total": INTEGER,
            "claimed_count": INTEGER,
            "unclaimed_count": INTEGER,
            "matched_count": INTEGER,
            "items": array(ref("ClaimTarget")),
        }
    ),
    "ClaimTarget": obj(CLAIM_TARGET),
    "ClaimBatchResult": obj(
        {
            "updated_count": INTEGER,
            "skipped_count": INTEGER,
            "updated": array(ref("ClaimTarget")),
            "skipped": array(obj({"target": ref("ClaimTarget"), "claimed_by": STRING})),
        }
    ),
    "TagDefinition": obj({"code": STRING, "label": STRING, "description": STRING}),
    "TagSchema": obj(
        {
            field: array(ref("TagDefinition"))
            for field in ("question_types", "difficulty", "difficulty_tags", "authored_status")
        }
    ),
    "TagPatch": {
        **obj({**SELECTOR, **TAG_VALUES, **AUTHORED_VALUES}),
        "oneOf": [{"required": [field]} for field in SELECTOR],
        "anyOf": [{"required": [field]} for field in (*TAG_VALUES, *AUTHORED_VALUES)],
        "additionalProperties": False,
    },
    "TagBatchResult": obj({"updated_count": INTEGER, "items": array(ref("ClaimTarget"))}),
    "UploadResult": obj({"uploaded": array(ref("Image"))}),
}


def param(name, description, schema=STRING, *, location="query", example=None, explode=None):
    value = {
        "name": name,
        "in": location,
        "description": description,
        "schema": schema,
        "required": location == "path",
    }
    if example is not None:
        value["example"] = example
    if explode is not None:
        value.update(style="form", explode=explode)
    return value


RELATIVE_PATH = param("relpath", "img/ 内的相对路径，支持子目录。", location="path", example="分类/示例.jpg")
CLAIMER = param("claimer", "当前操作人，用于领取或下载。中文姓名可填此查询参数或 JSON 请求体。")
CLAIMER_HEADER = param(
    "X-Claimer",
    "当前操作人请求头，优先于查询参数。Swagger UI 中的中文姓名请填查询参数或 JSON 请求体。",
    location="header",
)
SELECTOR_PARAMETERS = [
    param(field, "图片定位字段，填写 id、file_url 或 path 中的一项。", schema) for field, schema in SELECTOR.items()
]
AUTHORED_PARAMETERS = [
    {
        **param("authored_status", "出题状态。显式传空字符串筛选未出题。", AUTHORED_VALUES["authored_status"]),
        "allowEmptyValue": True,
    },
    param("authored", "出题状态的兼容筛选。0 为未出题，1 为已出题。", {**STRING, "enum": ["0", "1"]}),
]


def filters(*, claimer_alias=False):
    parameters = [
        param("question_type", "候选题型，可多选。", TAG_VALUES["question_types"], explode=False),
        param(
            "difficulty", "综合难度，可多选。", array({**STRING, "enum": list(image_tags.DIFFICULTIES)}), explode=False
        ),
        param("difficulty_tag", "视觉难点，可多选。", TAG_VALUES["difficulty_tags"], explode=False),
        param("match", "各标签组内匹配全部或任一所选项。", {**STRING, "enum": ["all", "any"], "default": "all"}),
        param("tagged", "1 为已打标，0 为待标注。", {**STRING, "enum": ["0", "1"]}),
        param("status", "领取状态。", {**STRING, "enum": ["all", "unclaimed", "claimed"], "default": "all"}),
        *AUTHORED_PARAMETERS,
        param("claimed_by", "筛选已有领取人。"),
        param("category", "队列类别。"),
        param("prefix", "img/ 内的目录前缀。"),
    ]
    if claimer_alias:
        parameters.append(param("claimer", "claimed_by 的兼容别名。"))
    return parameters


def response(description, schema=None, *, media="application/json", headers=None):
    value = {"description": description}
    if schema is not None:
        value["content"] = {media: {"schema": schema}}
    if headers:
        value["headers"] = {name: {"schema": STRING} for name in headers}
    return value


ERRORS = {
    "400": "参数或请求体无效。",
    "401": "需要有效的 HTTP Token。",
    "403": "路径、权限或服务配置不允许此操作。",
    "404": "没有找到符合条件的记录或文件。",
    "409": "图片已被其他人领取，或目标发生冲突。",
    "411": "上传请求需要 Content-Length。",
    "413": "请求体超过大小限制。",
    "503": "服务未启用 SQLite。",
}


def operation(name, group, summary, responses, *, params=(), description=None, body=None, errors=(), public=False):
    value = {"operationId": name, "tags": [group], "summary": summary, "responses": dict(responses)}
    if public:
        value["security"] = []
    if params:
        value["parameters"] = list(params)
    if description:
        value["description"] = description
    if body:
        value["requestBody"] = body
    for code in errors if public else ("401", *errors):
        value["responses"][code] = response(ERRORS[code], ref("Error"))
    return value


def json_body(schema, examples, *, required=True):
    return {
        "required": required,
        "content": {
            "application/json": {
                "schema": schema,
                "examples": {name: {"value": value} for name, value in examples.items()},
            }
        },
    }


def get_head(get, *, omit_errors=()):
    head = dict(get, operationId=f"{get['operationId']}Head", summary=f"检查响应头 · {get['summary']}")
    head["responses"] = {
        code: {key: value for key, value in definition.items() if key != "content"}
        for code, definition in get["responses"].items()
        if code not in omit_errors
    }
    return {"get": get, "head": head}


def openapi_document(*, allow_query_token=True):
    categories = ("服务与文档", "图片与下载", "队列与领取", "标签", "上传", "跨域预检")
    service, images, claims, tags, uploads, cors = categories
    paths = {}

    paths["/health"] = get_head(
        operation("health", service, "健康检查", {"200": response("服务正常。", obj({"status": STRING}))}, public=True)
    )
    paths["/openapi.json"] = get_head(
        operation(
            "openapi",
            service,
            "获取 OpenAPI 文档",
            {"200": response("OpenAPI 3.0 文档。", {"type": "object"})},
            public=True,
        )
    )
    paths["/docs"] = get_head(
        operation(
            "swaggerUi",
            service,
            "打开 Swagger UI",
            {"200": response("交互式接口文档。", STRING, media="text/html")},
            public=True,
        )
    )
    paths["/docs/"] = get_head(
        operation(
            "swaggerUiSlash",
            service,
            "打开 Swagger UI（带结尾斜杠）",
            {"200": response("交互式接口文档。", STRING, media="text/html")},
            public=True,
        )
    )

    list_parameters = [*filters(claimer_alias=True), param("checksum", "为每张图计算 SHA-256。", BOOLEAN)]
    list_response = {"200": response("图片清单。", ref("ImageList"))}
    for path, name in (
        ("/api/images", "listImages"),
        ("/api/files", "listFiles"),
        ("/img", "listImg"),
        ("/img/", "listImgSlash"),
    ):
        paths[path] = get_head(
            operation(name, images, "列出本地图片", list_response, params=list_parameters, errors=("400", "403"))
        )
    gallery_responses = {
        "200": {
            "description": "网页或 JSON 图片清单。",
            "content": {
                "application/json": {"schema": ref("ImageList")},
                "text/html": {"schema": STRING},
            },
        }
    }
    paths["/"] = get_head(
        operation(
            "gallery",
            images,
            "图片浏览页或 JSON 清单",
            gallery_responses,
            params=[*list_parameters, param("format", "显式选择输出格式。", {**STRING, "enum": ["html", "json"]})],
            errors=("400", "403"),
        )
    )

    file_headers = ("Content-Disposition", "ETag", "Last-Modified", "X-Claimed-By", "X-File-SHA256", "Accept-Ranges")
    file_responses = {
        "200": response(
            "原文件，Content-Type 取决于实际文件。", BINARY, media="application/octet-stream", headers=file_headers
        ),
        "206": response(
            "单个字节范围。", BINARY, media="application/octet-stream", headers=(*file_headers, "Content-Range")
        ),
        "304": response("文件未更改。", headers=("ETag", "Last-Modified", "X-Claimed-By")),
        "416": response("无效或不支持的范围。", headers=("Content-Range",)),
    }
    for code in ("200", "206"):
        file_responses[code]["content"]["*/*"] = {"schema": BINARY}
    file_parameters = [
        RELATIVE_PATH,
        CLAIMER,
        CLAIMER_HEADER,
        param("sha256", "返回 X-File-SHA256 响应头。", BOOLEAN),
        param("Range", "单个字节范围，例如 bytes=0-1023。", location="header"),
        param("If-None-Match", "文件 ETag。", location="header"),
        param("If-Modified-Since", "HTTP 日期。", location="header"),
    ]
    for path, name, summary in (
        ("/img/{relpath}", "viewImage", "查看原图"),
        ("/download/{relpath}", "downloadImage", "下载原图"),
    ):
        parameters = list(file_parameters)
        if name == "viewImage":
            parameters += [
                param("download", "作为附件下载。", BOOLEAN),
                param("attachment", "download 的兼容别名。", BOOLEAN),
            ]
        paths[path] = get_head(
            operation(
                name,
                images,
                summary,
                file_responses,
                params=parameters,
                description="启用 SQLite 时，GET 可能领取图片。HEAD 仅返回响应头。",
                errors=("400", "403", "404", "409"),
            ),
            omit_errors=("409",),
        )
    paths["/api/meta/{relpath}"] = get_head(
        operation(
            "imageMetadata",
            images,
            "读取图片元数据",
            {"200": response("元数据及 SHA-256。", ref("Image"))},
            params=[RELATIVE_PATH],
            errors=("400", "403", "404"),
        )
    )
    paths["/api/thumb/{relpath}"] = get_head(
        operation(
            "thumbnail",
            images,
            "预览 JPEG 缩略图",
            {"200": response("长边至多 360 像素的 JPEG 或占位图。", BINARY, media="image/jpeg")},
            params=[RELATIVE_PATH],
            description="读取缩略图不会领取图片。",
            errors=("400", "403", "404"),
        )
    )

    archive_parameters = [
        *filters(),
        CLAIMER,
        CLAIMER_HEADER,
        param("path", "指定一个或多个文件，优先于 prefix。", array(STRING), explode=True),
        param("paths", "逗号分隔的文件路径，优先于 prefix。"),
        param("only_unclaimed", "兼容参数，跳过他人已领取的图片。仅打包未领取图片请用 status=unclaimed。", BOOLEAN),
    ]
    for path, name in (("/api/archive", "downloadArchive"), ("/download-all", "downloadAll")):
        paths[path] = get_head(
            operation(
                name,
                images,
                "打包并下载 ZIP",
                {
                    "200": response(
                        "筛选结果的 ZIP。", BINARY, media="application/zip", headers=("Content-Disposition",)
                    )
                },
                params=archive_parameters,
                description="启用 SQLite 时，GET 可能领取多张图片。HEAD 只读取候选。",
                errors=("400", "403", "404", "409"),
            ),
            omit_errors=("409",),
        )

    paths["/api/queue"] = get_head(
        operation(
            "listQueue",
            claims,
            "筛选采集队列",
            {"200": response("队列与统计信息。", ref("Queue"))},
            params=[
                *filters(claimer_alias=True),
                param("limit", "每页数量，0 表示不限。", INTEGER),
                param("offset", "跳过的匹配项数。", INTEGER),
            ],
            errors=("400", "403", "503"),
        )
    )

    claim_response = {"200": response("本次操作后的领取信息。", ref("ClaimTarget"))}
    claim_errors = ("400", "403", "404", "409", "413", "503")
    claim_selector = [*SELECTOR_PARAMETERS, CLAIMER, CLAIMER_HEADER]
    claim_create = operation(
        "createClaim",
        claims,
        "领取指定图片或下一条队列项",
        claim_response,
        description=(
            "next=true 时按队列 id 顺序领取第一条符合条件的未领取记录。"
            "authored_status、authored、category 可放查询参数或 JSON 请求体；"
            "question_types、difficulty（单值字符串）、difficulty_tags、match 仅从 JSON 请求体读取。"
            "省略出题状态筛选时匹配所有状态，出题领取建议传 ?authored=0 或 {\"authored_status\": \"\"}。"
        ),
        params=[
            *claim_selector,
            param("next", "领取下一条未领取的队列项。", BOOLEAN),
            param("category", "next 模式下的队列类别。"),
            *AUTHORED_PARAMETERS,
        ],
        errors=claim_errors,
        body=json_body(
            obj(
                {
                    **SELECTOR,
                    "claimer": STRING,
                    "next": BOOLEAN,
                    "category": STRING,
                    "match": {**STRING, "enum": ["all", "any"]},
                    "authored_status": AUTHORED_VALUES["authored_status"],
                    **{field: schema for field, schema in TAG_VALUES.items() if field != "tag_notes"},
                }
            ),
            {
                "byId": {"id": 42, "claimer": "张三"},
                "nextByTags": {"next": True, "claimer": "张三", "question_types": ["counting"], "difficulty": "hard"},
                "nextUnauthored": {"next": True, "claimer": "张三", "authored_status": ""},
            },
            required=False,
        ),
    )
    claim_modify_params = [*claim_selector, param("force", "强制修改或释放现有领取。", BOOLEAN)]
    claim_modify_body = json_body(
        obj(
            {
                **SELECTOR,
                "claimer": STRING,
                "new_claimed_by": STRING,
                "claimed_by": STRING,
                "release": BOOLEAN,
                "force": BOOLEAN,
            }
        ),
        {
            "transfer": {"id": 42, "claimer": "张三", "new_claimed_by": "李四"},
            "release": {"id": 42, "claimer": "张三", "release": True},
        },
        required=False,
    )
    claim_modify_args = {
        "params": [
            *claim_modify_params,
            param("new_claimed_by", "新领取人。"),
            param("release", "释放领取。", BOOLEAN),
        ],
        "body": claim_modify_body,
        "errors": claim_errors,
    }
    paths["/api/claims"] = {
        "post": claim_create,
        "patch": operation("modifyClaim", claims, "修改、转交或释放领取", claim_response, **claim_modify_args),
        "put": operation("replaceClaim", claims, "修改领取（PUT 兼容接口）", claim_response, **claim_modify_args),
        "delete": operation(
            "releaseClaim",
            claims,
            "释放领取",
            claim_response,
            params=claim_modify_params,
            errors=claim_errors,
            description="在 Swagger UI 中使用查询参数定位图片。兼容客户端也可发送 JSON 请求体。",
        ),
    }
    paths["/api/claims/update"] = {
        "post": operation("updateClaim", claims, "修改领取（POST 兼容接口）", claim_response, **claim_modify_args)
    }
    paths["/api/claims/batch"] = {
        "post": operation(
            "batchClaims",
            claims,
            "批量更新领取",
            {"200": response("批量处理结果。", ref("ClaimBatchResult"))},
            params=[CLAIMER, CLAIMER_HEADER],
            errors=claim_errors,
            body=json_body(
                obj(
                    {
                        "claimer": STRING,
                        "ids": array(INTEGER),
                        "file_urls": array(STRING),
                        "paths": array(STRING),
                        "skip_claimed": BOOLEAN,
                        "force": BOOLEAN,
                        "items": array(obj({**SELECTOR, "claimed_by": STRING, "expected_claimer": STRING})),
                    }
                ),
                {
                    "markById": {"ids": [42, 43], "claimer": "张三", "skip_claimed": True},
                    "transfer": {"items": [{"id": 42, "expected_claimer": "张三", "claimed_by": "李四"}]},
                },
            ),
        )
    }

    paths["/api/tags/schema"] = get_head(
        operation(
            "tagSchema", tags, "查询允许的图片标签", {"200": response("合法编码、中文名及说明。", ref("TagSchema"))}
        )
    )
    tag_example = {"id": 42, "question_types": ["counting"], "difficulty": "hard", "difficulty_tags": ["small_target"]}
    tag_errors = ("400", "403", "404", "413", "503")
    paths["/api/tags"] = {
        "patch": operation(
            "saveTags",
            tags,
            "修改单张图片的标签及出题状态",
            {"200": response("更新后的标注与领取状态。", ref("ClaimTarget"))},
            description="id、file_url、path 三选一。省略字段保留原值，传空数组或空字符串可清空。",
            errors=tag_errors,
            body=json_body(ref("TagPatch"), {
                "annotate": tag_example,
                "markAuthored": {"id": 42, "authored_status": "authored", "authored_ref": "ZB-001 | outputs/题目材料"},
            }),
        )
    }
    paths["/api/tags/batch"] = {
        "post": operation(
            "batchTags",
            tags,
            "批量修改图片标签",
            {"200": response("更新后的图片。", ref("TagBatchResult"))},
            description="批次失败时整批回滚。若问题出在某一项，响应包含从 0 开始的 index。",
            errors=tag_errors,
            body=json_body(
                obj({"items": {**array(ref("TagPatch")), "minItems": 1}}, ("items",)),
                {"annotate": {"items": [tag_example]}},
            ),
        )
    }

    upload_responses = {
        "200": response("更新了已有文件。", ref("UploadResult")),
        "201": response("创建了文件。", ref("UploadResult")),
    }
    upload_errors = ("400", "403", "409", "411", "413")
    upload_raw = {"schema": BINARY}
    paths["/img/{relpath}"]["put"] = operation(
        "putImage",
        uploads,
        "上传单个文件（PUT）",
        upload_responses,
        description="需要以 --allow-upload 启动服务。请求体是文件的二进制内容。",
        params=[RELATIVE_PATH],
        errors=upload_errors,
        body={"required": True, "content": {"application/octet-stream": upload_raw}},
    )
    paths["/api/upload"] = {
        "post": operation(
            "uploadImages",
            uploads,
            "上传一个或多个文件",
            upload_responses,
            description=(
                "需要以 --allow-upload 启动。multipart 可选择多个文件，并用 dir 查询参数指定目标目录。"
                "原始二进制上传请指定 path 或 X-Filename。dir 和 path 也可由客户端放进 multipart 表单。"
            ),
            errors=upload_errors,
            params=[
                param("dir", "multipart 文件的目标目录。"),
                param("path", "单文件的目标相对路径。"),
                param("X-Filename", "原始二进制上传的目标相对路径，支持 ASCII 文件名。", location="header"),
            ],
            body={
                "required": True,
                "content": {
                    "multipart/form-data": {"schema": obj({"files": array(BINARY)}, ("files",))},
                    "application/octet-stream": upload_raw,
                },
            },
        )
    }

    for operations in paths.values():
        first = next(iter(operations.values()))
        path_params = [parameter for parameter in first.get("parameters", []) if parameter["in"] == "path"]
        operations["options"] = operation(
            f"{first['operationId']}Options",
            cors,
            f"预检 · {first['summary']}",
            {
                "204": response(
                    "预检成功。启用 CORS 时返回配置的响应头。",
                    headers=(
                        "Access-Control-Allow-Origin",
                        "Access-Control-Allow-Methods",
                        "Access-Control-Allow-Headers",
                    ),
                ),
            },
            params=path_params,
            public=True,
        )

    security = {
        "BearerToken": {
            "type": "http",
            "scheme": "bearer",
            "description": "填入服务 Token。Swagger UI 会加上 Bearer 前缀。",
        },
        "XToken": {"type": "apiKey", "in": "header", "name": "X-Token"},
        "XApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    }
    if allow_query_token:
        security["QueryToken"] = {"type": "apiKey", "in": "query", "name": "token"}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "图片采集服务 API",
            "version": "1.0.0",
            "description": "点击 Authorize 并选择一种认证方式，再用 Try it out 调用接口。下载原图和 ZIP 可能写入领取状态。",
        },
        "servers": [{"url": "/"}],
        "tags": [{"name": group} for group in categories],
        "paths": paths,
        "components": {"schemas": SCHEMAS, "securitySchemes": security},
        "security": [{name: []} for name in security],
    }
