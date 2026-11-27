#!/usr/bin/env python3
"""Generate outputs/authoring_ZB-TOOLS-151686260-v1/author_record.html and copy unmodified original image."""
import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "authoring_ZB-TOOLS-151686260-v1"
SRC_IMG = ROOT / "img" / "居家场景" / "工具五金" / "zb-hardware-151686260.jpg"
DST_IMG = OUT_DIR / SRC_IMG.name

recompute = json.loads((WORK / "recompute.json").read_text(encoding="utf-8"))
report = json.loads((WORK / "qa_report" / "report.json").read_text(encoding="utf-8"))["items"][0]
blind = json.loads((WORK / "blind_trials.json").read_text(encoding="utf-8"))
prompt_text = (WORK / "prompt_v1.txt").read_text(encoding="utf-8").strip()

W, H = recompute["image_size"]
base = recompute["baseline"]
bf = base["fields"]

cf_thinking_lines = []
cf_short_conds = {
    "CF1_H3_size_monotonic_23": "仅将 H3 正面规格由 15 误读为 23（按递减补猜）",
    "CF2_H6_blue_2": "仅将 H6(19 mm) 蓝柄把数 B_6 由 3 误读为 2",
    "CF3_H1_H4_red_single_1": "仅将 H1(28 mm) 与 H4(22 mm) 红柄把数 R_1、R_4 均由 2 误读为 1（其余不变；注：单独误读 H1 得 W0=20/23→M、W1=32/31→N，单独误读 H4 得 W0=20/23→M、W1=30/29→N，均保持 rev=1 但改变盘点/边数/工况 1 代价）",
    "CF4_H1_H4_red_1_and_H6_blue_2": "同时将 R_1、R_4 由 2 误读为 1 且将 B_6 由 3 误读为 2（对应盲测第 2 轮实际错读）",
    "CF5_behind_red_single_1": "仅将 B 组 H5–H12 背后叠挂红柄把数一律误读为 1（R_5..R_12 均设为 1）",
    "CF6_H5_USA_even_guess": "仅将 H5(20 mm) 品牌后缀 U_5 由 0 误判为 1（按偶数猜有 USA）",
    "CF7_H7_USA_missed_dirt": "仅因油污将 H7(18 mm) 品牌后缀 U_7 由 1 漏读为 0",
    "CF8_H3_red_single_1": "仅将 H3(15 mm) 红柄把数 R_3 由 3 误读为 1（漏看后方 2 把长红柄）",
}
for idx, cf in enumerate(recompute["counterfactuals"], 1):
    f = cf["fields"]
    cond = cf_short_conds[cf["id"]]
    cf_thinking_lines.append(
        f"  ({idx}) {cf['id']}：{cond} → "
        f"蓝/红={f['q1_sum_blue']}/{f['q1_sum_red']}，E={f['q2_edges']}({f['q2_near_edges']})，"
        f"P={f['q3_total_plans']}(M={f['q3_M_plans']},N={f['q3_N_plans']})，"
        f"工况 0: M={f['q4_M_min_c0']}/N={f['q4_N_min_c0']}→{f['q6_winner_w0']}，"
        f"工况 1: M={f['q5_M_min_c1']}/N={f['q5_N_min_c1']}→{f['q6_winner_w1']}，"
        f"rev={f['q6_reversal']}（共 {cf['changed_field_count']}/20 字段变化）。"
    )
cf_flip_cnt = sum(1 for cf in recompute["counterfactuals"] if cf["flips_reversal"])
cf_total_cnt = len(recompute["counterfactuals"])

thinking_text = f"""1. 关键视觉区别（四重联锁图证）：
- 左红柄区（H1–H4）存在非单调刻字与紧贴多层叠挂：H3 位于 24 mm 与 22 mm 之间但实际刻字为 15 mm，且 H1(28)、H3(15)、H4(22) 并非单把悬挂，而是分别叠挂了 2、3、2 把红柄扳手（仅 H2 为 1 把）。
- 中蓝柄区（H5–H12）同钩前后双层异色叠挂：每个蓝柄挂钩背后均藏有红柄橙颈 UNIOR 扳手，其中除 H10(15 mm) 背后仅 1 把红柄外，其余 7 个挂钩背后各有 2 把红柄；同时各钩前方蓝柄也存在 1–4 层紧贴叠挂（H5–H12 依次为 1, 3, 3, 4, 2, 1, 3, 3 把）。
- 蓝柄正面品牌后缀存在反规律分布：仅 H7(18 mm，表面带油污)、H9(16 mm)、H11(14 mm) 印有 “Park Tool USA”，而同为偶数规格的 H5(20 mm) 仅印有 “Park Tool” 无 USA。
- 跨组钩心水平像素投影距离 dx(a, b) 划定近距（≤1180 px）、中距（1180–2200 px）与超距（>2200 px）边界，距两处阈值最小余量分别达 108 px 与 72 px（误差上界 24 px，R = 4.50 与 3.00）。

2. 改变的关系、参数与约束：
- H3 的实际规格 15 mm 与 3 把红柄库存共同决定近距边 H3-H5 与 H3-H6 的合法性及 A 组重载加罚；若按单调递减误读为 23 mm 或漏读 H3 叠挂，近距边 H3-H5 立即失效。
- H1、H4 紧贴叠挂的第 2 把红柄决定跨组边 H1-H5 是否满足 T_a + T_b ≥ 5，以及工况 1 中 H4 是否触发 R_a ≥ 2 加罚（直接改变 sum_R、E、P、P_N 及 C1_M / C1_N；该两钩漏读不改变反转位，但会改变多处盘点与优化字段）。
- H6(19 mm) 的 3 层蓝柄叠挂决定方案 H3-H6;H4-H7 落入高蓝柄组 M（3+3=6）而非轻蓝柄组 N；若误读为 2 把，该方案划入 N 组并直接消灭工况 0→1 的赢家反转。
- H5 无 USA、H7 带 USA 决定合法方案全局约束 U_b1 + U_b2 = 1，任何一项误判均会剔除核心最优方案。

3. 受影响的可判分字段与明确定义的 {cf_total_cnt} 组反事实复算验证：
- 标准正确读法：蓝/红={bf['q1_sum_blue']}/{bf['q1_sum_red']}，E={bf['q2_edges']}({bf['q2_near_edges']})，P={bf['q3_total_plans']}(M={bf['q3_M_plans']},N={bf['q3_N_plans']})，工况 0: M={bf['q4_M_min_c0']}/N={bf['q4_N_min_c0']}→{bf['q6_winner_w0']}，工况 1: M={bf['q5_M_min_c1']}/N={bf['q5_N_min_c1']}→{bf['q6_winner_w1']}，rev={bf['q6_reversal']}（规范方案 {bf['q6_w1_canonical_plan']}）。
- 对以下 {cf_total_cnt} 组明确限定修改条件的有图面依据易混读法（其余未提及属性均保持标准值）逐一独立重算：
""" + "\n".join(cf_thinking_lines) + f"""
- 汇总：上述显式定义的 {cf_total_cnt} 组反事实读法均改变 6–13 个可判分字段（覆盖盘点总数、兼容边、合法方案数与两工况最小代价），其中除 CF3（漏读 H1/H4 双层红柄保持 rev=1）外，其余 {cf_flip_cnt}/{cf_total_cnt} 组（CF1、CF2、CF4、CF5、CF6、CF7、CF8）均将两工况赢家反转位由 1 翻转为 0。"""

cot_img_text = """按原图（4716×3144 px，左上角为原点）上排从左到右前 12 个挂钩逐钩辨析，排除最右侧两处全银色无塑柄双头扳手挂钩与下排工具：

一、A 组（左侧红柄橙颈 UNIOR 1617/2DP-US 区，H1–H4，B_i 均为 0）
1. H1：正面钢柄刻字 28（批号 F25）；放大核查右侧银色钳口边缘、三角挂孔内双层钢板、右侧橙色颈圈双层台阶及底孔内双层同心橙环，确认紧贴叠挂 2 把红柄（R_1 = 2，T_1 = 2）；红杆穿出挂孔中心横坐标 x_1 ≈ 500 px。易混点：后方第 2 把与前把对齐紧密，易漏读为 1 把。
2. H2：正面钢柄刻字 24（批号 N45）；钳口、三角挂孔、橙色颈圈与底孔均为单层，确认 R_2 = 1，T_2 = 1；x_2 ≈ 928 px。
3. H3：正面钢柄刻字 15（批号 N49，非单调位于 24 与 22 之间）；三角挂孔内可见 3 层水平钢板顶边、左侧可见 3 层银色钳口与 3 条红柄侧缘，且较短的 15 mm 前把后方露出 2 把更长红柄（底孔内可见 2 层同心橙环），确认 R_3 = 3，T_3 = 3；x_3 ≈ 1338 px。易混点：按递减规律补猜为 23，或将后方 2 把长红柄合算为 1 把而误计总数 2。
4. H4：正面钢柄刻字 22（批号 N45）；左侧银色钳口、左侧双层橙色颈圈与左侧双层红柄边缘清晰可辨，确认紧贴叠挂 2 把红柄（R_4 = 2，T_4 = 2）；x_4 ≈ 1666 px。易混点：后方第 2 把仅在左侧窄边显露，易漏读为 1 把。

二、B 组（中部蓝柄黑头 Park Tool 区，H5–H12，每个挂钩后方均叠挂红柄 UNIOR）
5. H5：蓝柄印字 20 mm / SCW-20 / Park Tool®（无 USA，U_5 = 0）；顶部仅 1 个蓝柄圆拱、底部仅 1 片黑钢刃（B_5 = 1）；后方左侧可见 2 个独立橙色颈圈与 2 层银色钳口（R_5 = 2），故 T_5 = 3；x_5 ≈ 2000 px。易混点：误按偶数规格猜有 USA，或漏看后方 2 把红柄。
6. H6：蓝柄印字 19 mm / SCW-19 / Park Tool®（无 USA，U_6 = 0）；顶部可见 3 层独立蓝柄圆拱，蓝黑交界处可见 3 段高低错落的蓝套下缘与 3 层黑钢颈（B_6 = 3）；后方可见 2 个橙色颈圈与 2 层银色钳口（R_6 = 2），故 T_6 = 5；x_6 ≈ 2340 px。易混点：前两层黑钳口紧贴，易将 3 层蓝柄误看为 2 把。
7. H7：蓝柄印字 18 mm / SCW-18 / Park Tool USA（虽有黑色油污但末尾 USA 清晰可辨，U_7 = 1）；顶部可见 3 层蓝柄圆拱与 3 段蓝套下缘（B_7 = 3）；后方 2 个橙色颈圈与 2 层银色钳口（R_7 = 2），故 T_7 = 5；x_7 ≈ 2628 px。易混点：因油污漏读 USA。
8. H8：蓝柄印字 17 mm / SCW-17 / Park Tool®（无 USA，U_8 = 0）；顶部可见 4 层独立蓝柄圆拱、蓝黑交界处可见 4 层蓝套（B_8 = 4）；后方 2 个橙色颈圈（R_8 = 2），故 T_8 = 6；x_8 ≈ 2955 px。易混点：最内侧第 4 层蓝柄贴近银色钳口，易误数成 3 把。
9. H9：蓝柄印字 16 mm / SCW-16 / Park Tool USA（U_9 = 1）；顶部 2 层蓝柄圆拱、2 片黑刃（B_9 = 2）；后方 2 个橙色颈圈（R_9 = 2），故 T_9 = 4；x_9 ≈ 3255 px。
10. H10：蓝柄印字 15 mm / SCW-15 / Park Tool®（无 USA，U_10 = 0）；顶部仅 1 层蓝柄（B_10 = 1）；后方仅 1 个橙色颈圈与 1 层银色钳口（R_10 = 1），故 T_10 = 2；x_10 ≈ 3445 px。易混点：按其余 7 钩规律误以为背后也是 2 把红柄。
11. H11：蓝柄印字 14 mm / SCW-14 / Park Tool USA（U_11 = 1）；顶部 3 层蓝柄圆拱（B_11 = 3）；后方 2 个橙色颈圈（R_11 = 2），故 T_11 = 5；x_11 ≈ 3745 px。
12. H12：蓝柄印字 13 mm / SCW-13 / Park Tool®（无 USA，U_12 = 0）；顶部 3 层蓝柄圆拱、底部 3 层黑钳口（B_12 = 3）；后方 2 个橙色颈圈（R_12 = 2），故 T_12 = 5；x_12 ≈ 3945 px。

三、盘点汇总
- 蓝柄总数 sum_B = 0+0+0+0 + (1+3+3+4+2+1+3+3) = 20；
- 红柄总数 sum_R = (2+1+3+2) + (2+2+2+2+2+1+2+2) = 8 + 15 = 23；
- B 组 U_i = 1 的挂钩为 H7(18)、H9(16)、H11(14)，按从左到右输出 18,16,14。"""

cot_reason_text = """一、小问 1（全挂钩盘点）
由图像识别逐钩事实表直接汇总：sum_B = 20，sum_R = 23，U_i = 1 对应规格按从左到右为 18,16,14。

二、小问 2（跨组水平测距与兼容边筛选）
计算全部 4×8 = 32 对跨组水平像素投影距离 dx(a, b) = |x_a - x_b|，检查距离阈值余量：
- 距近距阈值 1180 px 最近的对为 H2-H5（1072 px，余量 108 px）与 H4-H8（1289 px，余量 109 px）；
- 距上限阈值 2200 px 最近的对为 H1-H7（2128 px，余量 72 px）与 H4-H12（2279 px，余量 79 px）。
单端点误差上界 12 px 时两点差误差上界为 24 px，所有 32 对均远离两处阈值（R = 4.50 与 3.00），分类完全稳健。

逐对检验 3 项兼容条件（dx ≤ 2200、|size_a - size_b| ≥ 4、T_a + T_b ≥ 5），共得 E = 12 条兼容边，其中近距边（dx ≤ 1180，d_cost = 4）共 E_near = 3 条，中距边（1180 < dx ≤ 2200，d_cost = 9）共 9 条。每条边的常规代价 c_0 = d_cost + |size_a - size_b| + (5 - B_b) 及工况 1 加罚 pen = (T_b ≥ 5 时 4*(T_b-4)) + (R_a ≥ 2 时 2) 如下：
1. 近距边（3 条）：
   - H3-H5：dx=662，|15-20|=5，T和=3+3=6，c_0 = 4+5+(5-1) = 13，pen = 0+2 = 2，c_1 = 15；
   - H3-H6：dx=1002，|15-19|=4，T和=3+5=8，c_0 = 4+4+(5-3) = 10，pen = 4+2 = 6，c_1 = 16；
   - H4-H7：dx=962，|22-18|=4，T和=2+5=7，c_0 = 4+4+(5-3) = 10，pen = 4+2 = 6，c_1 = 16。
2. 中距边（9 条）：
   - H1-H5：dx=1500，Δ=8，T和=5，c_0 = 9+8+4 = 21，pen = 0+2 = 2，c_1 = 23；
   - H1-H6：dx=1840，Δ=9，T和=7，c_0 = 9+9+2 = 20，pen = 4+2 = 6，c_1 = 26；
   - H1-H7：dx=2128，Δ=10，T和=7，c_0 = 9+10+2 = 21，pen = 4+2 = 6，c_1 = 27；
   - H2-H6：dx=1412，Δ=5，T和=6，c_0 = 9+5+2 = 16，pen = 4+0 = 4，c_1 = 20；
   - H2-H7：dx=1700，Δ=6，T和=6，c_0 = 9+6+2 = 17，pen = 4+0 = 4，c_1 = 21；
   - H2-H8：dx=2027，Δ=7，T和=7，c_0 = 9+7+1 = 17，pen = 8+0 = 8，c_1 = 25；
   - H4-H8：dx=1289，Δ=5，T和=8，c_0 = 9+5+1 = 15，pen = 8+2 = 10，c_1 = 25；
   - H4-H9：dx=1589，Δ=6，T和=6，c_0 = 9+6+3 = 18，pen = 0+2 = 2，c_1 = 20；
   - H4-H11：dx=2079，Δ=8，T和=7，c_0 = 9+8+2 = 19，pen = 4+2 = 6，c_1 = 25。
（注：其余 20 对分别因 dx > 2200、规格差 < 4 如 H3-H7/H8/H9/H10 与 H4-H5/H6、或 T和 < 5 如 H2-H5(4) 和 H4-H10(4) 被剔除。）

三、小问 3（完整合法两对方案计数与分组）
从 12 条兼容边中无序任取两条端点互不复用的边（a1 ≠ a2 且 b1 ≠ b2），且要求所选两个 B 组挂钩恰好 1 个带 USA（U=1 集合为 {H7, H9, H11}，U=0 集合为 {H5, H6, H8}）。按所含唯一 USA 边枚举并去重（按 A 组编号升序规范化）：
- 含 H1-H7（U=1, B=3）配非 USA 边（a ≠ H1）：可选 H2-H6(B=3)、H2-H8(B=4)、H3-H5(B=1)、H3-H6(B=3)、H4-H8(B=4)，共 5 种（M 组 4 种，N 组 1 种：H1-H7;H3-H5）。
- 含 H2-H7（U=1, B=3）配非 USA 边（a ≠ H2）：可选 H1-H5(B=1)、H1-H6(B=3)、H3-H5(B=1)、H3-H6(B=3)、H4-H8(B=4)，共 5 种（M 组 3 种，N 组 2 种：H1-H5;H2-H7 与 H2-H7;H3-H5）。
- 含 H4-H7（U=1, B=3）配非 USA 边（a ≠ H4）：可选 H1-H5(B=1)、H1-H6(B=3)、H2-H6(B=3)、H2-H8(B=4)、H3-H5(B=1)、H3-H6(B=3)，共 6 种（M 组 4 种，N 组 2 种：H1-H5;H4-H7 与 H3-H5;H4-H7）。
- 含 H4-H9（U=1, B=2）配非 USA 边（a ≠ H4）：可选 H1-H5(B=1)、H1-H6(B=3)、H2-H6(B=3)、H2-H8(B=4)、H3-H5(B=1)、H3-H6(B=3)，共 6 种（仅 H2-H8;H4-H9 满足 B和=6 属 M 组，其余 5 种 B和 ≤ 5 属 N 组）。
- 含 H4-H11（U=1, B=3）配非 USA 边（a ≠ H4）：可选 H1-H5(B=1)、H1-H6(B=3)、H2-H6(B=3)、H2-H8(B=4)、H3-H5(B=1)、H3-H6(B=3)，共 6 种（M 组 4 种，N 组 2 种：H1-H5;H4-H11 与 H3-H5;H4-H11）。
合计：合法方案总数 P = 5 + 5 + 6 + 6 + 6 = 28，其中 M 组 P_M = 4+3+4+1+4 = 16，N 组 P_N = 1+2+2+5+2 = 12。

四、小问 4（工况 0 最优与并列）
- M 组（16 种）中，唯一同时使用两条近距边（c_0 = 10）的方案为 H3-H6;H4-H7，其 C_0 = 10 + 10 = 20；次优为 H2-H6;H4-H7（16+10=26）等，故 C0_M = 20，并列数 ties0_M = 1。
- N 组（12 种）中，唯一同时使用两条近距边的方案为 H3-H5;H4-H7，其 C_0 = 13 + 10 = 23；次优为 H3-H6;H4-H9（10+18=28）与 H2-H7;H3-H5（17+13=30）等，故 C0_N = 23，并列数 ties0_N = 1。

五、小问 5（工况 1 最优与并列）
- M 组（16 种）：
  * H3-H6;H4-H7：C_1 = 16 + 16 = 32；
  * H2-H6;H4-H7：C_1 = 20 + 16 = 36；
  * H2-H7;H3-H6：C_1 = 21 + 16 = 37；
  其余方案 C_1 ≥ 37。故 C1_M = 32，并列数 ties1_M = 1（唯一最优 H3-H6;H4-H7）。
- N 组（12 种）：
  * H3-H5;H4-H7：C_1 = 15 + 16 = 31（H5 仅 3 把总库存不触发 B 组重载加罚，仅 H7 触发 +4、H3 与 H4 各触发 +2）；
  * H3-H5;H4-H9：C_1 = 15 + 20 = 35；
  * H2-H7;H3-H5：C_1 = 21 + 15 = 36；
  * H3-H6;H4-H9：C_1 = 16 + 20 = 36；
  其余方案 C_1 ≥ 38。故 C1_N = 31，并列数 ties1_N = 1（唯一最优 H3-H5;H4-H7）。

六、小问 6（赢家反转与规范代表方案）
- 工况 0：M 组 20 < N 组 23，赢家 W0 = M；
- 工况 1：N 组 31 < M 组 32，赢家 W1 = N；
- 赢家由 M 反转为 N，反转位 rev = 1；
- 工况 1 赢家组（N 组）唯一最小代价方案的规范编码为 H3-H5;H4-H7。

最终标准答案：
20,23,18,16,14|12,3|28,16,12|20,1,23,1|32,1,31,1|M,N,1,H3-H5;H4-H7"""

response_text = base["canonical_answer"]

platform_points = [
    {
        "num": 1,
        "xy": (1338, 895),
        "kind": "作者关键证据点",
        "title": "H3 挂钩（非单调规格 15 mm + 3 层叠挂红柄）",
        "desc": "位于 24 mm（H2）与 22 mm（H4）之间但正面刻字实为 15 mm，且三角挂孔内可见 3 层钢板、底孔内可见后方 2 把长红柄的双层橙环（R_3 = 3）。按递减误读为 23 或漏读叠挂均会导致近距边 H3-H5 失效，直接将反转位由 1 翻转为 0。"
    },
    {
        "num": 2,
        "xy": (1666, 955),
        "kind": "实测模型误读点（盲测 2/3 轮次错读）",
        "title": "H4 挂钩（22 mm 紧贴叠挂 2 把红柄）",
        "desc": "左侧银色钳口、橙色颈圈与红柄侧缘清晰可见双层叠挂（R_4 = 2；同理 H1 也为紧贴 2 层）。独立盲测第 2、3 轮均将 H1/H4 漏读为 1 把，导致 sum_R 少计 2、兼容边 H1-H5 缺失，且工况 1 漏计 H4 的 R_a ≥ 2 防卡滞加罚（C1_M 32→30、C1_N 31→29）。"
    },
    {
        "num": 3,
        "xy": (2340, 1015),
        "kind": "实测模型误读点（盲测 1/3 轮次错读）",
        "title": "H6 挂钩（19 mm 叠挂 3 层蓝柄 + 背后 2 把红柄）",
        "desc": "蓝柄顶部可见 3 层独立圆拱、蓝黑交界处可见 3 段高低错落的蓝套下缘（B_6 = 3），且背后叠挂 2 把红柄（R_6 = 2，T_6 = 5）。盲测第 2 轮误将 H6 蓝柄读为 2 把，导致 H3-H6;H4-H7 落入轻蓝柄组 N、两工况均由 N 胜且反转位由 1 翻转为 0。"
    },
]

# Build SVG markers overlay (exact native viewBox 0 0 4716 3144)
svg_markers = []
for pt in platform_points:
    x, y = pt["xy"]
    n = pt["num"]
    color = "#e11d48" if n > 1 else "#f59e0b"
    svg_markers.append(f'''
      <g>
        <circle cx="{x}" cy="{y}" r="88" fill="none" stroke="#ffffff" stroke-width="26" opacity="0.95"/>
        <circle cx="{x}" cy="{y}" r="88" fill="none" stroke="{color}" stroke-width="14"/>
        <line x1="{x-125}" y1="{y}" x2="{x-46}" y2="{y}" stroke="{color}" stroke-width="10"/>
        <line x1="{x+46}" y1="{y}" x2="{x+125}" y2="{y}" stroke="{color}" stroke-width="10"/>
        <line x1="{x}" y1="{y-125}" x2="{x}" y2="{y-46}" stroke="{color}" stroke-width="10"/>
        <line x1="{x}" y1="{y+46}" x2="{x}" y2="{y+125}" stroke="{color}" stroke-width="10"/>
        <circle cx="{x}" cy="{y}" r="16" fill="{color}" stroke="#ffffff" stroke-width="6"/>
        <circle cx="{x+96}" cy="{y-96}" r="66" fill="{color}" stroke="#ffffff" stroke-width="12"/>
        <text x="{x+96}" y="{y-70}" text-anchor="middle" fill="#ffffff" font-size="78" font-weight="700" font-family="system-ui, sans-serif">{n}</text>
      </g>''')
svg_overlay = "\n".join(svg_markers)

hook_rows = []
for h in recompute["hooks"]:
    tot = h["blue"] + h["red"]
    usa_str = "—" if h["group"] == "A" else ("1 (Park Tool USA)" if h["usa"] else "0 (Park Tool®)")
    hook_rows.append(
        f"<tr><td><strong>{h['id']}</strong></td><td>{h['group']} 组</td><td>{h['front_brand']}</td>"
        f"<td>{h['size']} mm</td><td>{h['blue']}</td><td>{h['red']}</td><td><strong>{tot}</strong></td>"
        f"<td>{usa_str}</td><td>({h['x']}, {h['y']})</td></tr>"
    )

field_specs = [
    ("q1_sum_blue", bf["q1_sum_blue"], "把", "精确整数", "0", "小问 1：H1–H12 蓝柄总把数"),
    ("q1_sum_red", bf["q1_sum_red"], "把", "精确整数", "0", "小问 1：H1–H12 红柄总把数（含蓝柄背后红柄）"),
    ("q1_usa_sizes", bf["q1_usa_sizes"], "mm 列表", "精确有序字符串", "无", "小问 1：B 组印有 USA 的规格（从左到右逗号分隔）"),
    ("q2_edges", bf["q2_edges"], "条", "精确整数", "0", "小问 2：跨组兼容边总数"),
    ("q2_near_edges", bf["q2_near_edges"], "条", "精确整数", "0", "小问 2：近距兼容边数（dx ≤ 1180 px）"),
    ("q3_total_plans", bf["q3_total_plans"], "种", "精确整数", "0", "小问 3：合法无序两对方案总数"),
    ("q3_M_plans", bf["q3_M_plans"], "种", "精确整数", "0", "小问 3：高蓝柄备件组 M 方案数"),
    ("q3_N_plans", bf["q3_N_plans"], "种", "精确整数", "0", "小问 3：轻蓝柄备件组 N 方案数"),
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
    f"<tr class='baseline-row'><td><strong>标准正确读法</strong></td><td>4× 微距复核全部 12 钩真实属性</td>"
    f"<td>{bf['q1_sum_blue']} / {bf['q1_sum_red']}</td><td>{bf['q2_edges']} ({bf['q2_near_edges']})</td>"
    f"<td>{bf['q3_total_plans']} ({bf['q3_M_plans']}/{bf['q3_N_plans']})</td>"
    f"<td>M={bf['q4_M_min_c0']}, N={bf['q4_N_min_c0']} → {bf['q6_winner_w0']}</td>"
    f"<td>M={bf['q5_M_min_c1']}, N={bf['q5_N_min_c1']} → {bf['q6_winner_w1']}</td>"
    f"<td><strong>{bf['q6_reversal']}</strong></td><td><code>{bf['q6_w1_canonical_plan']}</code></td></tr>"
)
for cf in recompute["counterfactuals"]:
    f = cf["fields"]
    rev_cls = " class='flip-cell'" if cf["flips_reversal"] else ""
    cf_rows.append(
        f"<tr><td><code>{html.escape(cf['id'])}</code></td><td>{html.escape(cf['description'])}</td>"
        f"<td>{f['q1_sum_blue']} / {f['q1_sum_red']}</td><td>{f['q2_edges']} ({f['q2_near_edges']})</td>"
        f"<td>{f['q3_total_plans']} ({f['q3_M_plans']}/{f['q3_N_plans']})</td>"
        f"<td>M={f['q4_M_min_c0']}, N={f['q4_N_min_c0']} → {f['q6_winner_w0']}</td>"
        f"<td>M={f['q5_M_min_c1']}, N={f['q5_N_min_c1']} → {f['q6_winner_w1']}</td>"
        f"<td{rev_cls}><strong>{f['q6_reversal']}</strong></td><td><code>{html.escape(str(f['q6_w1_canonical_plan']))}</code></td></tr>"
    )

blind_rows = []
for tr in blind["trials"]:
    badge = "<span class='badge ok'>整题正确 (20/20)</span>" if tr["exact_match"] else f"<span class='badge err'>整题错答 ({tr['correct_fields']}/20)</span>"
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
<title>ZeroBench 作者填报记录 · ZB-TOOLS-151686260-v1</title>
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
  <h1>ZeroBench 视觉联合推理作者填报页 · ZB-TOOLS-151686260-v1</h1>
  <p>自行车锥形扳手挂板多属性盘点、水平投影测距与两工况联合调度反转（离线平台填报版）</p>
</header>

<!-- 1. 基本信息 -->
<section id="sec-basic">
  <div class="sec-head">
    <h2>一、基本信息</h2>
    <button class="btn-copy" data-target="copy-basic">复制基本信息</button>
  </div>
  <div class="meta-grid">
    <div class="meta-item"><span class="k">题号</span><span class="v">ZB-TOOLS-151686260-v1</span></div>
    <div class="meta-item"><span class="k">题名</span><span class="v">自行车修车挂板扳手多层叠挂盘点与两工况联合调度反转</span></div>
    <div class="meta-item"><span class="k">一级题型 / 候选题型</span><span class="v">计数聚合链（主）；定位度量、抗干扰文本读取、复杂指令遵循</span></div>
    <div class="meta-item"><span class="k">图片大类与小类</span><span class="v">实拍密集场景照 · 居家场景 / 工具五金（真实照片 real_photo）</span></div>
    <div class="meta-item"><span class="k">原图尺寸与文件</span><span class="v">4716 × 3144 px（EXIF=1，RGB JPEG，zb-hardware-151686260.jpg）</span></div>
    <div class="meta-item"><span class="k">来源页与资产编号</span><span class="v">Wikimedia Commons Page ID 151686260 · File:Bicycle_cone_wrenches_at_Somerville_Bike_Kitchen.jpg</span></div>
    <div class="meta-item"><span class="k">作者署名</span><span class="v">4300streetcar（Own work）</span></div>
    <div class="meta-item"><span class="k">许可协议</span><span class="v">CC BY 4.0（https://creativecommons.org/licenses/by/4.0）</span></div>
  </div>
  <textarea id="copy-basic" hidden>题号：ZB-TOOLS-151686260-v1
题名：自行车修车挂板扳手多层叠挂盘点与两工况联合调度反转
题型：计数聚合链（兼定位度量、抗干扰文本读取、复杂指令遵循）
图片类别：实拍密集场景照 / 居家场景-工具五金（真实照片）
原图尺寸：4716×3144 px（zb-hardware-151686260.jpg）
来源：https://commons.wikimedia.org/wiki/File:Bicycle_cone_wrenches_at_Somerville_Bike_Kitchen.jpg
作者：4300streetcar
许可：CC BY 4.0（https://creativecommons.org/licenses/by/4.0）</textarea>
</section>

<!-- 2. 原图与打点对照 -->
<section id="sec-images">
  <div class="sec-head">
    <h2>二、原图与打点对照</h2>
    <button class="btn-copy" data-target="copy-points">复制打点坐标说明</button>
  </div>
  <div class="compare-grid">
    <figure>
      <figcaption>左：干净原图（上传平台主图，4716 × 3144 px 未修改）</figcaption>
      <div class="img-stage">
        <img src="zb-hardware-151686260.jpg" alt="干净原图 zb-hardware-151686260.jpg" width="{W}" height="{H}">
      </div>
    </figure>
    <figure>
      <figcaption>右：同画幅叠加 3 个关键打点（SVG viewBox 0 0 4716 3144 精确缩放对齐）</figcaption>
      <div class="img-stage">
        <img src="zb-hardware-151686260.jpg" alt="打点对照图 zb-hardware-151686260.jpg" width="{W}" height="{H}">
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
  <textarea id="copy-points" hidden>点1：(1338, 895) [28.37%, 28.47%] | 作者关键证据点 | H3 挂钩：左红柄区非单调刻字 15（位于 24 与 22 之间）且同钩叠挂 3 把红柄，决定兼容边 H3-H5 与两工况反转。
点2：(1666, 955) [35.33%, 30.38%] | 模型误读点（盲测 2/3 错读） | H4 挂钩：22 mm 红柄实际紧贴叠挂 2 把（橙颈/钳口双层），漏读为 1 把将漏计工况 1 防卡滞加罚并改变总库存。
点3：(2340, 1015) [49.62%, 32.28%] | 模型误读点（盲测 1/3 错读） | H6 挂钩：19 mm 蓝柄实际叠挂 3 层蓝套且背后有 2 把红柄，误读为 2 蓝柄将改变 M/N 分组边界并使反转位由 1 翻转为 0。</textarea>
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
  <h3>H1–H12 逐钩核验事实表（供审题人快速核对）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>挂钩</th><th>分组</th><th>最前品牌</th><th>正面规格</th><th>蓝柄 B_i</th><th>红柄 R_i</th><th>总把数 T_i</th><th>品牌后缀 U_i</th><th>钩心坐标 (x, y)</th></tr>
      </thead>
      <tbody>
        {"".join(hook_rows)}
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
  <h3>逐字段判分口径（共 20 个可判分字段）</h3>
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
    <li><strong>离线指标质检结论</strong>：<span class="badge ok">decision = authoring_candidate</span>（阻断项 <code>0</code>、待复核项 <code>0</code>、提醒项 <code>0</code>）；<code>difficulty_status = documented_failure_evidence_requires_human_acceptance</code>。</li>
    <li><strong>原图与密集/遮挡统计</strong>：原图 <code>{mt['width']}×{mt['height']} px</code>（EXIF=1，RGB），中文覆盖率 <code>0.0%</code>，无人物/人脸及水印遮挡；登记 <code>{mt['object_count']}</code> 个对象（<code>{mt['class_count']}</code> 类），近色异类邻居 <code>{mt['nearcolor_pair_count']}</code> 对、边界框投影重叠候选 <code>{mt['bbox_overlap_pair_count']}</code> 对，6 个原生 ROI 裁图均经人工 4× 微距复核清晰可辨。</li>
    <li><strong>多层联合推理图与测距稳健性</strong>：作者登记推理 DAG 含 <code>{rm['node_count']}</code> 节点、最大深度 <code>{rm['max_depth']}</code> 层、<code>{rm['multi_visual_join_nodes']}</code> 个多视觉源合流节点，6 个小问输出视觉祖先覆盖率 <code>100%</code>。水平投影测距单端点误差上界 <code>12 px</code>（两点差上界 <code>24 px</code>），近距阈值 <code>1180 px</code> 最小余量 <code>108 px</code>（<code>R = 4.50</code>），上限阈值 <code>2200 px</code> 最小余量 <code>72 px</code>（<code>R = 3.00</code>）；<code>10,000</code> 次联合随机扰动与改用三角形孔心替代锚点复算，全部 20 字段稳定率均为 <code>100%</code>。</li>
    <li><strong>防绕过审查（passed）</strong>：去图无法获取任何库存、非单调规格、USA 分布与钩心横坐标；关键图证横跨全图宽度 <code>x ∈ [450, 4050]</code>，单一大裁图无法覆盖；按单调规律或偶数规律猜读均会直接翻转最终结论。</li>
  </ul>

  <h3>反事实复算差异对照（solver.py 独立重算）</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>读法编号</th><th>图面误读假设</th><th>蓝 / 红总数</th><th>兼容边 (近距)</th><th>方案 P (M/N)</th><th>工况 0 最小代价→赢家</th><th>工况 1 最小代价→赢家</th><th>反转位</th><th>工况 1 代表方案</th></tr>
      </thead>
      <tbody>
        {"".join(cf_rows)}
      </tbody>
    </table>
  </div>

  <h3>定稿前 3 次独立盲答试答摘要（冻结题面 v1 + 干净原图，工具开放）</h3>
  <p style="font-size:13.5px; margin:6px 0 8px;">有效完整试答 <strong>3 / 3</strong>（超时 0、工具故障 0、残缺答案 0），整题完全正确 <strong>1 / 3</strong>，整题错答 <strong>2 / 3</strong>。两份错答均为紧贴多层叠挂的预期视觉误读，将盲答最终采用的事实表代入 <code>solver.py</code> 均实现 <strong>100% 逐字段复现</strong>，未发现题面歧义或判分问题。</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>轮次</th><th>判分结果</th><th>提交末答</th><th>错答字段</th><th>归因与复算验证</th></tr>
      </thead>
      <tbody>
        {"".join(blind_rows)}
      </tbody>
    </table>
  </div>
  <textarea id="copy-qa" hidden>离线质检：decision=authoring_candidate（0阻断/0待审/0提醒），原图 4716×3144 px（EXIF=1，中文覆盖 0.0%，无隐私水印），20 对象、33 近色异类对、15 投影重叠对，6 个原生 ROI 均人工复核可读。
测距稳健性：单端点误差上界 12 px（总误差上界 24 px），1180 px 阈值余量 108 px（R=4.50），2200 px 阈值余量 72 px（R=3.00），10000 次联合扰动与替代锚点复算稳定率 100%。
反事实复算：对 CF1–CF8 共 8 组显式限定条件的易混读法逐一重算（其余属性不变），全部 8 组均改变 6–13 个可判分字段；其中除 CF3（漏读 H1/H4 双层红柄，工况 0/1 为 20/23→M 与 30/29→N，rev=1）外，其余 7/8 组（CF1、CF2、CF4–CF8）均将反转位由 1 翻转为 0。
三次独立盲答（冻结 v1 + 干净原图，工具开放）：有效 3/3，整题全对 1/3（trial_1 20/20），整题错答 2/3（trial_2 漏读 H1/H4 双层红柄及误读 H6 为 2 蓝柄，7/20 且反转位翻转为 0；trial_3 漏读 H1/H4 双层红柄，14/20），两份错答均可由 solver.py 100% 逐字段复现。</textarea>
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
