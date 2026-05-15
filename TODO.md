# TODO — Clotho 未完成的严谨物理工作

本清单记录 deadline closure-volume MVP 中已简化或跳过的严谨物理工作。
MVP 的闭合结果都是 candidate，不是最终论文级模型。

## 1. Carter 泄失积分

当前 PKN volume-balance 使用粗估 `C_L = |slope| * h_f / (4 * E' * sqrt(tp))`。
需要实现 Carter 积分：`V_leak = 2 * C_L * A_f * g(t_D, alpha)`，
包括时间相关的泄失面积增长和正确的 g-function 积分形式。

## 2. Stress-shadow 段间应力干扰

当前模型不考虑前序段闭合对后续段最小主应力的影响。
需要实现段间应力干扰修正：`sigma_min_eff(i) = sigma_min + sum(delta_sigma(j))`, j < i。

## 3. Cluster allocation 簇级体积分配

当前 PKN 估算只输出单段总体积。
需要实现多簇分配模型（均匀分配 baseline + 非均匀分配 sensitivity）。

## 4. Pressure smoothing 压力平滑

当前导数直接用 `np.gradient` 在原始采样上计算，不做平滑。
低频采样噪声会直接传到导数。需要评估 Bourdet 对数导数平滑或 moving-window 方案。

## 5. Automatic active-bleedoff detection 自动主动放压识别

当前依赖人工 `--valid-falloff-end-elapsed` 指定有效压降窗口终点。
需要自动识别主动放压 onset（rate > 0 重启、压力梯度突变等）。

## 6. Resampling 非均匀采样重采样

当前不做重采样。实际数据在 early time 采样密集、late time 稀疏。
需要评估对导数计算的影响，并实现可选的等间距重采样。

## 7. PKN 校准与真实裂缝几何

当前 PKN 宽度用简化 Sneddon 平面应变公式 `w = net_p * h_f / (2 * E')`。
需要对比 KGD、radial 等几何模型，并用微地震约束校准。

## 8. McClure nonlinear fracture-compliance inversion

当前 McClure-style screening 只找 dP/dG 局部极小。
需要实现完整 nonlinear compliance inversion：
拟合 `dP/dG = f(G)` 的非线性 compliance 模型，估计 compliance 变化点。

## 9. Multiple closure event detection 多次闭合事件

当前只选一个 closure candidate。
需要支持多次闭合（如 tip closure + main closure）的识别和排序。

## 10. ISIP automatic picking 自动 ISIP 识别

当前不自动识别 ISIP (instantaneous shut-in pressure)。
需要从停泵后压力曲线自动提取 ISIP 候选，作为闭合分析上界。

## 11. Volume balance with variable leakoff 变泄失体积平衡

当前泄失系数 C_L 在整个压降过程中视为常数。
需要支持时间/压力相关的变泄失系数，特别是 closure 前后的泄失变化。

## 12. Uncertainty / sensitivity analysis 不确定性分析

当前闭合候选和体积估算没有不确定性量化。
需要实现：
- Barree tangent fit fraction sensitivity；
- PKN 参数（E, nu, h_f）的 Monte Carlo 或区间分析；
- 多方法（Barree vs. McClure）的 candidate 离散度统计。

## 13. Barree tangent fit 不确定性与人工确认

当前 Barree tangent 只输出一个 candidate，没有 fit 不确定性区间。
最终论文工作流必须包含人工 plot review 确认 tangent departure 位置。
fit_fraction 和 residual_sigma_factor 的 sensitivity 也需要量化。

## 14. 射孔摩阻公式/单位校准

当前 `perforation_friction_mpa` 作为用户输入常数。
需要根据射孔参数（孔密度、孔径、孔数）和排量估算射孔摩阻，
并校准单位一致性（MPa vs. psi）。

## 15. 井筒存储系数校准

当前 `wellbore_storage_coeff_m3_per_mpa` 作为用户输入常数。
需要根据井筒几何（井径、完井液压缩系数、井深）估算 C_wb，
或通过 early-time 压力响应拟合。

## 16. 有效进缝液量的液体类型/支撑剂修正

当前有效进缝液量只做井筒存储和射孔摩阻修正。
如果获得滑溜水/胶液/支撑剂分段注入数据，
需要按液体类型密度和支撑剂体积分数修正有效液量。

## 17. Stage 4 / 25 缺失有效压降候选人工审查

Stage 4 和 25 在 Phase 4K manifest 中缺失（无 valid falloff candidate）。
需要人工审查原始曲线，判断是否存在可用压降窗口，
或确认为 active bleedoff / 数据缺失。

## 18. 最终论文工作流必须包含人工 plot review

最终论文级闭合压力判定不能只依赖自动 candidate。
工作流必须要求：
- 人工查看 G·dP/dG vs G plot 确认 tangent departure；
- 人工查看 dP/dG vs G plot 确认 compliance minimum；
- 人工对比 Barree 和 McClure candidate 是否一致；
- 人工确认 closure 结果后才标记 closure_is_final_interpretation=True。

## 19. I_F=0.722464726919 积分表达式确认

当前 I_F 按人类指定常数 0.722464726919 固定。
I_F 在 volume-balance 中代数消去（最终 V_f 不依赖 I_F），但影响中间量（L ∝ 1/I_F, C ∝ I_F）。
需要确认 I_F 的积分表达式来源和推导。

## 20. Stress-shadow 对 stage total volume 的耦合

当前 linear volume-balance formulation 中，stress shadow 主要改变簇间半长分配。
由于按总注入体积归一化求解，stage-level total physical storage volume 在 α=1 和 α=0 时相同。
若要让 stress shadow 改变 stage total volume，需要重新定义体积约束或簇间流量分配模型。

## 21. Physical PKN stable segment 人工复核

stable P-vs-G segment 自动检测（longest-first R² search）需要人工复核：
- 确认选段是否在 normal leakoff 区间；
- 确认 dP/dG slope 物理合理性；
- 评估 min_elapsed_seconds / min_points / min_r2 参数敏感性。

## 22. Physical PKN 不确定性与段型分层

当前 physical PKN volume 没有不确定性量化。
需要实现：
- stable segment rows 间的 volume 标准差作为不确定性指标；
- 按段型分组（常规 / 裂缝影响 / 断层）分层计算相关性；
- 提高 Barree 闭合覆盖率（当前只有 3/30 段有 physical PKN）。

## 23. Stress-shadow flow allocation 验证

当前 stress-shadow-weighted η_i 是 model assumption。
需要用 DAS（分布式声学传感）/ PLT（production log test）/ 簇级进液量标定数据验证 η_i 分配是否合理。
当前 volume-balance 代数结构导致 η_i 不影响 stage total volume，只改变逐簇分配；
后续若需要 η_i 影响 stage total，需要更完整的簇级流量不平衡 coupled model。

## 24. Decouple C_L 与 ξ 使 stress shadow 真正改变 stage total V_f

Phase 5D.4 实现了 direct per-cluster denominator `L_i = η_i · V_inj / unit_i`，
但 stage total V_f 在 shadow_eta / uniform_eta / no_shadow 之间仍然完全相同。
根因：当前 coupled assumption 同时令 `P_net_i ∝ ξ_i` 和 `C_L_i ∝ ξ_i`，
导致 `unit_i ∝ ξ_i`，进而 V_f_i = K·P_base·η_i·V_inj/U_base，
Σ V_f_i = K·P_base·V_inj/U_base 与 ξ_i / η_i 都无关。

要让 stress shadow 真正影响 stage total V_f，需要在物理模型层面解耦 C_L 与 ξ，例如：

- C_L 取为 stage-level 标量（从 stable dP/dG slope 推导），不再 per-cluster ∝ ξ；
- 或保留 P_net_i ∝ ξ_i，但用独立的 segment slope 或 calibrated leakoff coefficient；
- 或重新表述 cluster-level flow imbalance 的耦合模型（簇间泄滤面积/时间不同）。

这是 *physical assumption* 层面的改动，不是 numerical fix。需要先与人类确认物理口径。

**Phase 5D.5 进度**: 已实现 `--pkn-C-coupling {stage-constant, shadow-scaled}`，
其中 stage-constant 为 baseline，shadow-scaled 为 control。
stage-constant 已让 stage total V_f 随 ξ/η 变化（test_stage_constant_breaks_previous_cancellation 通过）。
但 storage 与微地震仍为负相关；leakoff/nonstorage 出现正相关，但与 raw/effective_injected 共线性强。
后续需要 Carter calibration 区分纯 leakoff 与注入规模效应。

## 25. Carter leakoff calibration 分离纯 leakoff 与注入规模效应

Phase 5D.5 发现 `pkn_leakoff_volume_m3` / `pkn_nonstorage_volume_m3` 与电磁面积呈 Pearson +0.594，
但 `effective_injected_volume_m3` 自身与电磁面积 Pearson +0.807。
当前 pkn_storage_fraction <10%，nonstorage ≈ effective_injected，
所以 leakoff/nonstorage 的正相关无法独立于注入规模解释。

需要：

- 独立估计 Carter leakoff（不依赖 effective_injected）；
- 比较 pkn_leakoff_volume_m3 与 effective_injected_volume_m3 的残差 vs 微地震/电磁；
- 或用 leakoff_fraction (per-volume) 替代绝对体积，剔除规模效应；
- pkn_leakoff_fraction 当前已实现，但 Pearson 较弱（vs micro +0.233, vs EM +0.087）；
- 需要更高维分析（partial correlation 或 multiple regression）。

## 26. shut-in fluid efficiency 偏低（Phase 5D.6 blocker）

Phase 5D.6 输出 well4 shut-in fluid efficiency median ~8%，27/28 段 < 20%，19/28 < 10%。
这显著低于"压裂液效率约 20%"的工程经验值。
G 项不是主因（stable_G_leakoff_unit_fraction median ~4%），主导项是 preclosure leakoff（unit 中 ~93–99%），由 C_stage 驱动。
pkn_C_multiplier_to_20pct median ~0.28，提示当前 C_stage 大致需要缩小到原来的 1/3.5 才能达到 20%。

候选解释（全部是 sanity check，不是物理结论）：

- stable segment 选段过早或过晚，导致 dP/dG slope 过大；
  - stage 5 slope=-930 MPa, r²=0.81 是极端例子，可能采到 early transient；
  - 需要人工 plot review 复核选段；
- H_p = fleak·H_w = 25 m 偏小，导致 C 公式 `C = -(I_F·H_w²)/(E'·H_p·√tp)·dP/dG` 把 |dP/dG| 放大；
- tp 或 sqrt(tp) 单位（rate-time-unit=minute, tp 应为 seconds）需要复核；
- I_F 在 C 公式里整体口径需要复核；
- Carter leakoff 模型与从 stable slope 反推的 C 在物理上不一致；
- 有效液量 (V_inj_eff) 包含井筒存储 / 射孔摩阻校正，但当前 well4 smoke 使用 0 值，可能高估有效液量。

需要做的事：

- 人工 plot review G·dP/dG vs G 与 dP/dG vs G，重新选 stable segment；
- 复核 H_p / fleak 物理来源（fleak=0.5 是 default fallback，stage_params 没给真实 fleak）；
- 复核 tp 单位（rate_time_unit=minute → tp seconds 路径）；
- 复核 I_F=0.722464726919 的来源积分 (TODO #19)；
- 在确认所有 sanity check 后，决定是否需要重新定义 C_stage（如改用 calibrated Carter C 代替 stable slope）；
- **不通过调 C 强行让 shut-in efficiency 达到 20%**。
