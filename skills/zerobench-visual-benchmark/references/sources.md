# 图源、授权、台账领取与筛选

本页合并本地台账操作、外部图源指南与素材筛选规范，服务于“必要视觉配对 → 测距/选参 → 联合计算”。**本项目已彻底取消 1080p（`1080×1920`）原生分辨率及图片尺寸阻断要求**，并**跳过外部「难题 300」清单**。

## 1. 对接本地 SQLite 台账（`sqlite_ledger.py`）

在本项目中，选图、防重、领图与出题状态回写统一通过 `python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py` 对接根目录 `采集数据.sqlite`（`collection_queue` + `img_claims` 两张表）和 `来源与许可.jsonl`：

```bash
# 1) 筛选未领取、未出题候选（支持按题型、难点、难度组合筛选；不卡图片像素尺寸）
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py list \
  --question-type counting --difficulty medium,hard --unclaimed --unauthored

# 2) 在 BEGIN IMMEDIATE 事务内原子领取并标记 authored_status='draft'，带出来源与许可元数据
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py claim \
  --next --claimer <作者名> --question-type counting
# 也可按 --id <ID>、--file-url <URL> 或 --path <相对路径> 精确领取

# 3) 定稿或淘汰后回写台账（authored_status='authored' 或 'discarded'）与 authored_ref
python3 skills/zerobench-visual-benchmark/scripts/sqlite_ledger.py mark \
  --id <ID> --status authored --ref "ZB-XXXX-v1 | outputs/authoring_ZB-XXXX-v1"
```

- **去重规则（跳过外部「难题 300」清单）**：不要求外部「难题 300」排除文件；直接以本地 `采集数据.sqlite`（已领取 `claimed_by` / 非空 `authored_status`）和 `outputs/` 下已有题目的来源记录（`outputs/authoring_*`、`outputs/_work/*`）完成去重。
- **不卡像素尺寸**：`list` 与 `claim` 均不以图像分辨率作为筛选或阻断条件；领取时从 `来源与许可.jsonl` 带出宽高、来源页、作者与许可条款，出题前只需人工查看原图确认关键细节清晰可辨。

## 2. 按素材类型选外部入口

| 方向与投入 | 官方/发布方入口 | 可以先筛什么 | 取图后必须补什么 |
|---|---|---|---|
| 优先候选：密集真实货架 | [ShelfWise SKUs_on_shelves_PL](https://huggingface.co/datasets/shelfwise-by-form/SKUs_on_shelves_PL) | 发布方 COCO 框、类别与记录 ID；相邻多类、框尺寸分布 | 图内是否真的可区分类别，品牌级/包装改版/容量差异；重复框、价签归属、参与目标、自然遮挡 |
| 优先候选：一般密集实物 | [Google Open Images V7](https://storage.googleapis.com/openimages/web/download_v7.html) | 类别、框、部分掩膜及关系，遮挡/截断/群体/描绘物标记 | 参与对象与干扰对象共现，真实实体合并，关键部件可辨、单图许可 |
| 优先候选：密集细胞与真实序列 | [BioImage Archive](https://www.ebi.ac.uk/bioimage-archive/help-search/) / [IDR](https://idr.openmicroscopy.org/about/api.html) | 实验/研究/物种/通道与样本元数据；字段依研究不同 | 正确的样本、通道、z、t 轴和尺度，真实连续关系、分割与身份标注 |
| 已有明确标注的核图 | [BBBC039](https://bbbc.broadinstitute.org/BBBC039) | 单通道核图与实例掩膜；可本地算邻接、紧邻与密度 | 不是时序/Z-stack；掩膜编码要正确，贴连核不能用简单二值连通域代替 |
| 密集计数候选 | [FSC-147 作者仓库](https://github.com/cvlab-stonybrook/LearningToCountEverything) | 目标类点标注与示例框 | 点不提供全部物类、遮挡层别或物体框；逐图核资产授权，不能从代码 MIT 推图片 MIT |
| 仪器、标本、纹样和器材 | [Wikimedia Commons](https://commons.wikimedia.org/wiki/Help:Searching) / [Smithsonian Open Access](https://www.si.edu/openaccess/faq) | 关键词、分类、文件或馆藏元数据 | 真实多部件而非文字占位图、标尺与关键接口、具体媒体的许可与实际宽高 |
| 真实多时相遥感 | [Google Earth Engine](https://developers.google.com/earth-engine/guides/ic_filtering) | AOI、日期、传感器、集合字段及整景云量 | 目标处云/阴影、清晰可辨性、同区配准、可唯一身份绑定、波段/导出参数和集合条款 |
| 科研原图和配套论述 | [PMC Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/textmining/) / [Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/cloud/) | 主题、文章许可、XML 图号/caption/媒体 | 具体面板图证、改图范围、第三方引用图许可、是否泄露答案 |
| 结构数据绘图，选择性投入 | [COD](https://www.crystallography.net/cod/search.html) | 元素、化学式、空间群、晶胞参数与论文；取 CIF 后筛不等价位点/占位 | 实验或理论来源、对称展开与周期、真实结构与假设状态分开 |
| 蛋白结构数据绘图，选择性投入 | [RCSB PDB](https://www.rcsb.org/) / [PDBe](https://www.ebi.ac.uk/pdbe/) | 分子、实验方法、链/组装等记录 | assembly/model/altloc、缺残基、接触定义；屏幕投影不是 Å，结构渲染不是照片 |
| 密集星场 | [SDSS 图像政策](https://sdss.org/collaboration/image-use-policy/) / [Gaia Archive](https://gea.esac.esa.int/archive/) | 天区、波段、观测与星表条目 | WCS、历元、饱和和混合源，星表记录不等于可见亮点；两个项目许可分别核 |
| 工程网络，允许题设绘图时 | [PGLib-OPF](https://github.com/power-grid-lib/pglib-opf) / [WNTR](https://usepa.github.io/WNTR/) | 真实/公开测试网络文件的节点和属性 | 网络示意布局不是实拍；绘图距离不是管长或线路长，连通不等于潮流/水力可行 |
| 地理路线 | [OpenFlights 数据](https://openflights.org/data.php) | 机场坐标、路线文件 | 去共享航班/重复，统一方向与时效；地理距离由坐标求，不把历史记录当当前时刻表 |
| 降低单独投入：序列与条形图 | [UniProt](https://www.uniprot.org/) / [InterPro](https://www.ebi.ac.uk/interpro/) / [Ensembl](https://www.ensembl.org/) / [UCSC](https://genome.ucsc.edu/) / [JASPAR](https://jaspar.elixir.no/) | 序列、结构域、外显子、motif 注释 | 真序列不使模拟凝胶变成实验图；查基因名、读最大列不是新的复杂视觉机制 |
| 降低单独投入：谱线表 | [NIST ASD](https://physics.nist.gov/asd) | 元素、波长、跃迁等字段 | 数据表不是实测谱；按表画棒谱属数据渲染，相对强度不随意跨条件相加 |
| 规则盘面配套 | [Lichess database](https://database.lichess.org/) / [Sudoku Exchange bank](https://github.com/grantm/sudoku-exchange-puzzle-bank) / [Brouwer Go](https://homepages.cwi.nl/~aeb/go/games/) | FEN、数独串、SGF | 合法走子不证明唯一最优，实战下一手不等于唯一答案 |
| 聚合发现入口 | [Openverse](https://docs.openverse.org/) / [Google 图片](https://support.google.com/websearch/answer/29508?hl=en-CN) / [ModelScope 魔搭数据集](https://modelscope.cn/datasets) | 关键词、来源和部分许可/类型筛选，具体随入口而异 | 回原发布页核授权与图片 |

ShelfWise 发布页说明包含波兰店内及实验室拍摄图、COCO 商品框及辅助 unknown/unreadable 类，当前列 CC-BY-4.0。它是可靠的候选入口，不能据此认为每个标签都是本题视觉可辨的 SKU。[数据集卡](https://huggingface.co/datasets/shelfwise-by-form/SKUs_on_shelves_PL)

BBBC039 有 200 幅 DNA 单通道视野、520×696 的 16 位 TIFF 和不同颜色编码的独立核掩膜，许可 CC0。不能把它描述为原生多通道时间序列。**本项目已彻底取消 1080p 分辨率限制，包括 BBBC039 在内的低分辨率科学图不再因像素尺寸被阻断或告警**，可正常纳入候选与出题流程；只需如实记录图像宽高、显示窗映射及核边界的可辨性。[官方说明](https://bbbc.broadinstitute.org/BBBC039)

## 3. 许可与资产性质一起保存

每项登记 asset page、原图/数据入口、作者、许可及适用对象、修改说明、record/figure/panel/scene ID。代码、元数据、图像、第三方引用图分别核；研究可下载、HTTP 200、扩展名为 PNG 都不等于可纳入公开题库。许可结论与科学来源真伪是两条独立检查。

| `source.kind` | 含义 | 常见误标 |
|---|---|---|
| `real_photo` | 真实实物照片 | 商品包装上印的另一物体仍是描绘物，不额外计实体 |
| `real_observation` | 原始/明确处理链的仪器或显微观测 | 模拟荧光、模拟凝胶不能填此类 |
| `data_rendering` | CIF/PDB/谱表等真实数据经软件绘图 | 有真实记录 ID 不等于实验测得；有些结构来自 DFT、预测或对称性修正 |
| `synthetic_schematic` | 作者确定性绘制的题设网络或规则盘面 | 适用性按用户是否允许；不能声称实拍 |
| `simulated_observation` | 模拟实验外观的图 | 真实序列/公式作为输入不改变其模拟性质 |
| `mixed_composite` | 多类型或多来源面板拼贴 | 逐面板存来源和缩放，不把拼接大画布尺寸冒充单面板原生尺寸 |

COD 官方将数据库与贡献数据置于公共领域/CC0，并要求承认原作者；因此可保留 CIF 及记录引用，但论文原图的许可需要另核。务必读具体结构的原始论文和测定方法，不把计算结构称为实验结构。[COD 官方](https://www.crystallography.net/cod/)

BIA 新直接提交数据按其政策使用 CC0 或 CC-BY-4.0；从别处导入的记录可有其他许可，逐 accession 确认。[BIA 许可政策](https://www.ebi.ac.uk/bioimage-archive/help-policies/)

## 4. 可计算筛选：先元数据，再图内证据

1. 优先从本地 `采集数据.sqlite` 通过 `sqlite_ledger.py` 召回并去重；新增外部批次时小批召回，按 record ID、论文图号、同场景与 `outputs/` 已有记录排查重复。
2. 元数据筛类别、尺度、时间/通道、是否有标注（不设像素尺寸下限）；原图本地解码再算框尺寸分布、参与密度、局部近色候选、重叠/重复框候选。
3. 逐对象审本题需要的粒度与身份。同品牌不同款、同商品两标签、镜像/包装图、两视图重复、部分露出、群体框分别处理。
4. 标清参与目标集合，核查视觉例外是否确实改变选参、可行集合或最终字段。图很密但绝大多数元素不参与时，降低预期。
5. 通过关键图证检查后进入作者求解、HTML 打包审阅与 4 次直调评测。

Open Images 的官方框格式包含 `IsOccluded`、`IsTruncated`、`IsGroupOf`、`IsDepiction`、`IsInside`。群体框不能当单体框；父子类或同实体多标签不能直接累加。Open Images 图像与标注许可分开，单图仍需使用者核对。[格式与子集入口](https://storage.googleapis.com/openimages/web/download_v7.html)、[许可说明](https://storage.googleapis.com/openimages/web/factsfigures_v7.html)

货架候选可从“至少十多个可辨参与对象、三种以上本题可分类型、存在近似包装和真实例外”开始，小目标特征宽度与正常测量误差比总物品数更关键。这是启发式候选条件，不是统一硬门槛。工业端子、科学原图、显微/遥感分别设参数；不把一套货架阈值搬到所有学科。

## 5. 论文图与去身份化

读取 caption 和正文来理解样本、条件与作者事实；题面只留作答必需的尺度、方向、单位、图例和物理假设。移去直接给出赢家的句子，不删除唯一判别依据。论文结论与额外假设工况分开。源 ID 留在作者记录中，公开 `prompt` 避免无意露出能直接查到所问答案的编号。

PMC 官方已宣布旧 OA Web Service 不再提供，当前应从 Article Datasets/Cloud Service 的文档确认媒体获取方式。[入口变更](https://pmc.ncbi.nlm.nih.gov/tools/oa-service/)

## 6. 视频、镜像与同源管控

可用已有授权视频抽帧，优先场景内有真实身份歧义且上下文可消歧的片段。保留 `video_id`、PTS、镜头/场景、帧号、采样/裁剪映射；变帧率不以帧号除标称 fps 代时间。邻近帧共享人物/货架/机位，按同源组登记；不靠不同文件名冒充独立题。`inspect_images.py` 只分析已抽出的帧，不会自动下载、抽帧或启动 YOLO。

镜像可用于商店、服装店或健身房，但要有镜面边界、遮挡/透视或上下文判据。深度排序和真实/反射实体数量不能只凭“看起来像”；图里缺失必要证据时换候选。同源关系用于管理投入和评测泄漏；明确记录共享证据、变化图证与独立新问题，按本地台账与 `outputs/` 去重范围决定是否接纳。
