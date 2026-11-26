# 指标定义与输入约定

这些是筛选及复核指标，不是经过标定的难度预测器。数值阈值是本地初筛起点，平台原文没有给出的数值不要写成官方要求。不要把缺失值补成 0，也不要用加权总分抵消来源、不可辨认、答案泄漏等明确缺陷。

| 维度 | 程序输出/单位 | 怎样使用 | 不能据此断言 |
|---|---|---|---|
| 原图质量 | 原生 W×H、mode、EXIF、帧数 | 默认短边1080px以下复审；显微可设置领域阈值；16位先明确显示窗 | 放大图变清晰；1080是通用硬门槛 |
| 局部可辨认 | ROI p90−p10灰度对比、16灰阶梯度边缘比例、原生裁图 | 人工检查文字笔画、连接端点、关键色块在原生像素可分辨 | 高对比或高锐度即可辨认；小目标bbox宽就是特征宽 |
| 密集程度 | 目标数、框数/MP、bbox短边中位数/p10 | 货架可从80–200框、已知类≥12、已知比例≥0.85、中位短边≥40px开始召回 | 越多越难；大量相同重复目标足够 |
| 空间散布 | 4×4中心落格的 Shannon熵/4，范围[0,1] | 对比同类场景中分散程度 | 确定对象遮挡、远近层别 |
| 近色异类 | 邻居两框中心差按平均宽高分别归一化，距离≤1.8；中心60%颜色中位数转D65 Lab；ΔE76≤12 | 输出pair ID供人工核查；未知类别不参与异类判断 | 颜色心理阈值通用；复杂花纹能由中位色代表 |
| 堆叠候选 | bbox交面积/min(两框面积)≥0.15的对数 | 检索相交区域，再看谁遮谁、可见比例、镜像 | 矩形重叠就是物理遮挡；零重叠即无遮挡 |
| 中文覆盖 | 汉字文本框的精确矩形并集/图面积 | 5%为复核提醒，另外检查语义必要性及文本框完整性 | OCR未检出等于没有中文；任意中文都不允许 |
| 多源证据 | 关键ROI数、ROI→参数→输出边、不同区域数 | 人工审查每个关系是不是必要，第二步是否有独立证据 | 自动数出依赖边就证明必须多次识图 |
| 误配敏感性 | 作者复算的baseline与alternative输出差 | 要留混淆读法、影响字段、求解器记录；目标字段应改变 | 仅作者写passed即完成验证 |
| 测距裕度 | R=距最近决策边界的margin/总error_bound，同单位 | R>1是局部阈值稳健必要检查；考虑所有阈值和最终分差，联合扰动重算 | 一个阈值稳健就全题稳健；任意造一个error_bound |
| 同质化 | 显式scene_id分组、来源ID/图号/视频相邻帧 | 同场景整体管理；人工看内容重复，限制单来源比例 | 脚本完成视觉近重复检测 |
| 失败证据 | tools、题版、完整错误/超时/其他状态、轨迹引用 | 只有适用设置的完整可判分错误支持难度判断 | 超时或残缺答案是确认能力失败 |

全图灰度熵和边缘密度仅作描述，统一缩到最长边640计算。不可用跨分辨率的Laplacian方差统一设模糊阈值。ROI在原生大小计算；缩略图不用于测距。

## 测距的具体误差

若每个端点二维位置的欧氏误差≤e，线段长度误差≤2e；若每轴误差≤e，则长度误差≤2√2e。水平投影距离的两端横坐标误差各≤e时为2e。长度标尺、配准误差需加入传播；平方距离不直接沿用线性距离的2e。透视照片仅可默认问像素投影距离；问实际厘米须有同平面标定、透视修正或几何模型。

比较两个带误差的距离时，用距离差的总误差；比较优化赢家时检查可行集变化和最优分差，不能只检验单边。推荐采样可行误差域做作者复算，但采样本身不构成全域数学证明。

## 输入 manifest

UTF-8 JSON，顶层 `{"items":[...]}`。相对文件路径相对于manifest目录；坐标用原图左上原点，x向右y向下，浮点像素。图像EXIF非1先同时转换图和坐标再输入，脚本不会静默转向。COCO只读所指定image_id，不混用其他图。未填字段保留待审。

```json
{
  "items": [{
    "id": "shelf-001",
    "image": "images/original.jpg",
    "require_real": true,
    "allow_data_rendering": false,
    "min_native_short_px": 1080,
    "source": {
      "kind": "real_photo",
      "url": "https://publisher.example/item/001",
      "license_url": "https://publisher.example/license",
      "authorization": "pending",
      "scene_id": "publisher:scene001"
    },
    "annotation_provenance": "publisher_coco",
    "coco": "annotations/001.json",
    "image_id": 1,
    "critical_rois": [{"id":"r1","bbox":[20,30,80,60],"human_readable":null}],
    "ocr": {"han_bboxes":[],"reviewed":false},
    "platform_points": [{"xy":[60,60],"label":"相邻同色商品身份区别，作者关键点"}],
    "human_checks": {
      "source_fidelity":null,"annotation_correct":null,
      "critical_evidence_visible":null,"no_answer_leakage":null,"counting_rules_clear":null
    },
    "task": {
      "uses_distance":true,
      "dependencies":[{"roi_id":"r1","parameter":"origin_id","output":"distance_bin"}],
      "measurements":[{"id":"d1","margin":29,"error_bound":10,"unit":"px","error_method":"两个横坐标误差各5px","evidence":"author/measurement.md"}],
      "counterfactuals":[{"field":"reversal","baseline":true,"alternative":false,"verified":false,"evidence":"author/recompute.json"}],
      "bypass_review":"pending"
    },
    "evaluation": {
      "tools_enabled":true,"frozen_version":"v1",
      "counts":{"correct":0,"incorrect":0,"timeout":0,"infra_error":0,"partial":0},
      "trajectory":"","gt_review":"","failure_attribution":""
    }
  }]
}
```

`objects` 可替代COCO：`[{"id":"a","bbox":[x,y,w,h],"category":"sku-a"}]`。未知category填null。YOLO已有输出可离线转换：xc,yc,w,h乘图宽高，再转xywh，保留预测conf及模型名至旁车文件；预测类别必须人工核对，不作为最终GT。框不能超边界；脚本发现坏框会阻断，保留原标注另做明确修订。

`human_checks`、`verified`、`gt_review` 是人工声明，不是程序独立证明。审查者应打开其引用文件。`difficulty_status`不自动授予平台达标资格。CSV用于排序，JSON保留全部pair明细、缺口，HTML提供缩略图及逐项记录，ROI PNG供人工原生大小检查。

## 视频候选

视频记录来源与许可、原文件、时间戳PTS、帧号、分辨率、裁切和场景ID。已有ffmpeg时按时间抽帧，遇变帧率以PTS为准，不用帧号/fps推时差。先粗抽再按可读性、目标数和场景变化选少量帧；相邻帧不当独立题。光流、跟踪仅给匹配候选。遮挡穿越、跨视角身份需人工和上下文确认；没有深度或标定不问真实三维位移。此版CLI分析已抽出的帧，不自动下载、抽帧或调用检测模型。

## 可见边缘框

默认严格检查框是否在图内。若来源COCO有截断对象的越界框，可逐项显式填 `bbox_policy: "clip_visible"`：只为像素统计使用与图像范围的交集，在report.json记录original/visible坐标，保留原文件，并标为需复核。若问题问整物体中心或遮挡补全，不能用可见框中心替代原定义。当前货架示例用此策略处理1–2px边界溢出；首次严格检查结果另存report_raw。

## 多层联合推理图

可选 `task.reasoning_graph` 使用作者登记的DAG：`nodes`含`id`与`kind`（visual/measure/parameter/state/aggregate/optimize/output）；visual节点必须含实际`roi_id`；`edges`是`[from,to]`数组。状态机按轮展开，不写循环边。脚本计算最长节点深度、分支与合流节点数、多视觉源合流数、状态节点数、参数节点数、输出的视觉祖先覆盖率及每个输出依赖的ROI。重复节点、断边、环会报错。

这些数值描述所提交图的结构，不能证明因果必要性；加无用节点能刷高深度，所以必须结合删证据、替换参数及反事实复算。`branch_nodes`是出度>1，不等于条件分支种类或认知难度。单个图像事实可祖先覆盖所有输出但仍然很容易。22835示例附可运行的真实依赖图。
