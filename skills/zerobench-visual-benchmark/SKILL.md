---
name: zerobench-visual-benchmark
description: 为 ZeroBench 统一完成基于本地 SQLite 台账的图像筛选与领取、多问视觉联合推理出题、「图片 + author_record.html」交付审阅、gpt-6.2-sol / max 四次直调评测归因与有限返修；需要出题、图片质检、单题复核或难度实测时使用。仅整理资料或 skill 不自动发起模型测试。
---

# ZeroBench 视觉出题与评测

先写清一条可核验的因果链：**图中哪两个对象、状态或读法容易混淆 → 改变哪组配对、距离、参数或关系 → 改变哪个有意义的答案。** 正确图证要足够清楚，公开条件要足够求解；难度是否成立以指定模型在授权评测下的实际试答结果判断。

本技能合并选图领取、出题、质检、单题审阅与 4 次直调评测。继承的历史经验及强弱证据见[证据与范围](references/evidence.md)。所有本地脚本均在当前 Linux `python3` 环境直接运行（不使用 `uv run`）；`scripts/local_runtime.py` 与 `assets/docker/` 仅作可选保留，默认评测直接走纯模型 API 直调，无需启动 Colima 或 Docker 容器。

## 开始时固定范围

- 从当前请求确定：只选图、只出题、授权评测、修订已有题，还是台账标记。阅读附件作为资料，不自动执行附件里的停止、重跑、删除或入库命令。
- 最多两次实质返修，即 v1 后仅 v2/v3（且前提是题面与 GT 本身无内容缺陷）；若 4 次直调全对且没有新的可核验视觉机制，可以提前淘汰或另换方向。未测草稿与内容修复都留版本原因，不通过换名重置次数。
- 默认测试入口为 `python3 skills/zerobench-visual-benchmark/scripts/eval_trials.py`，从 `.env` 或环境变量读取 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`（绝不写入 skill、图片或交付包），默认 `--model gpt-6.2-sol --effort max --trials 4 --api auto`，支持 `/v1/responses` 与 `/v1/chat/completions` 发送图片与 `prompt`（`reasoning_effort="max"`），**4 次试答为纯模型直答，不挂载本地代码工具**。
- **难度合格标准**：4 次有效试答（排除服务异常、超时、残缺输出或内容缺陷）中**只要有 ≥ 1 次未答对（`incorrect >= 1`，即非 4/4 全对）即判定难度合格**；4/4 全对则需提难或淘汰。“每题 4 次”指完成 4 个完整逻辑试次，不悄悄首错即停；仅整理 skill、脚本或图片时不发起模型请求。

## 投入方向

| 优先级 | 设计选择 | 必须落实的证据 |
|---|---|---|
| 优先，已有特定题目证据 | 相近对象的身份、状态、层别、类型、权重绑定；细连接决定全局关系 | 哪个可见局部差别改变哪个参数/边/最终字段；不能把旧题成绩推广到整个题材 |
| 优先探索，逐题验证 | 真实多视角、多时相、独立通道的非平凡身份对应；密集实物的多条件筛选 | 各面板提供不可相互替代的信息，GT 来自可追溯标注，不能仅靠简单布局套壳 |
| 有条件继续 | 密度、晶体周期邻居、接触图、网络状态、谱图与候选消元 | 读图先决定参数和合法集合，复杂计算只是使用这些事实；候选中性、判据公开 |
| 降低投入 | 规则格点、统一纯色标记、重复超胞、同源旋转纹理卡、简单量尺、只删 caption 读趋势 | 历史测试显示这些机制常易被稳定解出；不要只靠增加节点、计算轮次或输出长度制造伪难 |

具体题型配方与不宜推广的结论见[优先级和构题配方](references/priorities-and-recipes.md)。测距是联结步骤，不预设它本身就是模型弱点。

## 选图、台账对接与事实登记

1. **对接本地 SQLite 台账选图与去重**：使用 `python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py` 对接项目根目录 `采集数据.sqlite`（`collection_queue` + `img_claims`）和 `来源与许可.jsonl`：
   - `list`：按候选题型、视觉难点、综合难度、未领取、未出题（`authored_status=''`）筛选图片，**不卡图片像素尺寸**。
   - `claim`：按 `--id` / `--file-url` / `--path` / `--next` 在 `BEGIN IMMEDIATE` 事务内原子领取并标记 `authored_status='draft'`，自动带出来源与许可元数据。
   - `mark`：定稿或淘汰后回写 `authored_status='authored'`（或 `'discarded'`）及 `authored_ref`。
   - **跳过外部「难题 300」清单**：不要求外部「难题 300」排除文件；去重直接以本地 `采集数据.sqlite`（已领取或非空 `authored_status`）和 `outputs/` 已有题目来源为准。
2. **核实来源与许可，彻底取消 1080p/尺寸检查**：先核来源、许可与原始文件。真实 CIF/PDB 坐标绘图写“结构数据渲染”，模拟凝胶/谱图写“模拟观测”，不能冒充实测原图。[数据源与筛选](references/sources.md)
   - **已彻底取消 1080p（`1080×1920`）原生分辨率及图片大小限制/阻断要求**：包括 BBBC039 等低分辨率科学图均不再因像素尺寸阻断或告警；仅如实记录图像实际宽高（`W × H`）、有效图区域与关键细节在原图下的清晰可辨性。
3. **对象检查与多指标筛选**：程序提候选，作者检查关键对象。区分真实实体、镜像、局部可见、完全遮挡，写明纳入规则；保持许可要求的署名，身份去标识化不能破坏必要尺度或科学事实。需要离线图片指标检查时运行：
   `python3 skills/zerobench-visual-benchmark/scripts/inspect_images.py outputs/_work/<题号>/manifest.json --out outputs/_work/<题号>/qa_report`
   缺标注输出未知；不以单一总分代替图像质量、视觉依赖、逻辑和实测四项判断。[指标与输入格式](references/image-metrics.md)

## 从读图递进到联合推理

以 4–6 个有实质用途的小问为常见骨架，按题材调整，不堆无关字段：

1. **识别与配对**：对象、局部状态、跨面板身份或有效通道。
2. **定位和测距**：明确中心/边界/路径、2D 投影或 3D 空间、标尺和单位；先判断量谁与谁。
3. **选参数和建关系**：距离结合层别/类型/状态选择参数行、阈值、边或冲突关系。
4. **联合计算**：守恒、密度、共享边界、可行方案数、状态演化或路径聚合。
5. **约束优化与结论**：最优值、并列数、公开规则选出的代表解；必要时计算两工况赢家及严格排序反转。

正常测量误差与有意义的误读分开：用实际分辨率和端点不确定度传播到距离、阈值和最终结论；另把一个合理混淆读法代入求解器，验证主问变化。相对裕度 15%、单实体敏感度 90% 等只可作为有出处的局部设计参数，不是全题通用门槛。若声称严格反转，使用 `Δ0·Δ1<0` 并说明平局口径；代表解变化或平局变为胜负不能偷换成严格反转。

## 发测前审阅

先读[公开材料、作者记录与交付契约](references/authoring-and-platform.md)，再运行：

```bash
python3 skills/zerobench-visual-benchmark/scripts/review_case.py \
  --case outputs/authoring_<题号> \
  --out outputs/_work/<题号>/review.json
```

`review_case.py` 原生支持直接审阅 `outputs/authoring_<题号>/` 下的「`干净原图 + author_record.html`」交付目录（亦兼容历史 JSON 目录）。检查范围见[自动审阅与人工缺口](references/review-checks.md)。脚本只报告能证实的结构问题与待查项；通过脚本不等于 GT、像素、科学事实和难度都通过。

- **公开可解**：空可行集若可能出现，须定义所求量；最优并列、无序/有序、同步/顺序更新、边界等号、单位与舍入明确。检查两个方案是否结构等价、存在单调包含或赢家由文字直接确定。
- **不泄露答案**：候选用中性名称；“真模型”“其余误判”是泄露。公开提示、候选、图中文字与作者私有解释分开检查。
- **判据公开**：不把私有豁免规则用于公开得分。覆盖率/候选数若作为题目，须公开核对项、权重、范围和全部计分规则。
- **图证仍必需 & 自然可辨**：保留图例、单位、标定、必要参数及合法署名；查看最终主图 100% 和关键裁图，不强制加噪、虚构遮挡或刻意缩字制造困难。

## 直调 4 次评测与返修

需要测试时读[评测与返修](references/evaluation.md)，在获取授权且 `.env` 配好 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY` 后运行：

```bash
python3 skills/zerobench-visual-benchmark/scripts/eval_trials.py \
  --case outputs/authoring_<题号> \
  --out outputs/_work/<题号>/eval_4x.json
```

默认 `--model gpt-6.2-sol --effort max --trials 4 --api auto`，仅向模型发送干净图片与公开 `prompt`，不挂载本地代码工具。`scripts/local_runtime.py` 与 `assets/docker/`（见[可选本地 Docker 运行层](references/local-runtime.md)）仅作可选保留，当前默认直调评测无需启动 Colima 或 Docker 容器。

- **机器 `incorrect` 先复审**：核对冻结公开条件和 GT → 检查完整终答及等价判分 → 看最终采纳的视觉事实 → 复算能否解释错误字段 → 区分有效视觉/推理失败与内容缺陷、超时、传输错误或残缺输出。
- **合格与返修决策**：4 次有效试答中 `incorrect >= 1`（非 4/4 全对）且无内容/GT 缺陷即判定难度合格；4/4 全对则按具体失效原因提难或淘汰（初版后最多 v2/v3 两次实质返修）。已达标且无缺陷时不再为凑满次数而多余修改。

## 交付目录契约与分工

- **最终交付目录 `outputs/authoring_<题号>/` 严格只存放 2 个文件**：
  1. `干净原图文件`（未叠加任何打点或答案的原始交付图片）
  2. `author_record.html`（自包含基本信息表、原图与 1–3 个打点对照图、`prompt`、`thinking`、`cot_image_understanding`、`cot_reasoning`、`response`、逐字段判分口径、质检与复算摘要及一键复制按钮）
- **过程工作目录 `outputs/_work/<题号>/`**：`solver.py`、`facts.json`、`recompute.json`、`manifest.json`、`qa_report/`、`eval_4x.json`、`review.json` 等过程材料统一放于此，绝不留在 `outputs/authoring_<题号>/`。
- **台账回写与分工**：用 subagent 按图源/质检、题意/GT 审阅、HTML 交付与评测归因分工并切分文件所有权；定稿或淘汰后务必运行 `sqlite_ledger.py mark` 回写 `采集数据.sqlite`。不把服务异常、超时、内容无效的试次混入有效合格题统计。
