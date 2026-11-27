#!/usr/bin/env python3
"""Generate outputs/authoring_ZB-SHELF-63728335-v2/author_record.html and copy unmodified original image."""
import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "authoring_ZB-SHELF-63728335-v2"
SRC_IMG = ROOT / "img" / "公共场景" / "超市货架" / "zb-shelf-63728335.jpg"
DST_IMG = OUT_DIR / SRC_IMG.name

recompute = json.loads((WORK / "recompute.json").read_text(encoding="utf-8"))
report = json.loads((WORK / "qa_report" / "report.json").read_text(encoding="utf-8"))["items"][0]
blind = json.loads((WORK / "blind_trials.json").read_text(encoding="utf-8"))
prompt_text = (WORK / "prompt_v2.txt").read_text(encoding="utf-8").strip()

W, H = recompute["image_size"]
base = recompute["baseline"]
bf = base["fields"]

cf_short_conds = {
    "CF1_B3_cross_shelf_139": "仅将 B3 电子价签误串层读为上方中层红杠 13.90 kr / 126.36 kr/kg（p10_B3: 197→139，kg_B3: 115→126）",
    "CF2_B3_arrow_tag_148": "仅忽略红向下箭头将下层 14.80 kr / 87.06 kr/kg 干扰签误归给 B3（p10_B3: 197→148，kg_B3: 115→87）",
    "CF3_B2_leverpostei_131": "仅将下层 13.10 kr / 65.50 kr/kg（LEVERPOSTEI 肝酱签）误归给中层 B2（p10_B2: 169→131，kg_B2: 153→65）",
    "CF4_A3_miss_back_can": "仅漏看 A3 第 4 罐背面营养表朝前（E_A3: 1→0，G_A3: 5→6）",
    "CF5_A4_all_inverted": "仅漏看 A4 右上角唯一正立罐而误判 4 罐全倒置（E_A4: 3→4，G_A4: 1→0）",
    "CF6_B2_miss_botR_keyhole": "仅漏看 B2 最下层右罐倒置后露出的绿色钥匙孔图标（K_B2: 3→2）",
    "CF7_A3_miss_top_peel_tab": "仅看到 A3 第 5 罐而漏看第 1 罐右侧翘起的米金色易撕耳片（tab_A3: 2→1）",
    "CF8_B2_miss_bottom_row": "仅漏看 B2 最下层 2 罐倒置（E_B2: 2→0，G_B2: 4→6）",
    "CF9_B3_miss_back_left": "仅漏看 B3 后排左罐倒置（E_B3: 4→3，G_B3: 2→3）",
}

cf_thinking_lines = []
for idx, cf in enumerate(recompute["counterfactuals"], 1):
    f = cf["fields"]
    cond = cf_short_conds[cf["id"]]
    cf_thinking_lines.append(
        f"  ({idx}) {cf['id']}：{cond} → "
        f"盘点={f['q1_sum_N']}/{f['q1_sum_E']}/{f['q1_sum_K']}/{f['q1_tab_A3']}/{f['q1_sum_P10']}/{f['q1_sum_KG']}，"
        f"E={f['q2_edges']}({f['q2_near_edges']})，P={f['q3_total_plans']}(M={f['q3_M_plans']},N={f['q3_N_plans']})，"
        f"工况 0: M={f['q4_M_min_c0']}/N={f['q4_N_min_c0']}→{f['q6_winner_w0']}，"
        f"工况 1: M={f['q5_M_min_c1']}(并列{f['q5_M_ties_c1']})/N={f['q5_N_min_c1']}→{f['q6_winner_w1']}，"
        f"rev={f['q6_reversal']}（共 {cf['changed_field_count']}/23 字段变化）。"
    )
cf_flip_cnt = sum(1 for cf in recompute["counterfactuals"] if cf["flips_reversal"])
cf_total_cnt = len(recompute["counterfactuals"])

thinking_text = f"""1. 关键视觉区别（四重跨区图证联锁）：
- 跨层双口径电子价签归属与干扰排错：货架红杠电子价签默认归属其上方货架对应品名商品。A4 的 13.90 kr / 126.36 kr/kg 价签悬挂在中层红杠上、正位于 B3 大托上方，极易串层误归 B3；下层红杠右侧的 13.10 kr / 65.50 kr/kg 印字为 LEVERPOSTEI 200G（对应最下层肝酱箱而非 B2），最右端 14.80 kr / 87.06 kr/kg 左侧带红色向下箭头（指向下层货位而非 B3），唯独 16.90 / 153.64 归属 B2、19.70 / 115.88（STABBUR-MAKRELL TOMAT/PEPPER 170G）归属 B3。
- 局部朝向异常与“全员倒置”反例辨析：A3 左侧 6 罐竖叠列中第 4 罐以背面营养成分表朝前（E_A3 = 1）；A4 宽黄托 4 罐中 3 罐倒置，但右上角 1 罐保持正立（G_A4 = 1，使 A4 保留合法资格）；B2 底层 2 罐倒置（E_B2 = 2）；B3 3×2 顶面罐中仅前左与中左正立，后左与右侧整列 3 罐均倒置（E_B3 = 4）。
- 原生微距细粒度标志核验：B1 仅右侧两罐正立可见 2 处绿底白钥匙孔图标（K_B1 = 2），B2 除顶排 2 罐正立可见外，最下层右罐虽倒置但在左下角清晰露出倒置绿色钥匙孔（中右罐被纸托遮挡不完整，故 K_B2 = 3，合 sum_K = 5）；A3 竖叠列右侧第 1 罐（顶罐）与第 5 罐均明显露出向上翘起的半圆形米金色铝膜易撕耳片（tab_A3 = 2）。
- 跨层水平像素投影测距：dx(a, b) = |cx_a - cx_b| 划定近距（≤720 px）与上限（≤2050 px）边界，距两处阈值最小余量分别达 165 px 与 335 px（两点差误差上界 60 px，R = 2.75 与 5.58），10,000 次联合扰动与 A4 替代锚点测试稳定率 100%。

2. 改变的关系、参数与约束：
- A3 的背面异常罐（E_A3 = 1）决定 A3-B1 与 A3-B2 满足 E_a + E_b ≥ 3；漏看该罐会直接使 N 组全部 2 个合法方案归零。
- A4 右上唯一正立罐（G_A4 = 1）决定 A4 是否满足“至少保留 1 罐正常罐”的兼容边前提；误判 4 罐全倒置会令 A4-B2 与 A4-B3 失效，使 M 组失去最优方案，两工况均由 N 组胜出。
- B3 真实高单罐价（p10 = 197）与低公斤价（kg = 115，因 170g 大规格）的反向剪刀差，叠加未覆盖异常罐罚分与绿色钥匙孔抵扣，是驱动工况 0（N 胜，610 < 638）向工况 1（M 胜，510 < 534）发生赢家反转的核心机制；串层读 13.90 或误读 ↓14.80 均会消灭该反转。
- B2 底层右罐的倒置绿色钥匙孔（K_B2 = 3）使工况 1 下 M 组两方案 A2-B1;A4-B3 与 A2-B2;A4-B3 精确打成 510 分并列（ties1_M = 2），并直接决定 N 组最优值 534；A3 的 2 处翘起耳片（tab_A3 = 2）对含 A3 的方案叠加 +16 罚分，直接改变 N 组工况 1 最优值。

3. 受影响的可判分字段与明确定义的 {cf_total_cnt} 组反事实复算验证：
- 标准正确读法：盘点={bf['q1_sum_N']}/{bf['q1_sum_E']}/{bf['q1_sum_K']}/{bf['q1_tab_A3']}/{bf['q1_sum_P10']}/{bf['q1_sum_KG']}，E={bf['q2_edges']}({bf['q2_near_edges']})，P={bf['q3_total_plans']}(M={bf['q3_M_plans']},N={bf['q3_N_plans']})，工况 0: M={bf['q4_M_min_c0']}/N={bf['q4_N_min_c0']}→{bf['q6_winner_w0']}，工况 1: M={bf['q5_M_min_c1']}(并列{bf['q5_M_ties_c1']})/N={bf['q5_N_min_c1']}→{bf['q6_winner_w1']}，rev={bf['q6_reversal']}（规范方案 {bf['q6_w1_canonical_plan']}）。
- 对以下 {cf_total_cnt} 组明确限定修改条件的有图面依据易混读法（其余未提及属性均保持标准值）逐一独立重算：
""" + "\n".join(cf_thinking_lines) + f"""
- 汇总：上述显式定义的 {cf_total_cnt} 组反事实读法均改变 2–13 个可判分字段，其中 {cf_flip_cnt}/{cf_total_cnt} 组（CF1、CF2、CF4、CF5、CF8）直接将两工况赢家反转位由 1 翻转为 0，其余 4 组（CF3、CF6、CF7、CF9）分别改变单价/公斤价汇总、绿色钥匙孔汇总、翘起耳片数、工况 1 并列数与代表方案编码。"""

cot_img_text = """按原图（4032×3024 px，左上角为原点，x 向右、y 向下）仅考察上层红杠至中层红杠（上层 A 组 A1–A4）与中层红杠至下层红杠（中层 B 组 B1–B3）共 7 个鲭鱼罐头陈列位，排除最左侧玻璃瓶、最右侧白色圆盒与最下层敞口大箱：

一、上层 A 组（从左到右 A1–A4）
1. A1（最左黄色纸托）：底部黄色纸托内可见 2 罐正面竖立罐头（左罐 Peppermakrell i rapsolje，右罐 Filet，不含上方平叠罐），均正立且正面朝前 → N_A1 = 2，E_A1 = 0，G_A1 = 2；品牌 Stabburet；不统计 K 与 tab（均为 0）；按题意不读左端斜拍签，采用默认单价 p10 = 150、kg = 135；水平中心 cx_A1 ≈ 525 px。
2. A2（左中红色纸托圆形罐）：前排可见 2×2 共 4 个红黄圆罐（KING OSCAR MAKRELL I TOMAT 100g）。上排 2 罐正立、下排 2 罐上下倒置 180° → N_A2 = 4，E_A2 = 2，G_A2 = 2；品牌 KING OSCAR；K = 0，tab = 0；下方中层红杠对应电子价签为 “KING O. MAKRELL GROV | Pr/kg 122.00 | Kr Pr/Stk 12.20” → p10_A2 = 122，kg_A2 = 122；cx_A2 ≈ 1255 px。
3. A3（中部蓝白花纹罐左侧竖叠列）：左侧竖直平叠一整列共 6 罐（不含右侧蓝底竖立展陈罐，KING OSCAR SKINNFRI MAKRELLFILET 110g）。自上而下第 1、2、3、5、6 罐均以正面品牌主画面朝前，唯独第 4 罐反面朝前露出完整白色背景营养成分表（NÆRINGSINNHOLD PER 100 g）→ N_A3 = 6，E_A3 = 1，G_A3 = 5；品牌 KING OSCAR；K = 0；沿该列右侧边缘核查，第 1 罐（顶罐）与第 5 罐右侧均清晰露出向上翘起的半圆形米金色铝膜易撕耳片 → tab_A3 = 2；下方中层红杠电子价签为 “KING O. MAKRELL TOMAT 110G | Pr/kg 126.36 | Kr Pr/Stk 13.90” → p10_A3 = 139，kg_A3 = 126（舍去小数）；cx_A3 ≈ 1915 px。易混点：漏看第 4 罐背面翻转，或仅看到第 5 罐耳片而漏看顶罐第 1 罐耳片。
4. A4（右侧宽黄纸托蓝带罐）：上下两层宽黄纸托每层露出 2 个最前排罐面，共 4 罐（Stabburet）。左上、左下、右下 3 罐蓝色 “Stabbur-Makrell” 条带与文字均倒置 180°，唯独右上角 1 罐为正立（可见正立 OMEGA-3 徽章与正立红色 Stabburet 标志）→ N_A4 = 4，E_A4 = 3，G_A4 = 1；品牌 Stabburet；K = 0，tab = 0；下方中层红杠悬挂的电子价签为 “STABBUR-MAKRELL FILET 110G | Pr/kg 126.36 | Kr Pr/Stk 13.90” → p10_A4 = 139，kg_A4 = 126；cx_A4 ≈ 3426 px。易混点：误以为 4 罐全倒置而令 G_A4 = 0。

二、中层 B 组（从左到右 B1–B3）
5. B1（中左橙红角标黄纸托）：黄纸托内正面竖立最前排为 2×2 共 4 罐（不含左上角平放盒顶的散罐，Stabbur-Makrell Grovhakket i salsa）。左列上下 2 罐倒置、右列上下 2 罐正立 → N_B1 = 4，E_B1 = 2，G_B1 = 2；品牌 Stabburet；右列 2 个正立罐右上角均清晰可见完整绿底白钥匙孔圆形图标，左列 2 罐倒置处被纸托边缘遮挡未见 → K_B1 = 2；tab = 0；按题意采用默认单价 p10 = 150、kg = 135；cx_B1 ≈ 1025 px。
6. B2（中中天蓝角标黄纸托）：黄纸托内正面竖立最前排为 3 行×2 列共 6 罐（Stabbur-Makrell Grovhakket i tomatsaus）。上排 2 罐与中排 2 罐均正立，最下排 2 罐上下倒置 180° → N_B2 = 6，E_B2 = 2，G_B2 = 4；品牌 Stabburet；核查绿底白钥匙孔图标：上排左罐右上角（可见 1）、上排右罐右上角（可见 2）、中排左罐右上角被右侧纸托遮挡（不可见）、中排右罐右上角被黄色纸箱立壁裁切遮挡（不完整/不可见）、下排左罐左下角被黄色纸托折翼遮挡（不可见）、下排右罐虽倒置但在其左下角完整清晰露出倒置绿底白钥匙孔圆形图标（可见 3）→ K_B2 = 3；tab = 0；下方下层红杠最左电子价签为 “STABBUR-MAKRELL GROVHAKKET 110G | Pr/kg 153.64 | Kr Pr/Stk 16.90” → p10_B2 = 169，kg_B2 = 153；cx_B2 ≈ 1810 px。易混点：漏看下排 2 罐倒置，漏看下排右罐倒置露出的第 3 处绿色钥匙孔，或误将右侧相邻的 “LEVERPOSTEI 200G / 13.10” 肝酱签归给 B2。
7. B3（中右红边大椭圆罐大黄托）：大黄托内平放 3 行×2 列共 6 叠，计最顶面 6 罐（Stabbur-Makrell Filet i tomatsaus med pepper 170g）。左列前排与中排 2 罐正面正立（白字 Stabbur-Makrell 正向可读），左列后排 1 罐及右列前、中、后 3 罐均上下倒置 180° → N_B3 = 6，E_B3 = 4，G_B3 = 2；品牌 Stabburet；K = 0，tab = 0；排除上方中层红杠属于 A4 的 13.90 签、排除下层红杠 13.10 肝酱签、排除最右带红色向下箭头指向下层的 14.80 签，B3 真实归属签为下层红杠 “STABBUR-MAKRELL TOMAT/PEPPER 170G | Pr/kg 115.88 | Kr Pr/Stk 19.70” → p10_B3 = 197，kg_B3 = 115；cx_B3 ≈ 2970 px。易混点：漏看后排左罐倒置，或串层错读 13.90 / 误读红下箭头 14.80 干扰签。

三、盘点汇总
- 全 7 货位考察总罐数 sum_N = 2 + 4 + 6 + 4 + 4 + 6 + 6 = 32；
- 全 7 货位异常总罐数 sum_E = 0 + 2 + 1 + 3 + 2 + 2 + 4 = 14；
- B1 与 B2 可见绿色钥匙孔总罐数 sum_K = 2 + 3 = 5；
- A3 翘起易撕耳片罐数 tab_A3 = 2；
- 5 个清晰价签货位（A2, A3, A4, B2, B3）整型单罐价总和 sum_P10 = 122 + 139 + 139 + 169 + 197 = 766；
- 5 个清晰价签货位公斤价整数总和 sum_KG = 122 + 126 + 126 + 153 + 115 = 642。"""

cot_reason_text = """一、小问 1（全货位盘点）
由图像识别逐货位事实表直接求和：
- sum_N = 32，sum_E = 14，sum_K = 5，tab_A3 = 2，sum_P10 = 766，sum_KG = 642。

二、小问 2（跨层水平测距与兼容边筛选）
计算全部 4×3 = 12 对跨层货位对的水平像素投影距离 dx(a, b) = |cx_a - cx_b|，核验阈值余量（单货位中心误差上界 e = 30 px，两点差总误差上界 2e = 60 px）：
- 距近距阈值 720 px 最近的两对为 A2-B2（555 px，余量 165 px）与 A3-B1（890 px，余量 170 px），最小余量 165 px，R = 165 / 60 = 2.75 > 1；
- 距上限阈值 2050 px 最近的两对为 A2-B3（1715 px，余量 335 px）与 A4-B1（2401 px，余量 351 px），最小余量 335 px，R = 335 / 60 = 5.58 > 1。
所有 12 对分类完全稳健。逐对检验 3 项兼容条件（dx ≤ 2050、E_a + E_b ≥ 3、G_a ≥ 1 且 G_b ≥ 1）：
- 剔除 4 对：A1-B1（dx=500，但 E和=0+2=2 < 3）、A1-B2（dx=1285，E和=0+2=2 < 3）、A1-B3（dx=2445 > 2050）、A4-B1（dx=2401 > 2050）。
- 保留 E = 8 条兼容边，其中近距边（dx ≤ 720，walk = 15）共 E_near = 4 条，中距边（720 < dx ≤ 2050，walk = 45）共 4 条：
  1. 近距边（4 条）：A2-B1（dx=230，E和=4）、A2-B2（dx=555，E和=4）、A3-B2（dx=105，E和=3）、A4-B3（dx=456，E和=7）。
  2. 中距边（4 条）：A2-B3（dx=1715，E和=6）、A3-B1（dx=890，E和=3）、A3-B3（dx=1055，E和=5）、A4-B2（dx=1616，E和=5）。

三、小问 3（完整合法两对方案计数与分组）
从 8 条兼容边中无序任选两条端点互不复用（a1 ≠ a2 且 b1 ≠ b2）的边，且要求 {a1, a2} 中至少含 1 个 KING OSCAR 货位（A 组可用货位中仅 A2、A3 为 KING OSCAR，A4 为 Stabburet；因仅 A2、A3、A4 存在兼容边，任意两不同上层货位组合 {A2,A3}、{A2,A4}、{A3,A4} 均自动至少含 1 个 KING OSCAR）。按上层货位对枚举并按 A 组编号升序去重：
1. 上层选 {A2, A3}（2 种匹配）：
   - A2-B1;A3-B2：E_tot = 2+1+2+2 = 7 ≤ 7 → N 组；
   - A2-B2;A3-B1：E_tot = 2+1+2+2 = 7 ≤ 7 → N 组；
   - A2-B1;A3-B3：E_tot = 2+1+2+4 = 9 ≥ 8 → M 组；
   - A2-B2;A3-B3：E_tot = 2+1+2+4 = 9 ≥ 8 → M 组；
   - A2-B3;A3-B1：E_tot = 2+1+4+2 = 9 ≥ 8 → M 组；
   - A2-B3;A3-B2：E_tot = 2+1+4+2 = 9 ≥ 8 → M 组。
   （小计 6 种：M 组 4 种，N 组 2 种。）
2. 上层选 {A2, A4}（A4 可连 B2、B3）：
   - A2-B1;A4-B2：E_tot = 2+3+2+2 = 9 → M 组；
   - A2-B1;A4-B3：E_tot = 2+3+2+4 = 11 → M 组；
   - A2-B2;A4-B3：E_tot = 2+3+2+4 = 11 → M 组；
   - A2-B3;A4-B2：E_tot = 2+3+4+2 = 11 → M 组。
   （小计 4 种：全属 M 组。）
3. 上层选 {A3, A4}（A4 可连 B2、B3）：
   - A3-B1;A4-B2：E_tot = 1+3+2+2 = 8 → M 组；
   - A3-B1;A4-B3：E_tot = 1+3+2+4 = 10 → M 组；
   - A3-B2;A4-B3：E_tot = 1+3+2+4 = 10 → M 组；
   - A3-B3;A4-B2：E_tot = 1+3+4+2 = 10 → M 组。
   （小计 4 种：全属 M 组。）
合计：合法方案总数 P = 6 + 4 + 4 = 14，其中 M 组 P_M = 12，N 组 P_N = 2。

四、小问 4（工况 0 优化与并列）
公式 C_0(S) = sum(p10) + walk(e1) + walk(e2)：
- M 组（12 种）：
  * A2-B1;A4-B3：p10 = 122+139+150+197 = 608，walk = 15+15 = 30 → C_0 = 638（唯一最小）；
  * A2-B1;A4-B2：p10 = 122+139+150+169 = 580，walk = 15+45 = 60 → C_0 = 640；
  * A2-B2;A4-B3：p10 = 122+139+169+197 = 627，walk = 15+15 = 30 → C_0 = 657；
  * 其余 9 种 M 组方案 C_0 ∈ [668, 734]。
  故 C0_M = 638，ties0_M = 1。
- N 组（2 种）：
  * A2-B1;A3-B2：p10 = 122+139+150+169 = 580，walk = 15+15 = 30 → C_0 = 610（唯一最小）；
  * A2-B2;A3-B1：p10 = 580，walk = 15+45 = 60 → C_0 = 640。
  故 C0_N = 610，ties0_N = 1。

五、小问 5（工况 1 优化与并列）
公式 C_1(S) = sum(kg) + walk + 6×(14 - E_tot) - 18×(K_{b1} + K_{b2}) + 8×(tab_{a1} + tab_{a2})：
- M 组（12 种）：
  * A2-B1;A4-B3：kg = 122+126+135+115 = 498，walk = 30，未覆盖 3×6 = +18，钥匙孔 (2+0)×(-18) = -36，耳片 0 → C_1 = 498 + 30 + 18 - 36 + 0 = 510；
  * A2-B2;A4-B3：kg = 122+126+153+115 = 516，walk = 30，未覆盖 3×6 = +18，钥匙孔 (3+0)×(-18) = -54，耳片 0 → C_1 = 516 + 30 + 18 - 54 + 0 = 510；
  * 次优为 A2-B1;A4-B2（536+60+30-90+0 = 536）与 A3-B2;A4-B3（520+30+24-54+16 = 536）；其余 8 种 C_1 ∈ [566, 598]。
  故 C1_M = 510，ties1_M = 2（并列最优：A2-B1;A4-B3 与 A2-B2;A4-B3）。
- N 组（2 种）：
  * A2-B1;A3-B2：kg = 122+126+135+153 = 536，walk = 30，未覆盖 7×6 = +42，钥匙孔 (2+3)×(-18) = -90，耳片 (0+2)×8 = +16 → C_1 = 536 + 30 + 42 - 90 + 16 = 534（唯一最小）；
  * A2-B2;A3-B1：同上仅 walk 增至 60 → C_1 = 564。
  故 C1_N = 534，ties1_N = 1。

六、小问 6（赢家反转与规范代表方案）
- 工况 0：N 组 610 < M 组 638，赢家 W0 = N；
- 工况 1：M 组 510 < N 组 534，赢家 W1 = M；
- 两工况赢家由 N 反转为 M，反转位 rev = 1；
- 工况 1 赢家组（M 组）2 个并列最优方案 A2-B1;A4-B3 与 A2-B2;A4-B3 按字典序取最小，规范代表方案编码为 A2-B1;A4-B3。

最终标准答案：
32,14,5,2,766,642|8,4|14,12,2|638,1,610,1|510,2,534,1|N,M,1,A2-B1;A4-B3"""

response_text = base["canonical_answer"]

platform_points = [
    {
        "num": 1,
        "xy": (2070, 940),
        "kind": "作者关键证据点",
        "title": "A3 竖叠列第 4 罐背面翻转及第 1、5 罐翘起耳片",
        "desc": "A3 左侧 6 罐竖叠列中第 4 罐反面朝前露出完整营养成分表（E_A3 = 1），且第 1 罐与第 5 罐右侧均明显露出向上翘起的半圆形米金色铝膜易撕耳片（tab_A3 = 2）。漏看第 4 罐背面翻转会使 A3-B1/A3-B2 失效且 N 组归零（反转位 1→0）；漏看第 1 罐耳片会改变 tab_A3 与工况 1 N 组最优值（534→526）。"
    },
    {
        "num": 2,
        "xy": (1828, 2272),
        "kind": "作者关键证据点",
        "title": "B2 底层右罐倒置露出的绿色钥匙孔图标",
        "desc": "B2 为 3×2 共 6 罐，底层 2 罐倒置（E_B2 = 2），其中底层右罐倒置后在左下角完整清晰露出第 3 处绿底白钥匙孔圆形图标（K_B2 = 3，与 B1 的 2 处合为 sum_K = 5）。漏看底层倒置会使反转位翻转为 0；漏看该倒置钥匙孔会令 sum_K 变为 4、工况 1 M 组并列数由 2 降为 1 且 N 组代价由 534 升至 552。"
    },
    {
        "num": 3,
        "xy": (2760, 2700),
        "kind": "作者关键证据点",
        "title": "下层红杠 B3 真实双口径电子价签（19.70 kr / 115.88 kr/kg）",
        "desc": "下层红杠处该签品名明确为 STABBUR-MAKRELL TOMAT/PEPPER 170G（p10 = 197，kg = 115），须排除上方中层红杠属于 A4 的 13.90 签、左侧 13.10 的 LEVERPOSTEI 肝酱签，以及右侧带红色向下箭头指向下层的 14.80 签。串层误读 13.90 或误读 ↓14.80 均会直接将反转位由 1 翻转为 0。"
    },
]

# Build SVG markers overlay (exact native viewBox 0 0 4032 3024)
svg_markers = []
for pt in platform_points:
    x, y = pt["xy"]
    n = pt["num"]
    color = "#e11d48" if n == 3 else ("#0284c7" if n == 2 else "#f59e0b")
    # Keep badge inside canvas bounds for point 3 near bottom
    bx = x + 92 if x + 165 < W else x - 92
    by = y - 92 if y - 165 > 0 else y + 92
    svg_markers.append(f'''
      <g>
        <circle cx="{x}" cy="{y}" r="82" fill="none" stroke="#ffffff" stroke-width="24" opacity="0.95"/>
        <circle cx="{x}" cy="{y}" r="82" fill="none" stroke="{color}" stroke-width="13"/>
        <line x1="{x-118}" y1="{y}" x2="{x-42}" y2="{y}" stroke="{color}" stroke-width="9"/>
        <line x1="{x+42}" y1="{y}" x2="{x+118}" y2="{y}" stroke="{color}" stroke-width="9"/>
        <line x1="{x}" y1="{y-118}" x2="{x}" y2="{y-42}" stroke="{color}" stroke-width="9"/>
        <line x1="{x}" y1="{y+42}" x2="{x}" y2="{y+118}" stroke="{color}" stroke-width="9"/>
        <circle cx="{x}" cy="{y}" r="15" fill="{color}" stroke="#ffffff" stroke-width="6"/>
        <circle cx="{bx}" cy="{by}" r="62" fill="{color}" stroke="#ffffff" stroke-width="11"/>
        <text x="{bx}" y="{by+25}" text-anchor="middle" fill="#ffffff" font-size="74" font-weight="700" font-family="system-ui, sans-serif">{n}</text>
      </g>''')
svg_overlay = "\n".join(svg_markers)

bay_notes = {
    "A1": "默认基准签（不计入5清晰签）",
    "A2": "12.20 kr / 122.00/kg",
    "A3": "13.90 kr / 126.36/kg；第4罐背面，第1/5罐耳片",
    "A4": "13.90 kr / 126.36/kg；仅右上1罐正立",
    "B1": "默认基准签（不含盒顶散罐）；右列2处钥匙孔",
    "B2": "16.90 kr / 153.64/kg；底层右罐倒置钥匙孔",
    "B3": "19.70 kr / 115.88/kg；前左/中左正立，其余4罐倒置",
}

bay_rows = []
for b in recompute["bays"]:
    g_val = b["N"] - b["E"]
    tag_flag = "清晰签" if b["has_tag"] else "默认基准"
    bay_rows.append(
        f"<tr><td><strong>{b['id']}</strong></td><td>{b['group']} 组</td><td>{b['brand']}</td>"
        f"<td>{b['N']}</td><td>{b['E']}</td><td>{g_val}</td><td>{b['K']}</td><td>{b['tab']}</td>"
        f"<td>{b['p10']} / {b['kg']} ({tag_flag})</td><td>{b['cx']} px</td><td>{bay_notes[b['id']]}</td></tr>"
    )

field_specs = [
    ("q1_sum_N", bf["q1_sum_N"], "罐", "精确整数", "0", "小问 1：全 7 货位考察总罐数"),
    ("q1_sum_E", bf["q1_sum_E"], "罐", "精确整数", "0", "小问 1：全 7 货位异常总罐数"),
    ("q1_sum_K", bf["q1_sum_K"], "罐", "精确整数", "0", "小问 1：B1 与 B2 可见完整绿色钥匙孔总罐数"),
    ("q1_tab_A3", bf["q1_tab_A3"], "罐", "精确整数", "0", "小问 1：A3 竖叠列右侧翘起易撕耳片罐数"),
    ("q1_sum_P10", bf["q1_sum_P10"], "0.1 克朗", "精确整数", "0", "小问 1：5 个清晰价签货位整型单罐价总和"),
    ("q1_sum_KG", bf["q1_sum_KG"], "克朗/公斤", "精确整数", "0", "小问 1：5 个清晰价签货位公斤价整数部分总和"),
    ("q2_edges", bf["q2_edges"], "条", "精确整数", "0", "小问 2：跨层兼容边总数"),
    ("q2_near_edges", bf["q2_near_edges"], "条", "精确整数", "0", "小问 2：近距兼容边数（dx ≤ 720 px）"),
    ("q3_total_plans", bf["q3_total_plans"], "种", "精确整数", "0", "小问 3：合法无序两对采样方案总数"),
    ("q3_M_plans", bf["q3_M_plans"], "种", "精确整数", "0", "小问 3：高异常整顿组 M（E_tot ≥ 8）方案数"),
    ("q3_N_plans", bf["q3_N_plans"], "种", "精确整数", "0", "小问 3：轻异常整顿组 N（E_tot ≤ 7）方案数"),
    ("q4_M_min_c0", bf["q4_M_min_c0"], "代价点", "精确整数", "0", "小问 4：工况 0 下 M 组最小代价"),
    ("q4_M_ties_c0", bf["q4_M_ties_c0"], "种", "精确整数", "0", "小问 4：工况 0 下 M 组最优并列方案数"),
    ("q4_N_min_c0", bf["q4_N_min_c0"], "代价点", "精确整数", "0", "小问 4：工况 0 下 N 组最小代价"),
    ("q4_N_ties_c0", bf["q4_N_ties_c0"], "种", "精确整数", "0", "小问 4：工况 0 下 N 组最优并列方案数"),
    ("q5_M_min_c1", bf["q5_M_min_c1"], "代价点", "精确整数", "0", "小问 5：工况 1 下 M 组最小代价"),
    ("q5_M_ties_c1", bf["q5_M_ties_c1"], "种", "精确整数", "0", "小问 5：工况 1 下 M 组最优并列方案数"),
    ("q5_N_min_c1", bf["q5_N_min_c1"], "代价点", "精确整数", "0", "小问 5：工况 1 下 N 组最小代价"),
    ("q5_N_ties_c1", bf["q5_N_ties_c1"], "种", "精确整数", "0", "小问 5：工况 1 下 N 组最优并列方案数"),
    ("q6_winner_w0", bf["q6_winner_w0"], "组别", "精确枚举（M/N/TIE）", "无", "小问 6：工况 0 赢家"),
    ("q6_winner_w1", bf["q6_winner_w1"], "组别", "精确枚举（M/N/TIE）", "无", "小问 6：工况 1 赢家"),
    ("q6_reversal", bf["q6_reversal"], "位", "精确整数（0/1）", "0", "小问 6：两工况赢家反转位"),
    ("q6_w1_canonical_plan", bf["q6_w1_canonical_plan"], "编码", "精确规范字符串", "无", "小问 6：工况 1 赢家组字典序最小最优方案"),
]
field_rows = "\n".join(
    f"<tr><td><code>{k}</code></td><td><strong>{html.escape(str(v))}</strong></td><td>{u}</td><td>{m}</td><td>{t}</td><td>{d}</td></tr>"
    for k, v, u, m, t, d in field_specs
)

cf_rows = []
cf_rows.append(
    f"<tr class='baseline-row'><td><strong>标准正确读法</strong></td><td>原生微距复核全部 7 货位与 5 张双口径价签</td>"
    f"<td>{bf['q1_sum_E']} / {bf['q1_sum_K']} / {bf['q1_tab_A3']}</td>"
    f"<td>{bf['q1_sum_P10']} / {bf['q1_sum_KG']}</td>"
    f"<td>{bf['q2_edges']} ({bf['q2_near_edges']}) · {bf['q3_total_plans']} ({bf['q3_M_plans']}/{bf['q3_N_plans']})</td>"
    f"<td>M={bf['q4_M_min_c0']}, N={bf['q4_N_min_c0']} → {bf['q6_winner_w0']}</td>"
    f"<td>M={bf['q5_M_min_c1']}(×{bf['q5_M_ties_c1']}), N={bf['q5_N_min_c1']} → {bf['q6_winner_w1']}</td>"
    f"<td><strong>{bf['q6_reversal']}</strong></td><td><code>{bf['q6_w1_canonical_plan']}</code></td></tr>"
)
for cf in recompute["counterfactuals"]:
    f = cf["fields"]
    rev_cls = " class='flip-cell'" if cf["flips_reversal"] else ""
    cf_rows.append(
        f"<tr><td><code>{html.escape(cf['id'])}</code></td><td>{html.escape(cf['description'])}</td>"
        f"<td>{f['q1_sum_E']} / {f['q1_sum_K']} / {f['q1_tab_A3']}</td>"
        f"<td>{f['q1_sum_P10']} / {f['q1_sum_KG']}</td>"
        f"<td>{f['q2_edges']} ({f['q2_near_edges']}) · {f['q3_total_plans']} ({f['q3_M_plans']}/{f['q3_N_plans']})</td>"
        f"<td>M={f['q4_M_min_c0']}, N={f['q4_N_min_c0']} → {f['q6_winner_w0']}</td>"
        f"<td>M={f['q5_M_min_c1']}(×{f['q5_M_ties_c1']}), N={f['q5_N_min_c1']} → {f['q6_winner_w1']}</td>"
        f"<td{rev_cls}><strong>{f['q6_reversal']}</strong></td><td><code>{html.escape(str(f['q6_w1_canonical_plan']))}</code></td></tr>"
    )

blind_rows = []
for tr in blind["trials"]:
    badge = "<span class='badge ok'>整题正确 (23/23)</span>" if tr["exact_match"] else f"<span class='badge err'>整题错答 ({tr['correct_fields']}/23)</span>"
    wf = "无" if not tr["wrong_fields"] else ", ".join(tr["wrong_fields"])
    blind_rows.append(
        f"<tr><td><strong>{tr['trial_id']}</strong></td><td>{badge}</td>"
        f"<td><code>{html.escape(tr['answer'])}</code></td>"
        f"<td>{html.escape(wf)}</td><td>{html.escape(tr['attribution'])}</td></tr>"
    )

point_rows = []
for pt in platform_points:
    x, y = pt["xy"]
    px_pct = f"{100.0 * x / W:.2f}%, {100.0 * y / H:.2f}%"
    point_rows.append(
        f"<tr><td><strong>#{pt['num']}</strong></td><td><code>({x}, {y})</code><br><small>{px_pct}</small></td>"
        f"<td>{html.escape(pt['kind'])}</td><td><strong>{html.escape(pt['title'])}</strong><br>{html.escape(pt['desc'])}</td></tr>"
    )

rm = report["reasoning_metrics"]
mt = report["metrics"]

page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZeroBench 作者填报记录 · ZB-SHELF-63728335-v2</title>
<style>
  :root {{
    --bg: #f5f6f8;
    --card: #ffffff;
    --ink: #18202c;
    --muted: #526071;
    --border: #dce2ea;
    --accent: #1d4ed8;
    --accent-soft: #eff6ff;
    --ok: #15803d;
    --ok-bg: #dcfce7;
    --err: #b91c1c;
    --err-bg: #fee2e2;
    --warn: #b45309;
    --warn-bg: #fef3c7;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 28px 20px 64px;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.65;
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; }}
  header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
    color: #fff;
    padding: 24px 28px;
    border-radius: 14px;
    margin-bottom: 22px;
    box-shadow: 0 6px 24px rgba(15, 23, 42, 0.14);
  }}
  header h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0.2px; }}
  header p {{ margin: 0; opacity: 0.9; font-size: 14px; }}
  section {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  }}
  .sec-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    border-bottom: 2px solid var(--accent-soft);
    padding-bottom: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}
  h2 {{ margin: 0; font-size: 19px; color: #0f172a; }}
  h3 {{ margin: 18px 0 10px; font-size: 15.5px; color: #1e293b; }}
  .btn-copy {{
    appearance: none;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
    border-radius: 7px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.08s ease;
  }}
  .btn-copy:hover {{ background: #1e40af; }}
  .btn-copy:active {{ transform: scale(0.98); }}
  .btn-copy.copied {{ background: var(--ok); border-color: var(--ok); }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 10px 18px;
  }}
  .meta-item {{
    padding: 10px 12px;
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 13.5px;
  }}
  .meta-item .k {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; }}
  .meta-item .v {{ font-weight: 600; word-break: break-all; }}
  .compare-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
    align-items: start;
  }}
  @media (max-width: 900px) {{
    .compare-grid {{ grid-template-columns: 1fr; }}
  }}
  figure {{ margin: 0; }}
  figcaption {{
    font-size: 13px;
    font-weight: 600;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .img-stage {{
    position: relative;
    width: 100%;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: #111;
    line-height: 0;
  }}
  .img-stage img {{
    display: block;
    width: 100%;
    height: auto;
  }}
  .img-stage svg.overlay {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }}
  .copy-box {{
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    font-size: 14px;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "PingFang SC", "Microsoft YaHei", monospace;
  }}
  .answer-box {{
    background: #eff6ff;
    border: 2px solid #93c5fd;
    color: #1e3a8a;
    font-size: 16px;
    font-weight: 700;
    padding: 14px 18px;
    border-radius: 8px;
    word-break: break-all;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  .table-wrap {{ overflow-x: auto; margin-top: 10px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th, td {{
    border: 1px solid var(--border);
    padding: 8px 10px;
    text-align: left;
    vertical-align: top;
  }}
  th {{ background: #f1f5f9; font-weight: 700; white-space: nowrap; }}
  tr.baseline-row {{ background: #f0fdf4; }}
  td.flip-cell {{ background: #fef2f2; color: var(--err); }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }}
  .badge.ok {{ background: var(--ok-bg); color: var(--ok); }}
  .badge.err {{ background: var(--err-bg); color: var(--err); }}
  .badge.warn {{ background: var(--warn-bg); color: var(--warn); }}
  ul.clean {{ margin: 8px 0 0; padding-left: 20px; font-size: 14px; }}
  ul.clean li {{ margin-bottom: 6px; }}
  code {{
    background: #f1f5f9;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 12.5px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>ZeroBench 视觉联合推理作者填报页 · ZB-SHELF-63728335-v2</h1>
  <p>挪威超市鲭鱼罐头货架跨层陈列稽核、双口径电子价签核验与两工况调度反转（离线平台填报版 · 登记难度 medium）</p>
</header>

<!-- 1. 基本信息 -->
<section id="sec-basic">
  <div class="sec-head">
    <h2>一、基本信息</h2>
    <button class="btn-copy" data-target="copy-basic">复制基本信息</button>
  </div>
  <div class="meta-grid">
    <div class="meta-item"><span class="k">题号</span><span class="v">ZB-SHELF-63728335-v2</span></div>
    <div class="meta-item"><span class="k">题名</span><span class="v">挪威超市鲭鱼罐头货架跨层陈列稽核与两工况联合调度反转</span></div>
    <div class="meta-item"><span class="k">一级题型 / 候选题型</span><span class="v">计数聚合链（主）；抗干扰文本读取、定位度量、复杂指令遵循</span></div>
    <div class="meta-item"><span class="k">图片大类与小类</span><span class="v">实拍密集场景照 · 公共场景 / 超市货架（真实照片 real_photo）</span></div>
    <div class="meta-item"><span class="k">原图尺寸与文件</span><span class="v">4032 × 3024 px（EXIF=1，RGB JPEG，zb-shelf-63728335.jpg）</span></div>
    <div class="meta-item"><span class="k">来源页与资产编号</span><span class="v">Wikimedia Commons Page ID 63728335 · File:Mackerel_in_tomato_sauce,_etc.,_product_aisle-shop_shelves_in_Meny_Supermarket,_Bergen_Storsenter_Shopping_Mall,_Bergen,_Norway,_2017-10-23.jpg</span></div>
    <div class="meta-item"><span class="k">作者署名</span><span class="v">Wolfmann</span></div>
    <div class="meta-item"><span class="k">许可协议</span><span class="v">CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0）</span></div>
  </div>
  <textarea id="copy-basic" hidden>题号：ZB-SHELF-63728335-v2
题名：挪威超市鲭鱼罐头货架跨层陈列稽核与两工况联合调度反转
题型：计数聚合链（兼抗干扰文本读取、定位度量、复杂指令遵循）
图片类别：实拍密集场景照 / 公共场景-超市货架（真实照片）
原图尺寸：4032×3024 px（zb-shelf-63728335.jpg）
来源：https://commons.wikimedia.org/wiki/File:Mackerel_in_tomato_sauce,_etc.,_product_aisle-shop_shelves_in_Meny_Supermarket,_Bergen_Storsenter_Shopping_Mall,_Bergen,_Norway,_2017-10-23.jpg
作者：Wolfmann
许可：CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0）</textarea>
</section>

<!-- 2. 原图与打点对照 -->
<section id="sec-images">
  <div class="sec-head">
    <h2>二、原图与打点对照</h2>
    <button class="btn-copy" data-target="copy-points">复制打点坐标说明</button>
  </div>
  <div class="compare-grid">
    <figure>
      <figcaption>左：干净原图（上传平台主图，4032 × 3024 px 未修改）</figcaption>
      <div class="img-stage">
        <img src="zb-shelf-63728335.jpg" alt="干净原图 zb-shelf-63728335.jpg" width="{W}" height="{H}">
      </div>
    </figure>
    <figure>
      <figcaption>右：同画幅叠加 3 个关键打点（SVG viewBox 0 0 4032 3024 精确缩放对齐）</figcaption>
      <div class="img-stage">
        <img src="zb-shelf-63728335.jpg" alt="打点对照图 zb-shelf-63728335.jpg" width="{W}" height="{H}">
        <svg class="overlay" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" aria-label="关键打点标注">
          {svg_overlay}
        </svg>
      </div>
    </figure>
  </div>
  <h3>关键打点清单（以原图左上角为原点，单位 px）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>点编号</th><th>原图像素坐标 (x, y)</th><th>点类型</th><th>证据说明</th></tr>
      </thead>
      <tbody>
        {"".join(point_rows)}
      </tbody>
    </table>
  </div>
  <textarea id="copy-points" hidden>点1：(2070, 940) [51.34%, 31.08%] | 作者关键证据点 | A3 竖叠列第 4 罐背面营养表翻转（E_A3=1）及第 1、5 罐右侧翘起米金色易撕耳片（tab_A3=2），漏看第 4 罐使 N 组归零并翻转反转位。
点2：(1828, 2272) [45.34%, 75.13%] | 作者关键证据点 | B2 底层右罐倒置露出的左下角绿色钥匙孔图标（K_B2=3，sum_K=5），决定工况 1 M 组并列数 2 与 N 组最小代价 534。
点3：(2760, 2700) [68.45%, 89.29%] | 作者关键证据点 | 下层红杠 B3 真实双口径电子价签 19.70 kr / 115.88 kr/kg（须排除 13.10 肝酱签、红下箭头 14.80 签与上方 13.90 签），错配直接消灭两工况赢家反转。</textarea>
</section>

<!-- 3. 题目 (prompt) -->
<section id="sec-prompt">
  <div class="sec-head">
    <h2>三、题目（prompt）</h2>
    <button class="btn-copy" data-target="copy-prompt">复制题目正文</button>
  </div>
  <div class="copy-box" id="copy-prompt">{html.escape(prompt_text)}</div>
</section>

<!-- 4. 出题思路 (thinking) -->
<section id="sec-thinking">
  <div class="sec-head">
    <h2>四、出题思路（thinking）</h2>
    <button class="btn-copy" data-target="copy-thinking">复制出题思路</button>
  </div>
  <div class="copy-box" id="copy-thinking">{html.escape(thinking_text)}</div>
</section>

<!-- 5. 图像识别 (cot_image_understanding) -->
<section id="sec-cot-img">
  <div class="sec-head">
    <h2>五、图像识别（cot_image_understanding）</h2>
    <button class="btn-copy" data-target="copy-cot-img">复制图像识别正文</button>
  </div>
  <div class="copy-box" id="copy-cot-img">{html.escape(cot_img_text)}</div>
  <h3>A1–A4 与 B1–B3 逐货位核验事实表（供审题人快速核对）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>货位</th><th>层级</th><th>品牌</th><th>N_i</th><th>E_i</th><th>G_i</th><th>K_i</th><th>tab_i</th><th>p10 / kg</th><th>水平中心 cx</th><th>关键图证备注</th></tr>
      </thead>
      <tbody>
        {"".join(bay_rows)}
      </tbody>
    </table>
  </div>
</section>

<!-- 6. 题目推理 (cot_reasoning) -->
<section id="sec-cot-reason">
  <div class="sec-head">
    <h2>六、题目推理（cot_reasoning）</h2>
    <button class="btn-copy" data-target="copy-cot-reason">复制题目推理正文</button>
  </div>
  <div class="copy-box" id="copy-cot-reason">{html.escape(cot_reason_text)}</div>
</section>

<!-- 7. 标准答案 (response) -->
<section id="sec-response">
  <div class="sec-head">
    <h2>七、标准答案（response）与逐字段判分口径</h2>
    <button class="btn-copy" data-target="copy-response">复制标准答案</button>
  </div>
  <div class="answer-box" id="copy-response">{html.escape(response_text)}</div>
  <h3>逐字段判分口径（共 23 个可判分字段）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>字段键名</th><th>标准真值</th><th>单位</th><th>判分方法</th><th>容差</th><th>字段说明</th></tr>
      </thead>
      <tbody>
        {field_rows}
      </tbody>
    </table>
  </div>
</section>

<!-- 8. 质检与复算摘要 -->
<section id="sec-qa">
  <div class="sec-head">
    <h2>八、质检与复算摘要</h2>
    <button class="btn-copy" data-target="copy-qa">复制质检摘要</button>
  </div>
  <ul class="clean">
    <li><strong>离线指标质检结论</strong>：<span class="badge ok">decision = authoring_candidate</span>（阻断项 <code>0</code>、待复核项 <code>0</code>、提醒项 <code>0</code>）；<code>difficulty_status = no_complete_failure_recorded</code>（经 v1→v2 一轮提难后仍 3/3 全对，按实测诚实登记难度为 <code>medium</code>）。</li>
    <li><strong>原图与密集/近色/重叠统计</strong>：原图 <code>{mt['width']}×{mt['height']} px</code>（EXIF=1，RGB），中文覆盖率 <code>0.0%</code>，无真人人脸隐私及水印遮挡；登记 <code>{mt['object_count']}</code> 个对象（<code>{mt['class_count']}</code> 类），近色异类邻居 <code>{mt['nearcolor_pair_count']}</code> 对、边界框投影重叠候选 <code>{mt['bbox_overlap_pair_count']}</code> 对（中层红杠价签视觉投影叠压下方货位，构成串层错配核心陷阱），6 个原生 ROI 裁图均经人工逐张复核清晰可辨。</li>
    <li><strong>多层联合推理图与测距稳健性</strong>：作者登记推理 DAG 含 <code>{rm['node_count']}</code> 节点、最大深度 <code>{rm['max_depth']}</code> 层、<code>{rm['multi_visual_join_nodes']}</code> 个多视觉源合流节点，6 个小问输出视觉祖先覆盖率 <code>100%</code>。水平投影测距单货位误差上界 <code>30 px</code>（两点差上界 <code>60 px</code>），近距阈值 <code>720 px</code> 最小余量 <code>165 px</code>（<code>R = 2.75</code>），上限阈值 <code>2050 px</code> 最小余量 <code>335 px</code>（<code>R = 5.58</code>）；<code>10,000</code> 次联合随机扰动与 <code>A4</code> 右移 <code>+124 px</code> 替代锚点测试，全部 23 字段稳定率均为 <code>100%</code>。</li>
    <li><strong>防绕过审查（passed）</strong>：v2 彻底移除布局维度与干扰签提示，去图无法获取任何罐数、倒置、钥匙孔、耳片、双口径价签与中心坐标；关键图证横跨全图宽 <code>x ∈ [120, 4032]</code> 及上/中两层红杠，单一大裁图无法覆盖。</li>
  </ul>

  <h3>反事实复算差异对照（solver.py 独立重算，共 9 组）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>读法编号</th><th>图面误读假设</th><th>E / K / tab</th><th>P10 / KG</th><th>边(近) · 方案(M/N)</th><th>工况 0 最小代价→赢家</th><th>工况 1 最小代价→赢家</th><th>反转位</th><th>工况 1 代表方案</th></tr>
      </thead>
      <tbody>
        {"".join(cf_rows)}
      </tbody>
    </table>
  </div>

  <h3>定稿前 3 次独立盲答试答摘要（冻结题面 v2 + 干净原图，工具开放）</h3>
  <p style="font-size:13.5px; margin:6px 0 8px;">先期对 v1 做 3 次独立盲答 <strong>3/3</strong> 全对，随后执行一轮提难升级为 v2（去除全部布局与干扰签提示，新增双口径价签 <code>Pr/kg</code>、<code>B1/B2</code> 绿色钥匙孔含 <code>B2</code> 底层倒置图标及 <code>A3</code> 翘起耳片）。对冻结 v2 进行新一轮 3 次独立盲答：有效完整试答 <strong>3 / 3</strong>（超时 0、工具故障 0、残缺答案 0），整题完全正确 <strong>3 / 3</strong>（全部 23/23 字段精确命中），未发现题面歧义、图证不清或判分问题；按规范如实登记难度为 <code>medium</code>。</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>轮次</th><th>判分结果</th><th>提交末答</th><th>错答字段</th><th>核验说明</th></tr>
      </thead>
      <tbody>
        {"".join(blind_rows)}
      </tbody>
    </table>
  </div>
  <textarea id="copy-qa" hidden>离线质检：decision=authoring_candidate（0阻断/0待审/0提醒），原图 4032×3024 px（EXIF=1，中文覆盖 0.0%，无真人隐私及水印），14 对象、3 近色异类对、2 投影重叠对，6 个原生 ROI 均人工复核可读。
测距稳健性：单端点误差上界 30 px（两点差上界 60 px），720 px 阈值余量 165 px（R=2.75），2050 px 阈值余量 335 px（R=5.58），10000 次联合扰动与 A4 右移 +124 px 替代锚点测试全部 23 字段稳定率 100%。
反事实复算：对 CF1–CF9 共 9 组显式限定条件的易混读法逐一重算（其余属性不变），全部 9 组均改变 2–13 个可判分字段；其中 5/9 组（CF1、CF2、CF4、CF5、CF8）直接将反转位由 1 翻转为 0，其余 4 组（CF3、CF6、CF7、CF9）分别改变单价/公斤价汇总、绿色钥匙孔、耳片数、工况 1 并列数与代表方案。
三次独立盲答（冻结 v2 + 干净原图，工具开放）：经 v1→v2 提难后，有效 3/3，整题全对 3/3（23/23 字段零歧义精确命中），无超时/故障/残缺，按实测诚实登记难度 medium。</textarea>
</section>

</div>

<script>
(function() {{
  function fallbackCopy(text) {{
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try {{ ok = document.execCommand('copy'); }} catch (e) {{ ok = false; }}
    document.body.removeChild(ta);
    return ok;
  }}

  document.querySelectorAll('.btn-copy').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      const id = btn.getAttribute('data-target');
      const el = document.getElementById(id);
      if (!el) return;
      const text = (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') ? el.value : el.innerText;
      const done = function() {{
        const orig = btn.textContent;
        btn.textContent = '已复制 ✓';
        btn.classList.add('copied');
        setTimeout(function() {{
          btn.textContent = orig;
          btn.classList.remove('copied');
        }}, 1600);
      }};
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(done).catch(function() {{
          if (fallbackCopy(text)) done();
        }});
      }} else {{
        if (fallbackCopy(text)) done();
      }}
    }});
  }});
}})();
</script>
</body>
</html>
"""

OUT_DIR.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC_IMG, DST_IMG)
(OUT_DIR / "author_record.html").write_text(page_html, encoding="utf-8")
print("Wrote:", OUT_DIR / "author_record.html")
print("Copied unmodified original:", DST_IMG, "bytes:", DST_IMG.stat().st_size, "src bytes:", SRC_IMG.stat().st_size)
