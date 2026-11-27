# 图片指标、证据口径与离线检查

本页配合 `scripts/inspect_images.py`，用于筛候选与发现缺口。**图片质量、逻辑结构、来源适用性、实测难度分别判断，不合成一个难度分。** 未提供的数据输出 `null`（CSV 为空），不能补成 `0`。

## 先区分四个维度

| 维度 | 已有证据能回答什么 | 缺证据时怎么处理 |
|---|---|---|
| 来源 | 资产许可、真实观测/渲染/模拟、同源关系与修改范围是否明确 | 缺许可或性质不明为待审；明确不符合素材要求则阻断 |
| 图片 | 参与对象、必要特征及对应关系在原图上是否清晰可辨 | 框数、熵和像素宽高只是描述，**不设 1080p 或固定分辨率门槛**，人工核查关键证据可辨性 |
| 逻辑 | 读数怎样影响距离、取参、状态和目标字段，答案是否唯一可算 | 作者事实表、求解器和具体反事实缺一项就保留缺口 |
| 实测 | 固定版本与直调设置下是否发生有效错答（4 次中 `incorrect >= 1`） | 超时、服务失败、残缺答案、内容无效分别记录；不能填进有效错答数 |

`decision` 为 `blocked / needs_review / authoring_candidate / input_error`。`authoring_candidate` 只表示本次登记的检查没有未决项，不表示高难、平台通过或专家已验真。`difficulty_status` 独立记录试答材料状态；脚本不会因为一条人工填入的 `incorrect` 自动授予达标资格。

## 原生像素、几何声明与取消尺寸硬门槛

**本项目已彻底取消 1080p（`1080×1920`）原生分辨率及图片大小限制/阻断要求**：包括 BBBC039 等低分辨率科学图均不再因像素尺寸阻断或告警；脚本与记录仅**如实记录图像宽高（`width × height`）与关键证据的清晰可辨性**。

坐标统一指提交文件的左上原点，x 向右、y 向下，XYWH 浮点像素。`width/height` 与 `submitted_width/height` 表示当前提交文件尺寸。`image_geometry.kind` 有以下四种声明，未提供则 `unknown`：

| kind | 输入 | 输出/限制 |
|---|---|---|
| `native` | 声明文件就是本次取得的源采样，可附 `native_image` 或 `native_size_px` 核尺寸 | `native_width/height` 为文件尺寸。如实记录宽高即可，不因像素偏低阻断 |
| `crop` | `native_image` 或 `native_size_px`，以及 `source_crop_xywh` | 分别记源图尺寸、实际取样区域与缩放倍率；缺映射为待审 |
| `resized` | 同上；不裁切时可省 `source_crop_xywh` | 算 x/y 缩放比；放大只增加显示像素，非等比缩放需复审测距 |
| `montage` | `panels`，每面板有 `id/native_image/source_crop_xywh/output_xywh` | 全图 native 尺寸保持 `null`；每面板单记采样和缩放，画布和空白不能当新证据 |

原文件不便携时可填 `native_size_px`，输出会注明 `author_declaration`。原始图、裁剪、重采样、文字覆盖都保留变换记录。

全图像素描述使用最长边不超过 640 的缩略图，输出 `global_640_proxy`。关键 ROI 裁图按提交文件像素保存，标记 `pixel_metric_basis=submitted_pixels`；对裁剪、缩放、拼贴需确认 `native_readability_reviewed`。`feature_width_native_px` 是作者测量的关键笔画/连接宽度，不以整件商品框宽代替。16 位/浮点科学强度图（如部分显微原图）须先明确显示窗和显示图；脚本不把直接转 8 位的数值当有效成像质量指标。

## 多指标表

| 指标 | 计算与字段 | 使用边界 |
|---|---|---|
| 图像基础信息 | 提交尺寸 `submitted_width/height`、源采样尺寸、EXIF 方向、帧数、ROI 对比度 p90−p10、16 灰阶梯度边缘占比 | EXIF 方向未归一化会阻断；仅如实记录宽高，高对比、高熵、高像素都不证明关键证据可辨 |
| 标注总量 | `object_count`=有效框数；`objects_per_MP`=框数/提交图百万像素 | 是框的数量，未必是物理实体数；重复标注、群体框、镜像和包装照片均需辨析 |
| 参与目标密度 | 明确 `task.active_object_ids` 后给 `active_object_count`、`active_objects_per_submitted_MP`、`active_fraction_of_annotated_objects` | 未登记参与列表则全部为 `null`；背景有 200 件而题目只用 8 件不能报 200 个参与目标 |
| 参与区域密度 | 可选 `task.active_region_bboxes` 的矩形并集面积作为分母；所有参与中心须在区域内 | 输出 `active_objects_per_region_MP`，同时保留整张提交图密度，防止拼贴空白扭曲比较 |
| 真实实体数 | `entity_id` 跨视图统一时给 `active_entity_count`；非拼贴可明确 `object_unit=physical_instance` | 拼贴、镜像、另一视图再次出现不增加实体。作者身份声明仍需复核 |
| 背景量 | `inactive_annotated_count`=已标注而不参与的框数 | `background_object_count` 仅在 `annotation_complete=true`、物理实体口径且非拼贴时给值；否则 `null` |
| 类别与粒度 | 已知类数、已知比例、重复类数、参与已知类数 | `category_level=verified_task_classes/verified_sku` 才表示按本题区分口径审过 |
| 空间散布 | 目标中心落入 4×4 格，Shannon 熵除以 4，范围 `[0,1]` | 描述分散程度，不表示深度、遮挡或认知难度 |
| 局部近色异类 | 相邻不同已知类；中心差按平均宽高归一化≤1.8；中心 60% 区域中位 RGB 转 D65 Lab，ΔE76≤12 | 仅输出混淆候选对；可给对象 `color_roi` 指定真正有用色块。花纹和反光仍需看图 |
| 框相交与重复候选 | 交面积/较小框面积≥0.15 输出 `overlap_candidates`；IoU≥0.85 输出 `duplicate_bbox_candidates` | **框重叠不是遮挡。** 高 IoU 也可能属于不同投影或标签，脚本不自动合并 |
| 标注遮挡率 | 仅当所有已标框均有布尔 `occluded` 时给 `annotated_occlusion_fraction` | 是所给标注的比例，不是像素自动推断。部分未知时总比例为 `null` |
| 中文覆盖 | `ocr.han_bboxes` 精确矩形并集/面积；5% 给复审提醒 | 没有 OCR 框字段为 `unknown`；显式空列表仅表示本次登记未检出，还需人工审查 |
| 图证依赖 | ROI→参数→输出边、不同区域数、作者提供 DAG 的深度/合流/祖先覆盖 | 多问、多节点不证明更难；须核对各步是否消费真实图证 |
| 反事实作用 | 有 `evidence`、`verified=true` 且目标字段 `baseline≠alternative` 的已登记记录数 | 作者需在 `outputs/_work/<题号>/recompute.json` 实际复算 |
| 测距裕度 | `margin/error_bound`，相同单位，≤1 阻断阈值不稳健 | 一个局部阈值稳健不等于全局优化稳健；所有相关阈值、可行集和最终分差都要检查 |
| 同源关系 | 显式 `scene_id`、`source_asset_id`、`video_id`/PTS 分组 | 用于在本地 `采集数据.sqlite` 与 `outputs/` 中识别同源重裁或邻近帧 |

## 测距误差与因果复算

两端各有二维欧氏定位误差 ≤ `e`，则长度误差 ≤ `2e`；每轴误差 ≤ `e`，则上界为 `2√2e`。横向投影距离两端横坐标各误差 ≤ `e`，上界为 `2e`。标尺、配准和透视校正误差另传播；平方距离不能沿用长度的 `2e`。透视照片默认只能量像素投影，实际厘米须同平面标定或公开几何模型。

比较距离差时合并两项误差；优化赢家要检查错误是否改变可行集合及分差。要求“正常读图误差不改变判分；合理错配改变所问字段”，不把阈值放在不可辨认区间制造伪难。

## manifest 与运行

上游选图可先通过 `python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py list/claim` 从 `采集数据.sqlite` 和 `来源与许可.jsonl` 获取候选与来源元数据（同样不卡图片尺寸）。

`manifest.json` 为 UTF-8 JSON，顶层 `{"items":[...]}` 或列表，相对路径从 `manifest.json` 所在目录解析。在当前 Linux `python3` 环境直接使用现有 Pillow/NumPy 运行，不安装 YOLO/OpenCV，不下载权重、图片或调用模型：

```bash
python3 skills/zerobench-visual-benchmark/scripts/inspect_images.py \
  outputs/_work/<题号>/manifest.json \
  --out outputs/_work/<题号>/qa_report
```

注意：`manifest.json` 与 `qa_report/` 均属于过程材料，必须放在 `outputs/_work/<题号>/`，不得写入最终交付目录 `outputs/authoring_<题号>/`。

最小候选记录示例（示例只表达格式，不能将待审项批量改 `true`）：

```json
{
  "items": [{
    "id": "shelf-example",
    "image": "../../authoring_shelf-example/photo.jpg",
    "image_geometry": {"kind": "native"},
    "require_real": true,
    "source": {
      "kind": "real_photo",
      "url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
      "license_url": "https://creativecommons.org/licenses/by/4.0/",
      "authorization": "pending",
      "scene_id": "commons:scene-1",
      "source_asset_id": "commons:123456"
    },
    "annotation_provenance": "author_candidate_boxes",
    "annotation_complete": null,
    "category_level": "publisher_unverified",
    "objects": [
      {"id": "a", "entity_id": "physical-a", "bbox": [10, 20, 80, 150], "category": "sku-a", "occluded": null},
      {"id": "b", "entity_id": "physical-b", "bbox": [110, 20, 80, 150], "category": null, "occluded": null}
    ],
    "critical_rois": [{"id": "r1", "bbox": [10, 20, 180, 150], "human_readable": null}],
    "task": {
      "active_object_ids": ["a", "b"],
      "active_region_bboxes": [[0, 0, 200, 200]],
      "dependencies": [{"roi_id": "r1", "parameter": "pair_identity", "output": "edge_count"}],
      "uses_distance": true,
      "measurements": [{"id": "d1", "margin": 29, "error_bound": 10, "unit": "px", "error_method": "两端横坐标各5px", "evidence": "recompute.json"}],
      "counterfactuals": [{"field": "reversal", "baseline": 1, "alternative": 0, "verified": false, "evidence": "recompute.json"}],
      "bypass_review": "pending"
    },
    "platform_points": [{"xy": [50, 50], "label": "对象a身份与中心，作者关键证据点"}]
  }]
}
```

COCO 可用 `coco` 路径及唯一 `image_id` 替代 `objects`。默认越界框阻断；明确设置 `bbox_policy=clip_visible` 后只为统计使用交集并记原/新坐标，仍待审。对象和 ROI 坐标必须和图片 EXIF 方向一致。

`human_checks` 支持 `source_fidelity`、`annotation_correct`、`critical_evidence_visible`、`no_answer_leakage`、`counting_rules_clear`，各为 `true/false/null`。平台打点只取 1–3 个关键位置，作者全量事实表另存 `outputs/_work/<题号>/facts.json`。

`evaluation.counts` 的 `correct/incorrect` 必须是**已排除内容和基础设施无效后的完整可判分试次**。输出 `report.json`、`metrics.csv`、`index.html`、缩略图及 ROI PNG 均留在 `outputs/_work/<题号>/qa_report/`。退出码 2 表示输入无法处理；退出码 0 也可能有 `blocked/needs_review`，调用者必须读报告，不能把命令成功当题目通过。

## 视频帧

保存原视频、许可、`video_id`、`scene_id`、时间戳 PTS（秒）、帧号、分辨率和裁剪映射。变帧率用 PTS，不用 frame/fps 冒充真实时差。先粗抽，再在有变化的镜头内选可读帧；同一小段的相邻帧按同源管理。CLI 仅检查已存在的帧，不会自动下载或抽帧。
