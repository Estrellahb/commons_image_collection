# ZeroBench 实拍密集场景采集

用 SQLite 工具打开 [采集数据.sqlite](采集数据.sqlite)。先从 `search_keywords` 复制关键词或打开检索链接，再把选中的 Commons **File: 文件页链接**和**图片种类**填入 `collection_queue`。下载脚本默认按清单的 `id` 顺序读库，不会自动把搜索结果入库。

## 找图和更新清单

- `search_keywords`：`category` 是完整分类，`keyword` 是检索词，`search_url` 打开 Commons 搜索，`selection_notes` 说明选图要点。原来「继续扩充」一组的词用 `is_exploratory = 1` 标识。
- `collection_queue`：一行对应一张候选图。新增时只填 `file_url` 和 `category`，`id` 自动分配。用 `python download_images.py --list-categories` 查看合法分类，例如 `居家场景/工具五金`。数据库会阻止同一文件页链接重复插入。

优先搜「物件 + 摆放方式」。用预览检查能否数清、分组或读字，排除可识别人脸、遮挡题证的水印和目标过小的广角图，并在单图文件页核对许可。

```sql
SELECT keyword, search_url, selection_notes
FROM search_keywords
WHERE category = '居家场景/工具五金'
ORDER BY id;

SELECT file_url, category FROM collection_queue ORDER BY id;
```

## 配好联系方式，按需填令牌

编辑本文件夹下的 `.env`。公开 Commons 文件查询与下载**不强制登录**，只填 `WIKIMEDIA_CONTACT`（邮箱或 URL 编码的 Wikimedia 用户页链接）即可运行。不要把令牌贴进聊天或采集清单。

如果需要以个人账号身份查询：

1. 登录 Wikimedia 账号，打开 [Meta-Wiki 的 OAuth 2 注册页](https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose/oauth2)。
2. 给应用取名，例如 `ZeroBench Commons Collector`。勾选 **This consumer is for use only by user**（仅本人使用）。授权选基本读取即可，不给编辑、上传等写入权限。
3. 提交后复制页面显示的 **Access token**（不是 Client ID、Client secret），填在 `WIKIMEDIA_ACCESS_TOKEN=` 后面。[官方步骤](https://www.mediawiki.org/wiki/OAuth/Owner-only_consumers)。

```dotenv
WIKIMEDIA_CONTACT=你的联系邮箱
WIKIMEDIA_ACCESS_TOKEN=
WIKIMEDIA_PROXY_URL=http://127.0.0.1:1277
```

脚本只在查询 Commons 官方 API 时发送令牌，不把它发送给图片服务器，也不写入日志或 Excel。`.env` 已排除出 Git。

本机直连 Commons 曾超时，代理 `http://127.0.0.1:1277` 已成功返回 Commons API 的 HTTP 200。脚本用同一代理查询元数据和收取媒体；无需修改系统代理。换机器或直连正常时，可以清空 `WIKIMEDIA_PROXY_URL`。

## 下载和生成 Excel

在 PowerShell 中运行：

```powershell
Set-Location -LiteralPath 'E:\Santi\ZeroBench_CoT\commons_image_collection'
python -m pip install -r requirements.txt
python download_images.py --dry-run
python download_images.py
```

本批筛选出的 200 张候选图覆盖 24 个子类。用 [采集清单-200.csv](采集清单-200.csv) 下载这批图片，可用 JPG 保留较高的像素尺寸：

```bash
python download_images.py --input 采集清单-200.csv --format jpg
```

默认输出 PNG。下一批实拍照片想用 JPG 时，运行 `python download_images.py --format jpg`。只改变新图的输出，已有合规 PNG / JPG 继续沿用，同一来源不会重复下载。

- **分类目录**：`img/<一级类>/<子类>/`。例如 `img/居家场景/工具五金/zb-hardware-123456.jpg`。文件名由子类代号和 Commons 页面 ID 组成。脚本仍能按台账识别保存在旧 `images/` 目录里的 PNG / JPG。旧版 WebP 不会删除，也不会列在本版 Excel 中。
- **分类清单**：`图片分类.xlsx`，只含 **图片**（嵌入缩略图和对应文件名）与 **图片种类** 两列，按分类目录分组。仅成功保存的照片会出现在表中。
- **出处**：`来源与许可.jsonl` 另存作者、许可、来源页、像素尺寸、文件体积和转换说明。当前默认接收许可字段明确的公版／CC0／CC BY／CC BY-SA，不接受标明有额外限制的条目。发布前按 [Commons 复用说明](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia)复核每张图的授权与署名条件。
- **失败项**：`未入库.csv` 列出本次未下载或未处理的原因。若 Excel 正开着，关闭后跑 `python download_images.py --index-only`，用已保存的图重建，不必重下。

项目清单以 SQLite 为准。用 `--input` 可以指定另一份包含同样表结构的数据库（结构见 `collection_schema.sql`）；已有的外部 CSV 仍可通过 `--input 外部清单.csv` 显式读取。

## 单张硬上限 5 MB

脚本将 Commons 的完整像素版本**只读入内存**，按 EXIF 方向校正。PNG 保留颜色数量；未缩小时逐像素核对。JPG 用质量 93 并保留完整色度分辨率，优先保留照片细节；带透明通道或透明色的照片仍存 PNG。两种输出均优先保留原尺寸，超出目标才等比缩小。台账记录原始尺寸、保存尺寸和处理说明。仅支持照片常用的单帧 RGB、RGBA 或 8 位灰度 JPEG / PNG 输入。

单张硬上限是 **5 MB（5,000,000 字节）**。缩小时优先保留长边 2048 像素，仍超上限时继续等比缩小。重做清单中超上限的旧照片可运行 `python download_images.py --recompress-existing`，按已有格式从来源图重新生成，并在新文件合规时替换。特定批次必须保留原尺寸时加 `--no-resize`，可用 `--target-mb 4` 进一步收紧本批上限。上传飞书时使用 `img/` 中的 PNG 或 JPG。

默认单并发，媒体下载限速约 16 Mbps。请勿同时启动多个实例。Excel 可通过 XlsxWriter 或 Codex 工作区运行时生成，若运行时装在非默认路径，设置 `CODEX_WORKSPACE_DEPS` 指向其 `dependencies` 目录。

## 对外提供 `img/` 图片 HTTP Token 下载与传输服务

项目根目录下的 `img/` 文件夹用于存放需要对外传输或下载的图片。运行 `img_server.py` 即可启动 HTTP 服务（默认监听 `0.0.0.0:18080`）。网页缩略图使用 Pillow 生成，未安装时显示占位图。

1. **配置固定 Token**（推荐写入 `.env`，未配置时每次启动会临时生成一个随机 Token 并打印到控制台）：

   ```bash
   python3 img_server.py --generate-token
   # 将输出的 IMG_SERVER_TOKEN=... 写入 .env
   ```

2. **启动服务**：

   ```bash
   python3 img_server.py
   # 或显式指定端口与 Token：
   python3 img_server.py --host 0.0.0.0 --port 18080 --token "你的Token"
   ```

3. **通过 HTTP 携带 Token 列出、下载与传输图片**（支持 `Authorization: Bearer <token>`、`X-Token` 请求头或 `?token=<token>` 参数，支持断点续传 `Range` 与批量打包）：

   ```bash
   # 查看 img/ 下的图片清单
   curl -H "Authorization: Bearer <token>" http://<服务器IP>:18080/api/images

   # 下载单张图片（支持子目录和中文文件名）
   curl -H "Authorization: Bearer <token>" -OJ http://<服务器IP>:18080/download/<图片相对路径>
   curl -OJ "http://<服务器IP>:18080/download/<图片相对路径>?token=<token>"

   # 打包下载全部图片为 zip
   curl -H "Authorization: Bearer <token>" -o img.zip http://<服务器IP>:18080/api/archive
   ```

如需允许外部向 `img/` 上传图片，启动时加上 `--allow-upload`（支持 `PUT /img/<相对路径>` 与 `POST /api/upload`）。若直接暴露在公网，请配合 `--ssl-cert` / `--ssl-key` 启用 HTTPS 或置于 Nginx/Caddy 等反向代理之后。

### Swagger UI

打开 `http://<服务器IP>:18080/docs`，点击 **Authorize**，在 **BearerToken** 填入 `.env` 中的 `IMG_SERVER_TOKEN` 值，再展开接口并点击 **Try it out → Execute**。图片、缩略图、ZIP、队列、领取、标签和上传接口均可在此调用。`relpath` 填 `img/` 内的相对路径，例如 `居家场景/工具五金/示例.jpg`。

Swagger UI 和 `/openapi.json` 可直接打开，业务接口仍按原有规则检查 Token。资源由服务本地提供，使用 Swagger UI `5.36.0`，可在无外网连接时使用。上传需要启动参数 `--allow-upload`。启用 SQLite 时，执行原图或 ZIP 的 `GET` 可能领取图片，查看缩略图或执行 `HEAD` 仅做读取。

### 领取防重与状态修改（关联 `采集数据.sqlite`）

`采集数据.sqlite` 的 `collection_queue` 表新增了 `claimed_by` 列（默认空字符串 `''` 表示未领取）。`img_server.py` 启动时默认自动连接该库并开启防重复领取：

- **下载自动标记 & 拦截重复下载**：首次 `GET /download/<路径>` 或 `GET /img/<路径>` 时会原子写入 `claimed_by`（可通过 `?claimer=张三` 或请求头 `X-Claimer: 张三` 传入领取人，未传则记为 `downloaded`）；之后其他人再次下载或领取会返回 `409 Conflict`，仅原领取人携带相同 `claimer` 或释放后可再下载。
- **队列与领取接口**（均需携带 HTTP Token）：
  - `GET /api/queue?status=unclaimed`：查看队列领取状态（支持 `all` / `unclaimed` / `claimed`、`claimed_by`、`category` 筛选，兼容列表旧参数 `claimer`）。
  - `POST /api/claims`：领取指定记录（`{"id": 1, "claimer": "张三"}`）或顺序领取下一条（`{"next": true, "claimer": "张三"}`）。
  - `PATCH /api/claims`：原领取人修改/转交或释放（`{"id": 1, "claimer": "张三", "new_claimed_by": "李四"}` 或 `{"id": 1, "claimer": "张三", "release": true}`）。
  - `POST /api/claims/batch`：批量补标历史已领取记录（`{"claimer": "张三", "ids": [1, 2, 3], "skip_claimed": true}`）。
- 也可以直接用 SQLite 工具手工修改 `collection_queue.claimed_by` 列（填上名字即视为已领取，清空即释放）。

### 图片标签与筛选

网页首页支持按候选题型、视觉难点、综合难度和领取状态组合筛选，也可从图片卡片编辑标签。网页只加载最长边 360 像素的缩略图，预览和保存标注都不会领取图片。下载原图才会进入防重流程。

打标时先用原图确认关键对象和易混读法，再在备注里写清它会改变哪个关系、参数或约束，以及哪个答案字段受影响。优先选择能把对象属性、配对或测距用到完整方案计数、优化或两工况比较中的方向。综合难度按一个具体方向预估。关键图证待核时在备注中指出位置，等级可以留空。[出题标注规则](ZeroBench图片标签与筛选实施方案.md#1-出题标注规则)

- `GET /api/tags/schema` 返回合法编码和中文说明。`PATCH /api/tags` 可用 `id`、`file_url` 或 `path` 三选一定位。省略字段保留原值，传 `[]` 或 `""` 可清空对应字段。[完整标注请求示例](ZeroBench图片标签与筛选实施方案.md#2-sqlite-与写入接口)
- `POST /api/tags/batch` 接受 `{"items":[...]}`，每项与单图标注请求相同，有错时整批回滚。旧数据库由服务启动时自动补列。手工在 SQLite 中标注时，多选编码按字母排序并用英文逗号分隔。
- `/api/images`、`/api/queue` 和 `/api/archive` 支持 `question_type`、`difficulty`、`difficulty_tag`、`tagged` 和 `match`。例如 `?question_type=counting,robust_ocr&difficulty=medium,hard&status=unclaimed` 筛出同时支持两种题型且属于中等或困难的未领取图片。`match=any` 改为在题型组和难点组内任选其一，两组之间仍同时满足。
- `POST /api/claims` 可按标签领取队列下一项，例如 `{"next":true,"claimer":"张三","question_types":["counting"],"difficulty":"hard"}`。打包使用 `claimed_by` 筛选已有领取人，`claimer` 指当前下载人。使用 `status=unclaimed` 可只打包未领取文件。

### 出题状态

`collection_queue` 与 `img_claims` 均保存 `authored_status` 和 `authored_ref`，服务启动时自动补齐旧库字段。图片列表、队列和图片元数据返回这两个字段。

- `authored_status` 接受 `""`（未出题）、`draft`（出题中）、`authored`（已出题）和 `discarded`（已淘汰）。`authored_ref` 保存题号或作者材料路径。
- `PATCH /api/tags` 可提交 `{"id":1,"authored_status":"authored","authored_ref":"ZB-001 | outputs/题目材料"}`，也可用 `file_url` 或 `path` 三选一定位。省略字段会保留原值，空字符串可清空。批量接口同样支持这两个字段。
- `/api/images`、`/api/queue`、`/api/archive` 及 `POST /api/claims?next=true` 支持 `?authored_status=draft` 等筛选。`?authored_status=` 和 `?authored=0` 只选未出题，`?authored=1` 只选已出题。省略筛选参数时返回所有出题状态。
- AI 和人工出题可使用 `POST /api/claims?authored=0`，请求体为 `{"next":true,"claimer":"作者名"}`，原子领取未出题图片。请求体也可传 `"authored_status":""`。领取后标记 `draft`，完成后写入 `authored` 和题目引用。
