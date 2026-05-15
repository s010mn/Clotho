# G函数闭合候选 physical PKN 体积与微地震/广域电磁对照

本文件是 sprint 分支 Phase 5D / 5D.1 的组会汇报材料。
所有闭合结果都是 **candidate**，不是最终论文级闭合压力解释。

## 1. 研究问题

核心问题：**G函数/闭合候选推导的 physical PKN 体积与外部观测量是否有一致趋势？**

- 目标不是验证注入液量；
- 目标是比较 G函数闭合候选推导的 physical PKN 体积与外部观测量；
- 外部观测量是：
  - microseismic_affected_volume（微地震波及体积）；
  - electromagnetic_affected_area（广域电磁波及面积）。
- raw/effective injected volume 只作为施工规模控制变量，不作为主结论指标；
- 主指标是 **pkn_fracture_volume_m3**（physical PKN storage volume）。

## 2. 旧结果：半缝长口径负相关

此前 PPT 使用**半缝长口径**（2×max_L / 2×mean_L / 2×median_L）对比微地震和广域电磁，出现**负相关**：

| 旧指标 | 对比观测 | Pearson r |
|--------|----------|-----------|
| 2×max_L | 微地震波及体积 | **-0.356** |
| 2×mean_L | 微地震波及体积 | **-0.386** |
| 2×median_L | 微地震波及体积 | **-0.391** |
| 2×max_L | 广域电磁波及面积 | -0.081 |
| 2×mean_L | 广域电磁波及面积 | -0.120 |
| 2×median_L | 广域电磁波及面积 | -0.126 |

**这个负相关不能抹掉。**

解释：主裂缝等效半缝长是一维尺度指标，微地震波及体积和广域电磁波及面积是三维/二维缝网范围指标，口径不同。全段混算时包含裂缝影响段（2–7）、断层段（24）和缺失段（4、25），段型混杂加剧口径不匹配。

## 3. Phase 5D physical PKN 实现

Physical PKN storage volume 公式：

```
V_f,i^phys = (π I_F / E') · L_i · H_w² · P_net,i
```

参数：

- H_w = 50 m（固定）；
- I_F = 0.722464726919（人类指定常数）；
- E' = E / (1 − ν²)；
- stress shadow: `(I + αF)ξ = 1`，Sneddon kernel `F_ij = 1 - d/√(d²+(H_w/2)²)`；
- C from stable P-vs-G dP/dG slope：`C = -(I_F · H_w² · ξ) / (E' · H_p · √tp) · dP/dG`；
- K_lp = 4√π · m · Γ(m) / ((m+0.5) · Γ(m+0.5))；
- volume balance per cluster per stable-segment row：`L_i = V_inj · ratio_i / Σ(unit_j · ratio_j)`。

关键说明：

- canonical `pkn_fracture_volume_m3` 现在是 physical PKN，不再是 MVP；
- legacy MVP 已降级为 `legacy_mvp_pkn_*` 字段；
- I_F = 0.722464726919 目前按人类指定常数固定；
- I_F 在 volume-balance 中代数消去（同时出现在裂缝存储项和泄滤系数 C 中），因此最终 V_f 值与 I_F 无关，但 I_F 影响计算中间量（半缝长 L 和泄滤系数 C）。

## 4. 当前核心相关性

**警告：只有 3 个段具有 Barree 闭合候选且 physical PKN 成功计算（stage 1, 10, 29）。n=3 下任何相关系数都不具有统计显著性，以下数字仅供参考。**

### 4.1 stage-level detail

| stage | pkn_fracture_volume_m3 | pkn_half_length_mean_m | legacy_mvp_volume_m3 | micro_volume | em_area |
|------:|-----------------------:|-----------------------:|---------------------:|-------------:|--------:|
| 1     | 474.1                  | 100.7                  | 2609.6               | 147.5        | 18435   |
| 10    | 442.4                  | 66.7                   | 2354.6               | 192.0        | 19092   |
| 29    | 63.9                   | 8.6                    | 2941.1               | 142.5        | 18985   |

### 4.2 相关系数

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| physical pkn_fracture_volume_m3 | microseismic_affected_volume | 0.519 | 0.500 | 3 |
| physical pkn_fracture_volume_m3 | electromagnetic_affected_area | -0.427 | -0.500 | 3 |
| no-shadow physical pkn (α=0) | microseismic_affected_volume | 0.519 | 0.500 | 3 |
| no-shadow physical pkn (α=0) | electromagnetic_affected_area | -0.427 | -0.500 | 3 |
| legacy MVP pkn_fracture_volume_m3 | microseismic_affected_volume | -0.874 | -1.000 | 3 |
| legacy MVP pkn_fracture_volume_m3 | electromagnetic_affected_area | -0.077 | -0.500 | 3 |
| physical pkn_half_length_mean_m | microseismic_affected_volume | 0.239 | 0.500 | 3 |
| physical pkn_half_length_mean_m | electromagnetic_affected_area | -0.678 | -0.500 | 3 |
| legacy MVP pkn_half_length_mean_m | microseismic_affected_volume | -0.781 | -0.500 | 3 |
| legacy MVP pkn_half_length_mean_m | electromagnetic_affected_area | -0.952 | -1.000 | 3 |

解释：

- n=3 下所有相关系数均无统计显著性，不应作为物理结论的依据；
- physical PKN 体积与微地震波及体积为正相关方向（0.519），但 n=3；
- physical PKN 体积与广域电磁面积为负相关方向（-0.427），但 n=3；
- legacy MVP 体积与微地震呈强负相关（-0.874），但仅有 3 个数据点，可能被 stage 29 的极低 physical PKN 体积驱动；
- physical PKN vs legacy MVP 方向不同，说明 physical PKN 链路的 stable segment / C / volume balance 与简化 MVP 的 Sneddon average width 产生了不同的 stage 间排序；
- 不能说"验证成功"或"验证失败"。

## 5. 为什么只有 3 个段有 physical PKN

当前 manifest 中 30 个段共处理，但只有 3 个段同时满足：

1. valid falloff window（非 stage 4/25）；
2. Barree tangent closure candidate 被成功检测；
3. stable P-vs-G segment 被成功拟合；
4. physical PKN volume balance 求解成功。

其余 27 段 closure_method=none（未检测到闭合候选），因此没有 physical PKN 体积。这是当前自动检测算法的覆盖率问题，不是代码 bug。提高覆盖率需要：

- 放宽 Barree departure 阈值；
- 增加 McClure compliance candidate 的备选检测；
- 人工标注闭合区间作为补充。

## 6. stress shadow 解释

stress shadow linear system `(I + αF)ξ = 1` 已运行（α=1.0 baseline + α=0 no-shadow control）。

诊断结果：

| stage | alpha=1 volume | alpha=0 volume | volume diff | half_length_mean α=1 | half_length_mean α=0 | xi range |
|------:|---------------:|---------------:|------------:|---------------------:|---------------------:|---------:|
| 1     | 474.1          | 474.1          | 0.000       | 100.7                | 39.9                 | 0.18–0.59 |
| 10    | 442.4          | 442.4          | 0.000       | 66.7                 | 26.2                 | 0.17–0.59 |
| 29    | 63.9           | 63.9           | 0.000       | 8.6                  | 3.4                  | 0.16–0.59 |

- stage-level total physical storage volume 在 baseline（α=1）与 no-shadow control（α=0）中完全相同；
- 这是因为当前 linear volume-balance formulation 中，stress shadow 主要改变簇间半长分配（α=1 时边缘簇更长、中心簇更短），但由于按总注入体积归一化求解，stage-level total physical storage volume 不变；
- 因此本轮 stage-level 相关性不受 shadow control 影响；
- α=1 时半缝长均值为 α=0 时的 ~2.5 倍，标准差增大（簇间差异增大）；
- 后续若要让 stress shadow 改变 stage total volume，需要重新定义体积约束或簇间流量分配模型。

## 7. I_F 说明

- I_F = 0.722464726919，人类指定常数；
- I_F 在 volume-balance 代数中消去：V_f = π/E' × V_inj × ratio_i / Σ(K_j × ratio_j) × H_w² × P_net_i，其中 K_j 不含 I_F；
- I_F 影响中间量：半缝长 L ∝ 1/I_F，泄滤系数 C ∝ I_F；
- 最终 V_f 对 I_F 不敏感；
- 积分表达式确认仍在 TODO。

## 8. 组会建议讲法

1. 已实现 physical PKN storage volume，不再使用旧 MVP 体积作为主指标；
2. 当前只有 3/30 段自动检测到 Barree 闭合候选并成功计算 physical PKN 体积（stage 1, 10, 29）；
3. n=3 下相关系数无统计显著性，当前不能得出物理结论；
4. physical PKN 与 legacy MVP 对 stage 间的排序不同，说明 stable segment / C / volume balance 链路对结果有实质影响；
5. 下一步应提高闭合候选覆盖率（放宽阈值或人工标注），并对更多段进行 physical PKN 计算后重新评估相关性。

## 9. 明确不能写

禁止写：

- "G函数反演体积已被微地震验证"；
- "G函数反演体积已被广域电磁验证"；
- "负相关问题已经消失"；
- "physical PKN 结果证明模型错误"；
- "closure pressure 已最终确定"；
- "n=3 的相关性具有统计意义"。

可以写：

- "physical PKN 体积已实现，但当前只有 3 段有 Barree 闭合候选，样本量不足以评估"；
- "外部观测与 G函数反演体积之间可能存在物理口径差异"；
- "当前结果是 candidate/estimate，需要人工图形复核和更高的闭合覆盖率"；
- "旧半缝长口径的负相关仍然存在于历史数据中"。

## 10. Figures

Figures generated outside repo under `/tmp/gfunction-ref-audit-phase5d1/figures/`
