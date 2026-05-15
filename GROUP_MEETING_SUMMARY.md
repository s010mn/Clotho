# 组会汇报摘要：Clotho deadline closure-volume MVP

本文件是 sprint 分支上 Phase 5A / 5A.1 / 5B 的组会汇报材料。
所有闭合结果都是 **candidate**，不是最终论文级闭合压力解释。

## 1. 当前 sprint 目标

- 为组会 deadline 做 MVP 级别的闭合-体积估算链路；
- 目标是跑通：起裂修正 tp → closure candidate → volume estimate → observations correlation → effective volume sensitivity；
- 这不是最终论文级 closure 解释，不能直接作为闭合压力结论；
- 所有输出标记 `closure_is_candidate=True, closure_is_final_interpretation=False`。

## 2. 数据处理边界

- 使用 Phase 4K keep-last manifest 的 **28 个有效 falloff candidate**；
- observations 有 **30 段**，对应 well4 的 30 个压裂段；
- **stage 4 和 stage 25** 在 manifest 中缺失（无 valid falloff candidate），作为 placeholder 保留在 summary 中；
- placeholder 行保留观测值（微地震/电磁），但闭合和体积估算字段为 NaN/not_computed；
- placeholder 行**不参与**相关性计算（correlation n = 28，不是 30）；
- stage 4 / 25 需要后续人工审查原始曲线，判断是否存在可用压降窗口。

## 3. 自动候选点

### 起裂候选

- 自动识别 fracture initiation candidate，用于 corrected tp；
- 优先规则：sigma_min crossing（压力超过最小主应力 + 排量持续）；
- 退化规则：第一个排量超过 min_rate 的点；
- corrected tp = 停泵时刻 − 起裂候选时刻。

### 闭合候选

- **Barree tangent candidate**：在 G·dP/dG 空间拟合 normal leakoff 直线，寻找偏离点；
- **McClure-style compliance candidate**：在 dP/dG 中寻找局部极小，作为 compliance change screening；
- **selected closure** 默认 barree-then-mcclure 优先级；
- 所有闭合结果标记 `closure_is_candidate=True, closure_is_final_interpretation=False`；
- 结果需要后续人工 plot review 才能作为最终闭合压力。

## 4. Phase 5A.1 主要 smoke 结果

| 指标 | 值 |
|------|-----|
| 输出行数 | 30 |
| 已计算段数 | 28 |
| placeholder 段 | stage 4, 25 |
| 选择方法分布 | barree=27, mcclure=1, none=2 (placeholder) |
| PKN volume status | ok=28, not_computed=2 |
| correlation n | 28 |

### 核心相关性（baseline, perf=0, cwb=0）

| metric | target | Pearson r | Spearman r |
|--------|--------|-----------|------------|
| pkn_fracture_volume_m3 | microseismic_affected_volume | 0.25 | 0.20 |
| pkn_fracture_volume_m3 | electromagnetic_affected_area | 0.34 | 0.06 |
| effective_injected_volume_m3 | microseismic_affected_volume | 0.12 | 0.19 |
| effective_injected_volume_m3 | electromagnetic_affected_area | **0.81** | 0.25 |
| raw_injected_volume_m3 | microseismic_affected_volume | 0.12 | 0.19 |
| raw_injected_volume_m3 | electromagnetic_affected_area | **0.81** | 0.25 |

### 相关性解读（必须谨慎）

- EM affected area 与 raw/effective injected volume 的 Pearson r 较高（0.81），但 **Spearman r 只有 0.25**，说明 rank consistency 不强——少数极端值可能主导了线性相关；
- effective 和 raw 的相关性几乎相同，说明**当前井筒存储修正对相关性没有实质改变**；
- PKN fracture volume 与微地震/电磁的相关性偏弱（Pearson 0.25–0.34），说明 MVP 级 PKN 估算还不能直接用作反演结论；
- 这些都是**统计相关，不是因果验证**，也不能用来"证明"体积反演有效或某观测能被有效进缝液量解释。

## 5. Phase 5B sensitivity 结果

四组 sensitivity：baseline (perf=0, cwb=0), cwb=0.1, cwb=1.0, perf=1.0 MPa。

### 井筒存储 sensitivity

| case | C_wb (m3/MPa) | 最大 storage volume (m3) | effective volume range (m3) |
|------|---------------|--------------------------|----------------------------|
| baseline | 0 | 0 | 2499–3340 |
| cwb=0.1 | 0.1 | 1.56 | 2499–3340 |
| cwb=1.0 | 1.0 | 15.64 | 2495–3335 |

- cwb=0.1：effective volume 下降幅度很小（最大 ~1.6 m3 / ~3200 m3 ≈ 0.05%），相关性几乎不变；
- cwb=1.0：effective volume 下降幅度仍然有限（最大 ~15.6 m3 / ~3200 m3 ≈ 0.5%），EM area Pearson 从 0.807 降到 0.804，Spearman 从 0.250 降到 0.238；
- **结论**：当前 closure pressure 范围下，井筒存储修正对有效进缝液量和相关性的影响非常小。这可能是因为 P_shut − P_closure 差值不大，也可能是 C_wb 取值偏低。C_wb 的合理取值需要后续根据井筒几何校准（见 TODO #15）。

### 射孔摩阻 sensitivity

| case | perf friction (MPa) | PKN volume Pearson vs EM area | PKN volume Pearson vs micro |
|------|---------------------|-------------------------------|----------------------------|
| baseline | 0 | 0.335 | 0.248 |
| perf=1.0 | 1.0 | 0.328 | 0.238 |

- perf=1.0 MPa 对 PKN volume 相关性影响很小（Pearson 变化 < 0.01）；
- 射孔摩阻当前只是 pressure correction sensitivity，不是完整 perforation friction model；
- 射孔摩阻公式/单位的校准仍是 TODO（见 TODO #14）。

## 6. 组会建议讲法

1. **已跑通候选闭合与体积对照链路**：从停泵数据出发，自动生成起裂候选 → 闭合候选 → 体积估算 → 观测相关性的全链路 CSV 输出。
2. **28/30 段可形成 closure-volume estimate**：stage 4 / 25 缺有效压降窗口，需要人工补审。
3. **PKN volume 与微地震/电磁相关性不强**：说明 MVP 级简化 PKN 估算还不能当最终反演结论。
4. **注入量与电磁面积 Pearson 较高但 Spearman 弱**：不能直接做因果结论，可能被少数极端值驱动。
5. **下一步应做**：人工 plot review、主动放压/水锤剔除、射孔摩阻/井筒存储标定、完整 McClure/Barree 不确定性、rigorous Carter leakoff。

## 7. 明确未完成（引用 TODO.md）

以下工作仍需完成，才能从 MVP candidate 进入论文级 interpretation：

- Full McClure nonlinear fracture-compliance inversion（当前只做 dP/dG 局部极小 screening）；
- Barree tangent fit uncertainty 和 manual plot confirmation；
- Rigorous Carter leakoff integration（当前只有粗估）；
- Calibrated PKN model（当前用简化 Sneddon 平面应变）；
- Stress-shadow 段间应力干扰；
- Cluster allocation 簇级体积分配；
- Automatic active-bleedoff detection（当前依赖人工指定窗口终点）；
- Water-hammer high-frequency diagnosis（Phase 4N1 只做了低频 plausibility 标记）；
- Stage 4 / 25 manual review；
- Pressure smoothing 和 resampling；
- 有效进缝液量的液体类型/支撑剂修正；
- Uncertainty / sensitivity analysis；
- **最终论文级闭合压力判定必须包含人工 plot review**。

### 禁止表述

- 不能把任何结果写成"已确定闭合压力"；
- 不能写成"体积反演已验证有效"；
- 不能写成"电磁面积被有效进缝液量解释"；
- 不能写成"已完成论文级反演"；
- 相关性只是统计关联，不是因果关系。
