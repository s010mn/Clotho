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
