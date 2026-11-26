# 可按条件筛选的真实图源

图源说明沿用 2026-11-26 的项目查阅记录。表中区分了可直接检索的元数据、获取原图后才能计算的指标，以及作者必须观察的细节。使用候选时记录所选条目的许可与署名要求。

## 选择图源

| 优先使用场景 | 数据库与官方入口 | 原生检索或已有元数据 | 本地加工／看图后才能决定 | 使用要点 |
| --- | --- | --- | --- | --- |
| 密集实物、多类别、局部遮挡 | **[Google Open Images V7](https://storage.googleapis.com/openimages/web/download_v7.html)** | 类别、目标框、部分分割与关系；框有遮挡、截断、群体、描绘物等属性 | 同类数量、类别共现、对象面积分布、遮挡比例、关键部件可辨性 | 最适合先按标注筛图ID，再下载小批候选。类别与框不自动构成本题完整GT |
| 专业器材、纹样、标本、目录扫描 | **[Wikimedia Commons](https://commons.wikimedia.org/wiki/Help:Searching)** | 关键词、类别、文件属性及结构化声明；MediaSearch有尺寸和许可筛选 | 特定部件数量、近似对象、读数和空间关系 | [API扩展元数据](https://commons.wikimedia.org/wiki/Commons:Machine-readable_data/en)提供作者和许可等；回文件页取原图 |
| 历史仪器、矿物、实物与装饰纹样 | **[Smithsonian Open Access](https://www.si.edu/openaccess/faq)** | 关键词、馆藏分类；公开元数据含机构、对象说明及媒体 | 一件还是一组、纹样密度、标尺或部件是否可辨 | 选择媒体本身标为CC0的记录；元数据CC0不等于所有关联图片CC0。优先使用当前API或公共元数据 |
| 密集细胞、组织、多通道／时序图 | **[BioImage Archive](https://www.ebi.ac.uk/bioimage-archive/help-search/)**、**[IDR](https://idr.openmicroscopy.org/about/api.html)** | BIA支持布尔关键词及集合、发布日期等筛选；IDR提供实验和键值注释检索，如基因和表型 | 样本内通道、z层、时间点、细胞密度、可辨分割边界，按具体数据记录处理 | 优先选择附标注或实验条件的数据。BIA新直接提交数据用CC0或CC-BY-4.0，导入数据可能不同；逐记录确认 |
| 跨时相、同地区、真实变化 | **[Google Earth Engine](https://developers.google.com/earth-engine/guides/ic_filtering)** | 地理范围、日期、传感器与集合元数据；Sentinel-2有云量字段 | 局部有效观测、稳定地标、目标密度和能否唯一配对 | [Sentinel-2示例](https://developers.google.com/earth-engine/guides/image_overview)使用 `COPERNICUS/S2_SR_HARMONIZED`。分辨率必须支持目标；导出参数和数据集许可保留 |
| 复杂晶体、密度、层间邻接与堆积 | **[Crystallography Open Database](https://www.crystallography.net/cod/search.html)** | 元素及排除元素、元素种类数、化学式、空间群、晶胞体积、Z/Z′、论文DOI等 | 不等价位点、占据率、层序、配位与投影是否可判 | 提供真实结构数据，常用于CIF软件渲染；不是现成实拍图库。COD数据为公共领域，引用结构记录和原论文 |
| SCI原图、caption及实验论述 | **[PMC Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/textmining/)** | 文章主题、年份及文章级许可等；云端提供XML与可用媒体 | 图类型、面板依赖、密度、细支路、峰重叠等，需解析caption与图面 | 用 [PMC Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/cloud/) 的当前分发方式取媒体；许可逐文及逐图核对 |
| 跨网站找有许可的候选 | **[Openverse](https://docs.openverse.org/api/reference/search_algorithm.html)** | 关键词、来源、许可／许可类型、尺寸、宽高比、文件类型等 | 目标数、复杂关系和实际清晰度 | [API媒体字段](https://docs.openverse.org/meta/media_properties/api.html)包含来源页、作者等；返回上游页面确认原图 |
| 专业主题补充检索 | **[Google 图片搜索](https://support.google.com/websearch/answer/29508?hl=en-CN)** | 关键词及使用权限过滤，链接到具体来源 | 没有统一可直接查询的“20个物体、3类、部分遮挡”字段 | 用来发现原出处。使用权限过滤是入口，需打开许可详情；下载搜索缩略图不能替代原图 |

物理器材优先Commons／Smithsonian；生物优先BIA／IDR；晶体优先COD；一般密集实拍优先Open Images；遥感优先Earth Engine；论文图优先可用媒体与许可齐全的PMC条目。这个顺序按题材切换，不要求先遍历全部数据库。

## Open Images：把“找复杂图”变成可计算筛选

采用两阶段：官方元数据初筛 → 原图与关键证据核对。官方框属性包括 `IsOccluded`、`IsTruncated`、`IsGroupOf`、`IsDepiction`、`IsInside`；未知值不能当否。属性定义及下载格式见 [官方说明](https://storage.googleapis.com/openimages/web/download_v7.html)。

以下为本项目自定义的筛选意图示例，需由采集器映射，不可直接当成某个API的请求体。数值只是密集实物题的起点，按题材与实际分辨率调整：

```yaml
source: open-images-v7
purpose: dense-real-objects-with-conditional-selection
candidate_budget: 30
metadata_prefilter:
  target_classes_any: [Bottle, Cup, Chair, Car]
  real_instances_required: true
  ignore_group_boxes_for_individual_count: true
local_annotation_filter:
  min_candidate_instances: 15
  min_same_class_instances: 8
  min_distinct_leaf_classes: 3
  occluded_fraction_candidate_range: [0.10, 0.45]
manual_evidence_review:
  critical_boundaries_readable: true
  enough_evidence_for_unique_inclusion: true
  one_local_difference_can_change_constraints: true
  license_and_original_resolution_confirmed: true
```

处理细节：

- 标注数量只作候选指标；群体框不能当一个普通实例或凭框猜群体数量。对本题真正计数的对象重新列清单。
- 类别存在父子关系。同一实体多标签不能算多件；真正互相遮挡的不同实体也不能仅按框重叠率合并。
- 筛“真实实物”时检查描绘物标记及原图，排除包装上的物体图片被当成另一件实物。
- 优先保留全部相关标签，避免仅下载匹配类别后丢掉干扰对象及上下文。
- [FiftyOne](https://docs.voxel51.com/dataset_zoo/datasets/open_images_v7.html)支持按类别、标注类型、图ID和数量部分下载。它的类别条件并非保证所有指定类别同时出现；严格共现需要本地再筛。`attrs`针对关系属性，不能直接等同遮挡框标记。
- FiftyOne说明其图像版本长边至多1024像素；若项目要求更高分辨率，需要回来源取合规原图，拿不到时改选素材。放大缩略图不增加可辨证据。
- [Open Images许可说明](https://storage.googleapis.com/openimages/web/factsfigures_v7.html)区分标注和图像，并要求使用者核对单图许可。冻结作者、来源页及所用图像版本。

## 科学图的条件筛选例子

### 晶体

先以COD的元素、空间群、体积、Z/Z′和文献条件缩小集合，再读CIF筛不等价位点、分层及占据情况。优先选择“配位或层间关系真实不同”的结构，不能把大晶胞当作困难的充分条件。

可用选择意图：多类元素、多个不等价位点、可见层序差异、两个以上候选邻居组。是否需要非满占据取决于题目；仅看球图不能推出未表示的占据率。渲染图需保留能恢复周期与层关系的图证，必要时补一个投影。

### 生物

BIA可先用 `confocal AND fluorescence AND microscopy` 之类布尔词组合，再按实验元数据筛组织／物种和成像条件；该库默认多个词可能按OR匹配，要求全部出现时明确AND。[检索语法](https://www.ebi.ac.uk/bioimage-archive/help-search/)

在候选数据内寻找多通道、连续z层或时间点，优先有可核对的对象标注。细胞密度和实例边界通常要在图或分割数据上计算，不能宣称是网站统一现成筛选字段。BIA、IDR的键值、通道名称和格式随研究而异。[BIA许可政策](https://www.ebi.ac.uk/bioimage-archive/help-policies/) · [IDR API](https://idr.openmicroscopy.org/about/api.html)

### 遥感

先按同一区域、日期窗口、传感器及云量筛，再选相似季节和可比波段，核对局部云／阴影、有效区域与共同地标。整景低云量不保证目标处无云。保持题目需要的真实变化，不用时间平均合成图冒充某一天的单景观测。像素分辨率应支持需要辨认的地物。

Earth Engine是数据访问与计算平台；可用性、账户和具体数据集条款按实际运行时确认。普通Google图片搜索中的航拍截图不能自动替代带时间、尺度、投影的原始遥感数据。[过滤说明](https://developers.google.com/earth-engine/guides/ic_filtering)

### 论文图

先按主题和许可筛文章，读取XML中的图号、caption与媒体引用；以 `tomography`、`multi-channel`、`phase diagram`、`stacking fault`、`HMBC` 等作为题材词候选。它们是搜索词，不是通用图类型标签。进一步从图面确认多面板、交叉曲线、细分支或重叠峰是否实际存在。

**当前入口变化：** PMC官方已在2026-08公告旧OA Web Service不可用，并将当前媒体分发指向Cloud Service；不要照搬旧教程中的OA API或旧FTP包路径。[服务变更](https://pmc.ncbi.nlm.nih.gov/tools/oa-service/) · [当前云端文件](https://pmc.ncbi.nlm.nih.gov/tools/cloud/)

## 专业实物与纹样的搜索词

这是人工主题检索的起点，不能代替图面核对：

| 主题 | 候选检索词 | 候选图的取舍 |
| --- | --- | --- |
| 精密仪器 | micrometer、vernier、dial、mixing console、channel strip | 刻度与工作模式实际可辨，必要量程信息存在 |
| 密集工具或部件 | tool catalogue、specimen tray、instrument panel、mechanical assembly | 排除文字占位图；局部齿端、孔、接口能逐一定位 |
| 纹样和复杂规律 | patchwork quilt、sampler、geometric textile、mosaic | 保留真实局部例外，重复纹样不直接等于规则题唯一性 |
| 标本与矿物 | mineral collection、insect drawer、botanical plate | 区分单件展示与密集集合；必要标签及尺度可辨 |

Smithsonian的旧GitHub元数据仓库已归档，其说明指向公共云元数据及当前文档。不要将旧仓库当持续更新接口。[官方仓库说明](https://github.com/Smithsonian/OpenAccess) · [官方Python接口说明](https://github.com/Smithsonian/smithsonian-openaccess)

## 候选清单字段

每个候选至少保存：来源／ID、来源页与原图入口、许可与作者、原图尺寸、可用元数据、命中的筛选条件、需要人工确认的视觉条件、建议题型、旧图库来源匹配结果、保留／弃用原因。

对同一候选分别记录检索命中、关键图证可辨、作者真值已求出，以及是否已有对应版本的模型试答。
