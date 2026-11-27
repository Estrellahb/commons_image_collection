# 图片指标脚本迁移与实际运行记录

只改统一 skill 的 scripts/inspect_images.py、references/image-metrics.md、references/sources.md；旧 skill 未修改/删除。程序沿用 Pillow/NumPy 的成熟离线指标，没有下载新素材、安装检测模型或调用评测 API。

旧 20 项 manifest 实际运行：15 needs_review、5 blocked、0 input_error。5 个 blocked 均是已有素材性质与 require_real 要求不符。旧清单没有参与对象列表和可靠的原生映射，新版对此输出 null/待审，没有把全部框当参与对象或把提交文件尺寸当原生尺寸。

补充运行使用已经落盘的 C40-01/v2 真货架照片与实际拼贴题图：发布方框 118 个，题目参与目标 18 个。原图 1200×1600，题图 1960×1600；整图参与密度分别 9.375 与 5.7398/MP，而相同有效照片区域均为 9.375/MP。拼贴总 native_size=null，每个面板保留原图采样和缩放映射。遮挡标注缺失与全背景覆盖不明均保持 null。

实际运行中发现原有比例判断会把 78×210 缩略为 74×200 的整数舍入误报为非等比变形，已按半像素舍入上界修正，并重新运行同一现有清单确认。两项仍为 needs_review，未伪填人工可读、类粒度、许可/来源复审、反事实或实测通过。

输出分别在 inspection_existing_manifest/ 与 inspection_worked/，包含 HTML、JSON、CSV 和原像素 ROI。inspection_worked_manifest.json 使用现有本地绝对路径，是本次可复查运行材料；不是可在别的机器直接运行的自带图片示例。详细数值见 image_metrics_execution_receipt.json。

脚本限制：实体/类/遮挡/参与关系仍依赖输入与作者复核；没有自动语义识别、许可证法律判定、视觉近重复识别或难度预测。已有 YOLO 输出可转换输入，但脚本不启动 YOLO。所有 unknown 保留 null，0 仅为明确范围内的已知零。
