# G函数闭合候选 physical PKN 体积与微地震/广域电磁对照

本文件是 sprint 分支 Phase 5D.3 的组会汇报材料。
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

## 2. 研究对象

本研究对象为平台4井 30 段。当前 Phase 4F/4K 有效自然压降窗口 manifest 覆盖 28 段，stage 4 和 stage 25 暂缺有效 falloff candidate，因此在 closure-batch / physical PKN 输出中保留为 placeholder。相关性默认只使用 28 个 finite physical PKN estimate；若后续人工补充 stage 4/25 的有效窗口，才能形成 n=30 的完整计算对照。

- 30-stage full-well table；
- 28 computed under current manifest；
- 2 explicit placeholders（stage 4, 25: `missing_estimate_reason=no_valid_falloff_manifest_row`）。

## 3. 旧结果：半缝长口径负相关

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

## 4. Phase 5D physical PKN 实现

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
- volume balance per cluster per stable-segment row：`L_i = η_i · V_inj / Σ(unit_j · η_j)`。

关键说明：

- canonical `pkn_fracture_volume_m3` 现在是 physical PKN，不再是 MVP；
- legacy MVP 已降级为 `legacy_mvp_pkn_*` 字段；
- I_F = 0.722464726919 目前按人类指定常数固定；积分表达式确认仍在 TODO；
- I_F 在 volume-balance 中代数消去（同时出现在裂缝存储项和泄滤系数 C 中），因此最终 V_f 值与 I_F 无关，但 I_F 影响计算中间量（半缝长 L 和泄滤系数 C）。

### 4.2 Coupled stress-shadow assumption（Phase 5D.3）

Phase 5D.3 起，baseline 流量分配 η_i 不再 uniform，改为 stress-shadow-weighted：

```
η_i = ξ_i^γ / Σ_j(ξ_j^γ)
```

默认 γ=1，即 `η_i = ξ_i / Σξ_i`。

含义：应力阴影越强的簇（ξ_i 越小），分配到的流量比例越小。

当前 coupled stress-shadow assumption：

- ξ_i 影响 P_net_i = ξ_i × (P - perf - σ_min)；
- ξ_i 影响 C_L_i（泄滤系数）；
- ξ_i 影响 η_i（流量分配）。

uniform η_i = 1/n 只作为 control，不再是 baseline。

**重要发现**：stress-shadow-weighted η_i 改变了逐簇半缝长和体积分配，但由于 volume-balance 公式的代数结构（`Σ V_f_i = V_inj × Σ(η_i × unit_i) / Σ(η_j × unit_j) = V_inj`），stage-level total physical storage volume 对 η_i 分配不敏感。shadow_eta 和 uniform_eta 的 stage total volume 完全相同。因此 stage-level 相关性不受 flow allocation 方法影响。

后续若要让 flow allocation 改变 stage total volume，需要更完整的 coupled model（如簇级流量不平衡导致不同簇的泄滤面积/时间不同）。

闭合候选覆盖：

- physical PKN 使用 selected closure candidate（Barree 优先，McClure 备选）；
- 28 段中 27 段使用 Barree tangent closure；1 段（stage 5）Barree not_found，使用 McClure compliance closure；
- 两者都失败才 not_computed；当前 0 段物理失败。

## 5. 当前核心相关性

### 5.1 主指标（n=28）

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| **physical pkn_fracture_volume_m3** | **microseismic_affected_volume** | **-0.259** | **-0.292** | 28 |
| **physical pkn_fracture_volume_m3** | **electromagnetic_affected_area** | **0.075** | **0.170** | 28 |
| no-shadow physical pkn (α=0) | microseismic_affected_volume | -0.259 | -0.292 | 28 |
| no-shadow physical pkn (α=0) | electromagnetic_affected_area | 0.075 | 0.170 | 28 |

### 5.2 半缝长指标

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| physical pkn_half_length_mean_m | microseismic_affected_volume | -0.134 | -0.081 | 28 |
| physical pkn_half_length_mean_m | electromagnetic_affected_area | -0.096 | -0.199 | 28 |
| legacy MVP pkn_half_length_mean_m | microseismic_affected_volume | 0.295 | 0.259 | 28 |
| legacy MVP pkn_half_length_mean_m | electromagnetic_affected_area | -0.049 | -0.176 | 28 |

### 5.3 Legacy MVP 与控制变量

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| legacy MVP pkn_fracture_volume_m3 | microseismic_affected_volume | 0.248 | 0.205 | 28 |
| legacy MVP pkn_fracture_volume_m3 | electromagnetic_affected_area | 0.335 | 0.062 | 28 |
| raw_injected_volume_m3 | electromagnetic_affected_area | 0.807 | 0.250 | 28 |
| effective_injected_volume_m3 | electromagnetic_affected_area | 0.807 | 0.250 | 28 |
| raw_injected_volume_m3 | microseismic_affected_volume | 0.120 | 0.188 | 28 |

### 5.4 解读

- physical PKN 体积与微地震波及体积呈**负相关**（Pearson -0.259, Spearman -0.292, n=28）；
- physical PKN 体积与广域电磁面积仅**弱相关**（Pearson 0.075, Spearman 0.170, n=28）；
- legacy MVP 体积与微地震呈弱正相关（Pearson 0.248），说明 physical PKN 链路（stable segment / C / volume balance）与简化 MVP（Sneddon average width）对 stage 间排序不同；
- physical PKN 半缝长与微地震也为弱负相关（-0.134），方向与旧半缝长口径的负相关一致；
- physical formula 后负相关没有消失，是科研结果，不是要掩盖的问题；
- **不能说"验证成功"**。

## 6. 为什么会出现负相关

只写候选解释，不写定论：

- G函数/PKN体积更接近压力响应等效主缝储集体积；
- 微地震波及体积更接近事件云/裂缝网络波及范围；
- 广域电磁面积更接近导电流体波及响应；
- 主缝储集体积越集中，未必对应更大的微地震波及体积；
- 裂缝影响段 2–7、断层段 24、缺窗口段 4/25 混在全段相关性中；
- stable segment / closure candidate / C 的自动选择仍需人工复核；
- water hammer / early transient 可能影响早期导数；
- 有效液量、射孔摩阻、井筒存储尚未完成标定。

## 7. stress shadow 解释

stress shadow linear system `(I + αF)ξ = 1` 已运行（α=1.0 baseline + α=0 no-shadow control）。

- stage-level total physical storage volume 在 baseline（α=1）与 no-shadow control（α=0）中完全相同；
- 这是因为当前 linear volume-balance formulation 中，stress shadow 主要改变簇间半长分配（α=1 时边缘簇更长、中心簇更短），但由于按总注入体积归一化求解，stage-level total physical storage volume 不变；
- 因此本轮 stage-level 相关性不受 shadow control 影响；
- 后续若要让 stress shadow 改变 stage total volume，需要重新定义体积约束或簇间流量分配模型。

## 8. I_F 说明

- I_F = 0.722464726919，人类指定常数；
- I_F 在 volume-balance 代数中消去：V_f = π/E' × V_inj × ratio_i / Σ(K_j × ratio_j) × H_w² × P_net_i，其中 K_j 不含 I_F；
- I_F 影响中间量：半缝长 L ∝ 1/I_F，泄滤系数 C ∝ I_F；
- 最终 V_f 对 I_F 不敏感；
- 积分表达式确认仍在 TODO。

## 9. 组会建议讲法

1. 已实现 physical PKN storage volume，不再使用旧 MVP 体积作为主指标；
2. 30 段 full-well output，28 段 computed（27 Barree + 1 McClure），2 段 placeholder（stage 4/25 缺有效 falloff）；
3. physical PKN 体积与微地震波及体积呈负相关（Pearson -0.259, n=28）；
4. 这说明 G函数/PKN 等效体积与微地震/电磁波及量存在口径差异，不能简单认为外部观测会正相关验证；
5. 下一步应人工复核闭合候选、稳定段 C、段型分类和有效液量标定。

## 10. 明确不能写

禁止写：

- "G函数反演体积已被微地震验证"；
- "G函数反演体积已被广域电磁验证"；
- "负相关问题已经消失"；
- "physical PKN 结果证明模型错误"；
- "closure pressure 已最终确定"；
- "全井只有 28 段"（正确：30 段 full-well，28 computed under current manifest）。

可以写：

- "physical PKN 体积与微地震波及体积呈负相关，是当前最重要的待解释结果"；
- "外部观测与 G函数反演体积之间可能存在物理口径差异"；
- "当前结果是 candidate/estimate，需要人工图形复核"；
- "旧半缝长口径的负相关仍然存在于历史数据中"。

## 11. Figures

Figures generated outside repo under `/tmp/gfunction-ref-audit-phase5d2/figures/`
