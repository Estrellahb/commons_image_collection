# 单题质检：可验证项与人工缺口

`scripts/review_case.py` 是只读审核入口，不执行 `solver.py`/`oracle.py`，不调用模型或网络，不安装依赖，也不修改原题。标准库读取 PNG/JPEG 尺寸；其他图像格式仅尝试使用已安装的 Pillow。它不能从静态字段证明题目足够难、通过平台或具有唯一正确的科学解释。

```bash
python3 skills/zerobench-visual-benchmark/scripts/review_case.py \
  --case outputs/authoring_<题号> \
  --out outputs/_work/<题号>/review.json

python3 skills/zerobench-visual-benchmark/scripts/review_case.py \
  --case outputs/authoring_<题号> \
  --out outputs/_work/<题号>/review.json \
  --expected-model gpt-6.2-sol --expected-effort max
```

`--case` **原生支持直接审阅「`图片 + author_record.html`」单题交付目录**（`outputs/authoring_<题号>/`），同时兼容 `author.json`/`question.json` 等传统 JSON 用例格式。审阅报告输出到 `outputs/_work/<题号>/review.json`，不会写入 `outputs/authoring_<题号>/`，也不会覆盖已存在的报告。退出码 1 表示发现明确机器阻断项；退出码 0 仍然可能是 `needs_review`，绝不等于整题通过。

## 1. 交付目录契约与信息隔离

首先核对交付目录是否符合规范：

- `outputs/authoring_<题号>/` 下**严格只应存在 2 个文件**：`干净原图文件` + `author_record.html`；若夹带 `solver.py`、`facts.json`、`recompute.json`、`manifest.json`、`qa_report/`、`eval_4x.json` 等过程材料，应移回 `outputs/_work/<题号>/`。
- `author_record.html` 须自包含：基本信息表、原图与 1–3 个打点对照图、`prompt`、`thinking`、`cot_image_understanding`、`cot_reasoning`、`response`、逐字段判分口径、质检与复算摘要及一键复制按钮。

在泄露检查中，仅对**明确公开材料**（`prompt`、公开选项/候选、公开规则与输出要求，以及显式 `public` 块）进行答案泄露扫描；默认不把 `thinking`、两段作者解答、`response`、私有 `facts.json` 或 `solver.py` 注释当作公开泄露。

| 检查 | 自动处理 | 必须保留的边界 |
|---|---|---|
| 公开区包含答案/CoT 或直接写明真值 | `blocked` | 只针对公开字段或显式 `public` 对象，不扫作者字段误杀 |
| 公开候选 label/name/summary 写“真模型”“正确模型” | `blocked`，给字段与原文 | 题面要求“求唯一真模型编号”没有指明哪个候选，不因此判泄露 |
| 绘图脚本候选列表经循环变量流入 `text()` | `needs_review`，给调用行与值 | 只做静态数据流，仍须人工查看最终原图像素 |
| “忽略”“真实”“唯一”“混淆”等普通词 | 不触发硬拒绝 | “忽略完全遮挡物”“真实测量”“唯一答案”都是可能合理的规则 |
| 公开 PDB/COD/CID/DOI 等标识 | `needs_review` | 验证查库是否真正替代关键读图；许可署名或必要溯源不得随意抹除 |

脚本不做 OCR，未发现文本泄露不代表图上没有泄露；人工仍须用 100% 视图检查图片内容。

## 2. 覆盖率、诱饵数与私有计分

`N_cov92`、`N_decoy`、92% 阈值不是凭名称就禁止。真正要核对的是：这些字段能否完全由公开图像和公开规则唯一算出。必须公开或可从题图明确恢复全集、分母、权重、阈值边界、赢家是否纳入、缺失项处理和逐候选豁免；不能用作者侧私有清单或豁免字典补充评分。

## 3. 主图、图像尺寸与来源类型

- **彻底取消 1080p（`1080×1920`）及图片尺寸限制**：不再检查、警告或阻断 `1080×1920` 原生分辨率（包括 BBBC039 等低分辨率科学图均不再因像素尺寸被标记为 `blocked` 或告警）。
- **如实记录宽高与可辨性**：主图应清晰可读、坐标与比例真实；脚本与审核仅如实记录图像宽高（`W × H`）与来源/几何声明（如实拍照片、真实观测、科学数据渲染、题设示意、模拟观测、拼贴复合图），人工在 100% 原图下确认所有关键文字、刻度、边界或微细连接清晰可辨。
- 真实 PDB/CIF 数据绘制的结构图标明 `data_rendering` / `scientific_data_rendering`，须核对实验坐标、变换与图面可读性。混合来源面板须逐面板核对来源、授权与缩略映射。

## 4. `author_record.html` 平台字段与题意

- **1–3 个打点对照图**：`author_record.html` 中须展示干净原图与标注了 **1–3 个**关键证据点的对照图。检查坐标是否有限数字且落在 `0 ≤ x < W`、`0 ≤ y < H` 边界内；坐标在图内不代表指向正确笔画或对象，人工须核对打点准确且不遮挡被考特征。完整逐对象坐标留在 `outputs/_work/<题号>/facts.json`（或摘要中），不整批堆进对照图。
- **两段作者解答与复制按钮**：`thinking`、`cot_image_understanding`、`cot_reasoning`、`response` 及逐字段判分口径均须完整非空；第一段列出必要读图事实及干扰辨析，第二段从第一段推出关系、计算与标准答案；界面提供一键复制按钮。
- **题型**：主类对照八大题型枚举（计数聚合链、游戏／谜题规则求解、复杂指令遵循、小众知识解码、抗干扰文本读取、定位度量、拓扑／图结构追踪、空间变换）。
- **空集、并列与边界**：问最优值、赢家、路径或代表解时，人工核对空可行集、无路径、全被排除、等号归属、并列与输出编码是否公开唯一。
- **独立复算**：`outputs/_work/<题号>/solver.py` 与 `recompute.json` 须由作者运行核对（`review_case.py` 本身只读不运行代码）。

## 5. 测距、视觉依赖与复杂推理

逐问核对“对象/ROI → 读数 → 参数或关系 → 约束 → 输出”。高目标数、长题面或复杂计算不能替代真实视觉依赖。测距须明确端点、投影/标定物理/3D/路径类型、单位、比例与误差传递；检查所有关键阈值与全局分差，确认正常读图误差内答案稳定、而有图证的合理误配会导致所问字段改变（见 `outputs/_work/<题号>/recompute.json`）。

人工在原图 100% 下检查近色、遮挡、镜像、线交叉、层别、对象对应与关键短笔画。

## 6. 评测回执与难度判定核对

脚本关联 `outputs/_work/<题号>/eval_4x.json`（或历史 `evaluation/**/attempts/` 回执），核对模型、推理档与试答记录：

- **默认纯模型直调模式**：核对 `eval_4x.json` 中的请求与回显符合 `--model gpt-6.2-sol --effort max --trials 4`（`.env` OpenAI 兼容接口直调，**纯模型直答、不挂载本地代码工具**）。
- **难度合格标准**：4 次有效试答中**只要有 ≥ 1 次未答对（`incorrect >= 1`，即非 4/4 全对）即判定难度合格**；4/4 全对则需提难或淘汰（上限为初版后 v2/v3 两次实质返修）。
- 若检查的是历史或明确授权的开工具批次，须单独核对 `no_tools=false` 与 `tools_available`，不与纯模型直答结果混算。

| 回执情况 | 报告分类 | 可以得出的结论 |
|---|---|---|
| 完成、配置一致、判分正确 | `machine_correct` | 该轮机器判为正确 |
| 同条件下完整作答判分错误 | `machine_incorrect_candidate_requires_content_review` | 待审错答候选，核对 GT/题意/判分无误后计为有效 `incorrect` |
| 超时、断流、限流、残缺或用户中断 | `no_valid_complete_answer` | 无有效完整作答，不计入能力错误 |
| 末答解析歧义或等价表达待核 | `answer_needs_review` | 核对等价判分后再决定 |
| 模型/effort/配置证据不足或不匹配 | `protocol_unverified_or_mismatch` | 不计入目标配置的难度结论 |
| 缺回执或中途停止 | 保留缺口 | 不填成 0，不宣称测满 4 轮 |

## 输出判读

JSON 每个检查包含 `code/status/message/evidence`：`pass` 只表示该单项结构检查通过；`blocked` 表示明确的目录契约、公开泄露、缺字段或坐标越界冲突；`needs_review` 表示需人工核对。`review_case.py` 始终保持 `platform_accepted=false`、`difficulty_proven=false`（审阅脚本不替代人工图证复核与 4 次模型实测）。
