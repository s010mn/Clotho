# G函数闭合候选体积与微地震/广域电磁对照

本文件是 sprint 分支 Phase 5C 的组会汇报材料。
所有闭合结果都是 **candidate**，不是最终论文级闭合压力解释。

## 1. 研究问题

核心问题：**G函数/闭合候选反演体积与外部观测量是否有一致趋势？**

- 不是验证注入液量；
- 是检查通过 G函数闭合候选得到的 PKN 裂缝体积估算，与微地震波及体积、广域电磁波及面积之间的统计关联；
- raw_injected_volume_m3 和 effective_injected_volume_m3 只作为**施工规模/有效液量控制变量**，不作为主结论指标；
- 主指标是 **pkn_fracture_volume_m3**。

## 2. 旧结果回顾：半缝长口径的负相关

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

解释：主裂缝等效半缝长是一维尺度指标，微地震波及体积和广域电磁波及面积是三维/二维缝网范围指标，口径不同。此外，全段混算时包含裂缝影响段（2–7）、断层段（24）和缺失段（4、25），段型混杂加剧了口径不匹配。

## 3. 当前 sprint 新实现

sprint 分支（Phase 5A / 5A.1 / 5B / 5C）新增了从停泵数据到裂缝体积估算的完整链路：

1. **fracture initiation candidate**：自动起裂候选 + corrected tp；
2. **Barree tangent closure candidate**：G·dP/dG 偏离 normal leakoff 直线；
3. **McClure-style compliance closure candidate**：dP/dG 局部极小 screening（不是完整 nonlinear compliance inversion）；
4. **selected closure**：barree-then-mcclure 优先级选择；
5. **有效进缝液量修正**：井筒存储 + 射孔摩阻；
6. **PKN / volume-balance 裂缝体积估算**（pkn_fracture_volume_m3）；
7. **observations correlation**：Pearson + Spearman。

所有闭合结果标记 `closure_is_candidate=True, closure_is_final_interpretation=False`。

## 4. 当前主结果：PKN 裂缝体积 vs 观测

### 4.1 主指标

| metric | target | Pearson r | Spearman r | n |
|--------|--------|-----------|------------|---|
| **pkn_fracture_volume_m3** | **microseismic_affected_volume** | **0.248** | **0.205** | 28 |
| **pkn_fracture_volume_m3** | **electromagnetic_affected_area** | **0.335** | **0.062** | 28 |

**解读**：

- PKN 裂缝体积与微地震波及体积呈**弱正相关**（Pearson 0.25，Spearman 0.21）；
- PKN 裂缝体积与广域电磁波及面积呈**弱正相关**（Pearson 0.34），但 **Spearman 非常弱**（0.06），说明 rank consistency 几乎没有，线性趋势可能被少数极端值驱动；
- 与旧半缝长口径的负相关相比，体积口径至少方向从负变正，但**相关性仍然很弱**。

### 4.2 控制变量（施工规模）

| metric | target | Pearson r | Spearman r | n |
|--------|--------|-----------|------------|---|
| raw_injected_volume_m3 | electromagnetic_affected_area | 0.807 | 0.250 | 28 |
| effective_injected_volume_m3 | electromagnetic_affected_area | 0.807 | 0.250 | 28 |
| raw_injected_volume_m3 | microseismic_affected_volume | 0.120 | 0.188 | 28 |
| effective_injected_volume_m3 | microseismic_affected_volume | 0.120 | 0.188 | 28 |

**注意**：

- raw/effective 注入量与电磁面积的 Pearson 高达 0.81，但 Spearman 只有 0.25——这是被施工规模线性关系驱动的，不是反演结果；
- 当前井筒存储修正对 effective volume 和相关性几乎没有改变（见下文敏感性分析）；
- **这些只作为控制变量参考，不作为主结论。**

## 5. 散点图

以下散点图生成在仓库外：

```
/tmp/gfunction-ref-audit-phase5c/figures/
├── 01_pkn_volume_vs_microseismic.png
├── 02_pkn_volume_vs_em_area.png
├── 03_raw_volume_vs_em_area.png          (控制变量)
├── 04_effective_volume_vs_em_area.png    (控制变量)
├── 05_pkn_volume_grouped_scatter.png     (按段型分组)
└── 06_old_length_vs_current_volume_comparison.png  (旧vs新对比柱状图)
```

散点图包含：

- 所有 stage 编号标注（异常段加粗：2, 3, 4, 5, 7, 8, 10, 21, 24, 25）；
- 按段型分组着色：常规段（蓝）、裂缝影响段 2–7（红）、断层段 24（绿）、缺失段 4/25（黄）；
- stage 4 / 25 因缺 valid falloff manifest 作为 placeholder，体积估算为 NaN，不参与拟合线；
- 拟合线 + Pearson/Spearman/n 标注；
- 图 06 对比柱状图清晰展示：旧半缝长口径为负，当前 PKN 体积口径为弱正。

图片未提交到仓库。

## 6. 敏感性分析

### 6.1 敏感性 grid

Phase 5C 运行了 60 组参数组合（5 × 4 × 3）：

- 井筒存储系数 C_wb = {0, 0.1, 0.5, 1.0, 5.0} m³/MPa
- 射孔摩阻 perf = {0, 1, 2, 5} MPa
- 闭合搜索起始 closure_min_elapsed = {15, 30, 60} s

另外对 f_eff = {0.25, 0.5, 0.75, 1.0} 做了 post-processing sensitivity（对 effective volume 和 PKN volume 乘以 f_eff 系数）。

这是 post-processing sensitivity，不是新的闭合模型。

### 6.2 PKN 裂缝体积相关性的敏感性范围

| metric vs target | Pearson 范围 | Spearman 范围 |
|------------------|-------------|---------------|
| **pkn_fracture_volume vs microseismic** | **[0.131, 0.372]** | **[0.117, 0.381]** |
| **pkn_fracture_volume vs electromagnetic** | **[0.311, 0.398]** | **[0.044, 0.171]** |
| effective_volume vs microseismic | [0.120, 0.129] | [0.175, 0.210] |
| effective_volume vs electromagnetic | [0.784, 0.807] | [0.188, 0.263] |

### 6.3 关键发现

1. **对 pkn_fracture_volume 相关性影响最大的参数是 closure_min_elapsed_seconds**：从 15 s 延长到 60 s 会改变闭合候选位置，从而改变 net pressure 和体积估算。Pearson vs 微地震从 ~0.25 可变到 ~0.13 或 ~0.37。

2. **井筒存储修正对相关性几乎没有影响**：即使 C_wb=5.0（极端值），effective volume 变化 < 2%，pkn volume 变化 < 1%。这是因为 P_shut − P_closure 差值有限（~10–15 MPa），所以 V_storage = C_wb × ΔP 在 V_total ~ 3000 m³ 面前很小。

3. **射孔摩阻对 PKN volume 有小幅影响**：perf=5 MPa 使 PKN volume vs 微地震 Pearson 从 0.248 降到 ~0.22，影响方向是降低 net pressure 从而降低体积估算。

4. **f_eff 因子线性缩放不改变相关系数**：这是数学必然——对所有段等比缩放不改变 Pearson/Spearman。只有当 f_eff 按段变化时才会影响相关性。

5. **effective volume correction 当前只是小扰动**：raw 和 effective 的相关性几乎完全相同，说明当前井筒存储修正还没有实质意义。校准 C_wb 是未来 TODO（#15）。

## 7. 结论

**当前不是"没有负相关问题"。** 正确表述是：

- 旧半缝长口径结果为**负相关**（Pearson -0.36 ~ -0.39 vs 微地震）；
- 当前 PKN 体积口径结果为**弱正相关**（Pearson 0.25 ~ 0.37 vs 微地震，0.31 ~ 0.40 vs 广域电磁）；
- 方向从负变正，但**幅度仍然很弱**；
- 这说明**模型输出口径与观测口径仍需校准**；
- **不能说已经验证反演有效**，只能说体积口径比长度口径更接近一致趋势；
- Spearman 弱于 Pearson，说明 rank consistency 不强，可能被极端值或段型差异驱动。

## 8. 下一步

1. **人工 plot review**：逐段检查 G·dP/dG 和 dP/dG 曲线，确认 Barree tangent departure 和 McClure compliance minimum 的物理合理性；
2. **Barree / McClure candidate 复核**：量化 fit uncertainty，评估 fit_fraction 和 residual_sigma_factor 敏感性；
3. **主动放压 / 水锤剔除**：当前依赖人工 `--valid-falloff-end-elapsed`，需要自动识别；
4. **Barree tangent slope / leakoff coefficient 稳定段识别**：检查 slope 是否在段间具有一致性；
5. **更严格有效进缝液量修正**：标定井筒存储系数、射孔摩阻公式、液体类型修正；
6. **分段型相关性**：按常规段 / 裂缝影响段 / 断层段分组计算相关性，而不是全段混算；
7. **Stage 4 / 25 人工补审**：确认是否存在可用压降窗口；
8. **最终论文工作流**：必须包含人工 plot review 后才能标记 `closure_is_final_interpretation=True`。

## 禁止表述

- 不能把任何结果写成"已确定闭合压力"；
- 不能写成"体积反演已验证有效"；
- 不能写成"PKN 体积解释了微地震/电磁观测"；
- 不能写成"电磁面积被有效进缝液量解释"——那只是施工规模控制变量；
- 不能抹掉旧半缝长口径的负相关事实；
- 相关性只是统计关联，不是因果关系。
