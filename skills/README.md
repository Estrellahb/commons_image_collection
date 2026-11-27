# ZeroBench 统一出题、台账选图、质检与直调评测 Skill

当前活跃 Skill 入口为 [zerobench-visual-benchmark](zerobench-visual-benchmark/SKILL.md)，并已配置两处自动发现软链指向本目录的 `zerobench-visual-benchmark/`：

- `.agents/skills/zerobench-visual-benchmark`
- `~/.codex/skills/zerobench-visual-benchmark`

旧版 `zerobench-visual-authoring`、`ZeroBench_图片指标质检_20261126` 及历史压缩包已统一归档至 `skills/retired-skills-20261127.zip`，不再参与 Skill 自动发现；`skills/execution_records/` 保留历史执行记录。

## 当前工作区核心约定

1. **直接运行 Linux `python3`，无需 Docker/Colima**：所有命令示例统一直接使用 `python3 ...`（不依赖 `uv run`）。`scripts/local_runtime.py` 与 `assets/docker/` 仅作可选保留，默认评测通过纯模型 API 直调完成，无需启动 Colima 或 Docker 容器。
2. **SQLite 台账选图，跳过外部「难题 300」，彻底取消 1080p/尺寸检查**：
   - 通过 `scripts/sqlite_ledger.py` 直接对接项目根目录 `采集数据.sqlite`（`collection_queue` + `img_claims`）和 `来源与许可.jsonl`，支持 `list` / `claim` / `mark`。
   - 去重直接以本地 `采集数据.sqlite`（已领取或非空 `authored_status`）和 `outputs/` 已有题目来源为准，不要求外部「难题 300」排除文件。
   - **已彻底取消 1080p（`1080×1920`）及任意图片尺寸限制/阻断**（包括 BBBC039 等低分辨率科学图均不再因像素尺寸阻断或告警），仅如实记录图像宽高与清晰可辨性。
3. **单题交付目录契约（「仅 `图片 + author_record.html`」）**：
   - 最终交付目录 `outputs/authoring_<题号>/` **严格只存放 2 个文件**：`干净原图文件` + `author_record.html`（HTML 内自包含基本信息表、原图与 1–3 个打点对照图、`prompt`、`thinking`、`cot_image_understanding`、`cot_reasoning`、`response`、逐字段判分口径、质检与复算摘要及一键复制按钮）。
   - `solver.py`、`facts.json`、`recompute.json`、`manifest.json`、`qa_report/`、`eval_4x.json`、`review.json` 等过程材料统一只放在 `outputs/_work/<题号>/`。
4. **`.env` OpenAI 兼容接口直调 4 次评测与合格标准**：
   - 从 `.env` 或环境变量读取 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`。
   - 默认参数为 `--model gpt-6.2-sol --effort max --trials 4 --api auto`（兼容 `/v1/responses` 与 `/v1/chat/completions` 发送图片与 `prompt`，`reasoning_effort="max"`），**4 次试答为纯模型直答，不挂载本地代码工具**。
   - **难度合格标准**：4 次有效试答（排除服务/超时/残缺/内容缺陷）中**只要有 ≥ 1 次未答对（`incorrect >= 1`，即非 4/4 全对）即判定难度合格**；4/4 全对则需提难或淘汰（初版后保留最多 v2/v3 两次实质返修上限，前提是题面与 GT 本身无内容缺陷）。

## 脚本清单（`zerobench-visual-benchmark/scripts/`）

| 脚本 | 用途 | 关键特性 |
|---|---|---|
| `scripts/sqlite_ledger.py` | 对接 `采集数据.sqlite` 与 `来源与许可.jsonl` | `list` 按题型/难点/难度/未领取/未出题筛选（不卡尺寸）；`claim` 在 `BEGIN IMMEDIATE` 事务内原子领取并标记 `draft`；`mark` 回写 `authored`/`discarded` 与 `authored_ref` |
| `scripts/inspect_images.py` | 离线图片与 ROI 多指标质检 | 使用现成 Pillow/NumPy，不安装模型依赖、不设 1080p 阻断；生成 `report.json`、`metrics.csv`、`index.html` 与 ROI 裁图到 `outputs/_work/<题号>/qa_report/` |
| `scripts/review_case.py` | 只读单题交付审阅 | 原生支持直接审阅 `outputs/authoring_<题号>/` 下的 `图片 + author_record.html`（亦兼容 JSON 目录），输出至 `outputs/_work/<题号>/review.json`；不运行求解脚本或模型 API |
| `scripts/eval_trials.py` | `.env` 直调 4 次评测 | 读取 `OPENAI_BASE_URL` / `OPENAI_API_KEY`，默认 `gpt-6.2-sol / max / 4 trials / --api auto` 纯模型直答，输出 `outputs/_work/<题号>/eval_4x.json` |
| `scripts/local_runtime.py` | 可选本地 Docker 工具运行层（保留未动） | 与 `zerobench-visual-benchmark/assets/docker/` 共同作为可选隔离容器参考；默认直调评测无需启用 |

## 常用命令速查（在项目根目录执行）

```bash
# 1. 查看未领取且未出题的候选图片（不卡分辨率）
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py list --unclaimed --unauthored

# 2. 原子领取一张候选图片并获取来源与许可元数据（自动写入 authored_status='draft'）
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py claim --next --claimer <作者名>

# 3. 离线图像与指标质检（产物写入 _work 目录）
python3 skills/zerobench-visual-benchmark/scripts/inspect_images.py \
  outputs/_work/<题号>/manifest.json --out outputs/_work/<题号>/qa_report

# 4. 只读审阅最终交付目录（图片 + author_record.html）
python3 skills/zerobench-visual-benchmark/scripts/review_case.py \
  --case outputs/authoring_<题号> --out outputs/_work/<题号>/review.json

# 5. 纯模型直调 4 次评测（读取 .env 中 OPENAI_BASE_URL 与 OPENAI_API_KEY）
python3 skills/zerobench-visual-benchmark/scripts/eval_trials.py \
  --case outputs/authoring_<题号> --out outputs/_work/<题号>/eval_4x.json

# 6. 定稿或淘汰后回写 SQLite 台账
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py mark \
  --id <ID> --status authored --ref "<题号> | outputs/authoring_<题号>"
```

## 文档导航

- 核心工作流总览：[SKILL.md](zerobench-visual-benchmark/SKILL.md)
- 交付契约、`author_record.html` 规范与平台字段：[authoring-and-platform.md](zerobench-visual-benchmark/references/authoring-and-platform.md)
- 4 次直调评测、错答归因与返修规则：[evaluation.md](zerobench-visual-benchmark/references/evaluation.md)
- SQLite 台账、图源与许可核验：[sources.md](zerobench-visual-benchmark/references/sources.md)
- 图像指标与误差传播：[image-metrics.md](zerobench-visual-benchmark/references/image-metrics.md)
- 自动审阅项与人工边界：[review-checks.md](zerobench-visual-benchmark/references/review-checks.md)
- 投入优先级与领域构题配方：[priorities-and-recipes.md](zerobench-visual-benchmark/references/priorities-and-recipes.md)
- 历史实测证据与边界：[evidence.md](zerobench-visual-benchmark/references/evidence.md)
- 可选本地 Docker 运行层说明：[local-runtime.md](zerobench-visual-benchmark/references/local-runtime.md)
