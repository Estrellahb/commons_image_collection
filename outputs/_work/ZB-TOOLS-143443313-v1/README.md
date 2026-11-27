# ZB-TOOLS-143443313-v1

已冻结 1 道实拍多属性取件题，公开题面含 5 问。

平台单选题型选「计数聚合链」。项目题型标签另登记复杂指令遵循、定位度量、抗干扰文本读取。

- 答题材料位于 public，包括 image.jpg、prompt.md 和 attribution.md。
- 作者事实表、平台 3 个关键点、逐字段标准答案与作者解答见 author/author_record.json。
- 图片质检结论和人工复核依据见 author/qa_review.md，浏览 qa_report/index.html 可查看指标。
- 运行 `python3 solver.py > recompute.json` 重算全部 baseline 与 alternative。
- 运行 `python3 author/verify.py` 用逐排选对方法独立核验全部答案字段。
- 数据库状态写入凭据见 author/database_update.json。

标准答案为 `5,25,29,5|83|1692|3,5,2,2|3,6,3,010610,040509`。

本地质检达到 authoring_candidate。模型试答与平台难度实测状态为未测试。外部难题300排除清单未随项目提供，已核对当前数据库、本地技能样例和同场景加尺派生版。队列 316 的加尺派生版与 107 的原图共用题目引用，以防同场景重复出题。
